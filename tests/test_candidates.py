from __future__ import annotations

import re
from pathlib import Path

from monosashi.jmdict import Dictionary
from monosashi.label import batches
from monosashi.label.candidates import candidate_sheet, format_senses, render_sheet
from monosashi.schema import Source
from monosashi.sources import Sentence


def test_sheet_offers_the_whole_chain_and_the_compound(dictionary: Dictionary) -> None:
    text = "彼女は一人暮らしを始めてしまった。"
    sheet = candidate_sheet(text, dictionary)
    found = {(c.start, c.end, c.entry.seq, c.form, c.chain) for c in sheet}
    assert (3, 8, 1613340, "一人暮らし", ()) in found
    assert (9, 16, 1307550, "始める", ("-て", "-しまう", "-た")) in found
    # Lone particles carry no candidates; nothing spans the final 。
    assert not any(c.start == 2 and c.end == 3 for c in sheet)
    assert all(c.end <= len(text) - 1 for c in sheet)


def test_sheet_maps_noun_suru_to_the_noun(dictionary: Dictionary) -> None:
    sheet = candidate_sheet("勉強している", dictionary)
    assert any(c.entry.seq == 1512670 and c.end == 6 and c.chain == ("-て", "-いる") for c in sheet)
    bare = candidate_sheet("勉強する", dictionary)
    assert any(c.entry.seq == 1512670 and c.end == 4 and c.chain == () and c.form == "勉強" for c in bare)
    # A godan rule (擦る) must not reach the noun: its conditions are not する's.
    assert not any(c.entry.seq == 1512670 and c.end == 5 for c in candidate_sheet("勉強すった", dictionary))


def test_sheet_follows_the_exp_only_te_auxiliary_rule(dictionary: Dictionary) -> None:
    # The sheet and the validator share stops_at_te_auxiliary: no として + くれる, 一人で + 行く.
    for text, seq in (("一人で行く", 1163700), ("一人でいる", 1163700), ("としてくれる", 1008590)):
        assert not any(c.entry.seq == seq and c.chain for c in candidate_sheet(text, dictionary)), text
    sheet = candidate_sheet("に沿うて", dictionary)
    assert any(c.entry.seq == 2215300 and c.chain == ("kansai-ben -て",) for c in sheet)
    sheet = candidate_sheet("に沿うている", dictionary)
    assert not any(c.entry.seq == 2215300 and c.chain == ("kansai-ben -て", "-いる") for c in sheet)


def test_sheet_reads_katakana_and_stretched_surfaces(dictionary: Dictionary) -> None:
    wakatta = candidate_sheet("ワカった", dictionary)
    assert any(c.form == "わかる" and c.chain == ("-た",) and c.end == 4 for c in wakatta)
    stretched = candidate_sheet("すご〜かった", dictionary)
    assert any(c.entry.seq == 1374550 and c.form == "すごい" and c.chain == ("-た",) for c in stretched)
    # A search-only surface is offered under its standard form.
    assert any(c.entry.seq == 1374550 and c.form == "すごい" for c in candidate_sheet("すご〜い", dictionary))


def test_sheet_lists_names_for_kanji_spans(dictionary: Dictionary) -> None:
    sheet = candidate_sheet("田中さん", dictionary)
    assert any(c.entry.is_name and c.entry.seq == 5543705 for c in sheet)


def test_rendered_sheet_is_one_line_per_candidate(dictionary: Dictionary) -> None:
    text = "すげー！"
    sheet = candidate_sheet(text, dictionary)
    rendered = render_sheet(text, sheet).splitlines()
    assert rendered[0] == f"TEXT {text}"
    assert len(rendered) == len(sheet) + 1
    assert any("2722660 すげー【すげー】" in line for line in rendered)


def test_sheet_reads_vowel_stretches(dictionary: Dictionary) -> None:
    sheet = candidate_sheet("すごおおかった", dictionary)
    assert any(
        c.entry.seq == 1374550 and c.form == "すごい" and c.chain == ("-た",) and c.end == 7 for c in sheet
    )
    assert any(c.entry.seq == 2029080 and c.end == 4 for c in candidate_sheet("ねえええ", dictionary))


def test_sheet_counters_need_a_real_counter_at_a_word_start(dictionary: Dictionary) -> None:
    sheet = candidate_sheet("二十本の木", dictionary)
    assert any((c.start, c.end, c.form, c.entry.seq) == (0, 3, "本", 1522150) for c in sheet)
    # A particle after a number is not its counter, and 二 inside a name starts no number.
    assert not any(c.end == 2 and c.form == "は" for c in candidate_sheet("三は", dictionary))
    assert not any(
        c.start == 1 for c in candidate_sheet("田二本", dictionary) if c.form == "本" and c.end == 3
    )
    # Only ctr nouns and the listed words count: 回目 is a suffix, so 2回目 is 2回|目.
    assert not any((c.start, c.end) == (0, 3) for c in candidate_sheet("2回目", dictionary))


def test_sheet_offers_man_oku_cho_after_digits(dictionary: Dictionary) -> None:
    # SPEC.md §4.4: 50万 is entry 万, form 万; in 50万円 the number is 50万 and the counter 円.
    assert any(
        (c.start, c.end, c.form, c.entry.seq) == (0, 3, "万", 1584460)
        for c in candidate_sheet("50万", dictionary)
    )
    assert any((c.start, c.end, c.form) == (0, 4, "円") for c in candidate_sheet("50万円", dictionary))
    # Only after digits, and only at the end of the number: 五十万 is a number alone, and
    # 5万3000円 is the number 5万3000 and the counter 円.
    assert not any(c.form == "万" and c.start == 0 for c in candidate_sheet("五十万", dictionary))
    sheet = candidate_sheet("5万3000円", dictionary)
    assert not any((c.start, c.end) == (0, 2) for c in sheet)
    assert any((c.start, c.end, c.form) == (0, 7, "円") for c in sheet)


def test_sheet_keeps_ascii_forms(dictionary: Dictionary) -> None:
    assert any(c.form == "3つ" and c.entry.seq == 1299740 for c in candidate_sheet("3つ", dictionary))


def test_sheet_reads_only_katakana_stems_as_hiragana(dictionary: Dictionary) -> None:
    # はメ is a particle and the start of a katakana word, not a spelling of a hiragana word.
    assert not any(c.start == 0 and c.end == 2 for c in candidate_sheet("はメ", dictionary))
    assert any(c.form == "わかる" for c in candidate_sheet("ワカる", dictionary))


def test_sheet_reads_a_stretch_only_when_the_surface_shows_one(dictionary: Dictionary) -> None:
    # かわいい is a word: no stretch reading of it as かわい.
    plain = [c for c in candidate_sheet("かわいい", dictionary) if (c.start, c.end) == (0, 4)]
    assert plain and all(c.form == "かわいい" for c in plain)
    assert any(
        c.form == "すごい" for c in candidate_sheet("すごおおい", dictionary) if (c.start, c.end) == (0, 5)
    )


def test_batch_senses_file(tmp_path: Path, dictionary: Dictionary) -> None:
    source = Source("t", "1", "CC-BY-SA-4.0", "x")
    texts = ["食べなければならない", "田中さんは行かなくてはならない"]
    sentences = [Sentence(f"t-{i}", t, source, "conversation", "open") for i, t in enumerate(texts)]
    assert batches.prepare(sentences, tmp_path, dictionary) == ["batch-001"]
    senses = (tmp_path / "batch-001.senses.md").read_text(encoding="utf-8")
    keys = re.findall(r"^((?:name )?\d+): 1\) ", senses, flags=re.MULTILINE)
    on_sheets = {
        f"{'name ' if c.entry.is_name else ''}{c.entry.seq}"
        for t in texts
        for c in candidate_sheet(t, dictionary)
    }
    assert sorted(keys) == sorted(on_sheets) and "name 5543705" in keys  # each entry once, names marked
    (naranai,) = [line for line in senses.splitlines() if line.startswith("2083990: ")]
    assert naranai == (
        "2083990: 1) cannot help (feeling); unbearably; awfully; irresistibly (exp) [as ...てならない]"
        " 2) must not ...; should not ... (exp) [as ...てはならない]"
        " 3) must ...; have to ...; ought to ... (exp) [as ...なくてはならない, ...なければならない, ...ねばならない, etc.]"
        " 4) cannot; unable to (exp) 5) not (exp; dated) [as ...ではならない]"
    )
    sheets = (tmp_path / "batch-001.sheets.md").read_text(encoding="utf-8")
    assert "batch-001.senses.md" in sheets.split("## ")[0]  # the header points to the senses file
    for t in texts:
        assert render_sheet(t, candidate_sheet(t, dictionary)) in sheets  # candidate lines unchanged


def test_senses_show_tags_and_restrictions(dictionary: Dictionary) -> None:
    hitori = dictionary.entry(1576150)  # 一人: senses 2-5 are ひとり only; sense 5 is usually kana (uk)
    assert hitori is not None
    assert format_senses(hitori) == (
        "1) one person (n) [esp. 一人, １人] 2) being alone; being by oneself (n) {only ひとり}"
        " 3) being single; being unmarried (n) [esp. 独り] {only ひとり} 4) by oneself; alone (adv) {only ひとり}"
        " 5) just; only; simply (adv; uk) [with neg. sentence] {only ひとり}"
    )
    hane = dictionary.entry(1171680)  # 羽 / 羽根: a kanji restriction
    assert hane is not None
    assert "5) shuttlecock (in hanetsuki) (n) [also written as 羽子] {only 羽根}" in format_senses(hane)


def test_sheet_offers_an_expression_whose_teiru_is_contracted(dictionary: Dictionary) -> None:
    # 嘘に決まってる: the expression に決まっている keeps its entry, with no chain (SPEC.md §4.3).
    offered = {
        (c.start, c.end, c.form, c.entry.seq, c.chain) for c in candidate_sheet("嘘に決まってる", dictionary)
    }
    assert (1, 7, "に決まっている", 2841446, ()) in offered
