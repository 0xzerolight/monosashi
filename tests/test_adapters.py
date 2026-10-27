"""Light adapters on fixed sentences; skipped where the tool is not installed (CI)."""

from __future__ import annotations

import importlib
import importlib.util
import shutil
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

from monosashi.jmdict import repo_root
from monosashi.runner import describe, load_registry, run
from monosashi.schema import UNIT_KINDS

SENTENCES = [
    "彼女は一人暮らしを始めてしまった。",
    "食べちゃった",
    "𠮷野家で３つ食べた",
    "すご〜い！",
    "田中さん、来て",
]
# How long a readiness probe waits for docker; a hung daemon skips the test instead of hanging it.
DOCKER_PROBE_TIMEOUT_S = 30


@pytest.mark.parametrize(
    ("module", "tool"),
    [("monosashi.adapters.fugashi_unidic", "fugashi"), ("monosashi.adapters.sudachi", "sudachipy")],
)
def test_adapter_units_match_the_text(module: str, tool: str) -> None:
    pytest.importorskip(tool)
    adapter = importlib.import_module(module)
    for text in SENTENCES:
        units = adapter.analyze(text)
        assert units, text
        for u in units:
            assert text[u["start"] : u["end"]] == u["surface"], (text, u)
            assert u["kind"] in {"word", "name", "interjection", "particle", "auxiliary", "prefix", "suffix"}
        assert [u["start"] for u in units] == sorted(u["start"] for u in units)


def test_fugashi_reads_the_dictionary_form() -> None:
    pytest.importorskip("fugashi")
    from monosashi.adapters.fugashi_unidic import analyze

    by_surface = {u["surface"]: u for u in analyze("始めてしまった")}
    assert by_surface["始め"]["form"] == "始める"
    assert by_surface["始め"]["form_reading"] == "はじめる"


def test_sudachi_reads_an_uninflected_form_in_context() -> None:
    pytest.importorskip("sudachipy")
    from monosashi.adapters.sudachi import analyze

    by_surface = {u["surface"]: u for u in analyze("あの方")}
    assert (by_surface["方"]["reading"], by_surface["方"]["form_reading"]) == ("かた", "かた")  # not ほう


def test_himotoki_units_match_the_text(tmp_path: Path) -> None:
    spec = load_registry()["himotoki"]
    python = repo_root() / spec.command[0]
    if (
        not python.exists()
        or subprocess.run([python, "-c", "import himotoki_rs"], capture_output=True).returncode != 0
        or not Path(spec.env["HIMOTOKI_DB_PATH"]).exists()
    ):
        pytest.skip("himotoki-rs is not built (adapters/himotoki/README.md)")
    d = describe(spec)
    assert d.partition and set(d.fields) == {"form", "reading", "form_reading", "entries", "kind"}
    texts = [*SENTENCES, "彼らは読み方を知らない", "量が多すぎる"]
    with (tmp_path / "stderr.log").open("w", encoding="utf-8") as log:
        predictions = list(run(spec, [(str(i), text) for i, text in enumerate(texts)], log))
    for text, p in zip(texts, predictions, strict=True):
        assert p.status == "ok" and p.units, (text, p)
        for u in p.units:
            assert text[u.start : u.end] == u.surface, (text, u)
            assert u.kind in UNIT_KINDS, (text, u)
    by_surface = {u.surface: u for p in predictions for u in p.units}
    chain = by_surface["始めてしまった"]
    assert (chain.form, chain.form_reading, chain.entries) == ("始める", "はじめる", (1307550,))
    assert by_surface["は"].kind == "particle"
    # himotoki lists the compounds 彼+ら and 読み+方 before the entries 彼ら and
    # 読み方, which score higher; like ichiran, the adapter reports the entries.
    assert (by_surface["彼ら"].form, by_surface["彼ら"].entries[0]) == ("彼ら", 1483090)
    assert (by_surface["読み方"].form, by_surface["読み方"].entries[0]) == ("読み方", 1456330)
    # The reading is the chosen alternative's too: 多すぎる (440), not 多い+すぎる (432).
    many = by_surface["多すぎる"]
    assert (many.form, many.reading, many.form_reading) == ("多すぎる", "おおすぎる", "おおすぎる")


def test_unidic3_units_match_the_text(tmp_path: Path) -> None:
    spec = load_registry()["unidic3"]
    python = repo_root() / spec.command[0]
    probe = "import os, fugashi, unidic; assert os.path.exists(os.path.join(unidic.DICDIR, 'sys.dic'))"
    if not python.exists() or subprocess.run([python, "-c", probe], capture_output=True).returncode != 0:
        pytest.skip("the full UniDic is not set up (adapters/unidic3/README.md)")
    d = describe(spec)
    assert (d.dictionary, d.dictionary_date) == ("UniDic 3.1.0 (unidic)", "2021-08-31")
    assert d.partition and set(d.fields) == {"form", "reading", "form_reading", "kind"}
    texts = [*SENTENCES, "猫が猫を見た"]
    with (tmp_path / "stderr.log").open("w", encoding="utf-8") as log:
        predictions = list(run(spec, [(str(i), text) for i, text in enumerate(texts)], log))
    for text, p in zip(texts, predictions, strict=True):
        assert p.status == "ok" and p.units, (text, p)
        for u in p.units:
            assert text[u.start : u.end] == u.surface, (text, u)
            assert u.kind in UNIT_KINDS, (text, u)
    hajime = {u.surface: u for u in predictions[0].units}["始め"]
    assert (hajime.form, hajime.reading, hajime.form_reading) == ("始める", "はじめ", "はじめる")
    assert [u.start for u in predictions[-1].units if u.surface == "猫"] == [0, 2]


def test_anki_miner_units_match_the_text(tmp_path: Path) -> None:
    spec = load_registry()["anki_miner"]
    python = Path(spec.command[0])
    if (
        not python.exists()
        or subprocess.run([python, "-c", "import anki_miner"], capture_output=True).returncode != 0
        or not (Path(spec.env["ANKI_MINER_HOME"]) / "dicts" / "jmdict-english" / "index.sqlite").exists()
    ):
        pytest.skip("anki_miner or its dictionary is not set up (adapters/anki_miner/README.md)")
    adapter = _adapter("anki_miner")
    try:
        adapter.check_commit(python.parents[2])  # the venv lives in the checkout
    except SystemExit as off_pin:
        pytest.skip(str(off_pin))  # the adapter refuses to start; the refusal has its own test
    d = describe(spec)
    assert not d.partition and set(d.fields) == {"form", "form_reading"}
    assert d.commit == adapter.PINNED_COMMIT
    # anki_miner normalizes Kangxi radicals and halfwidth katakana before parsing, so
    # its offsets must be mapped back, one word at a time within a rewritten run.
    texts = [*SENTENCES, "⾞⼀台を⾒た", "ﾋﾟｱﾉ･ｷﾞﾀｰを弾く"]
    with (tmp_path / "stderr.log").open("w", encoding="utf-8") as log:
        predictions = list(run(spec, [(str(i), text) for i, text in enumerate(texts)], log))
    for text, p in zip(texts, predictions, strict=True):
        assert p.status == "ok", (text, p)
        for u in p.units:
            assert text[u.start : u.end] == u.surface, (text, u)
    cards = {u.surface: (u.form, u.form_reading) for p in predictions for u in p.units}
    assert cards["始めてしまった"] == ("始める", "はじめる")
    assert [u.surface for u in predictions[-2].units] == ["⾞", "⼀台", "⾒た"]
    assert [u.surface for u in predictions[-1].units] == ["ﾋﾟｱﾉ", "ｷﾞﾀｰ", "弾く"]
    assert cards["ﾋﾟｱﾉ"] == ("ピアノ", "ぴあの")


def _skip_without_ichiran(container: str) -> None:
    try:
        ready = subprocess.run(
            ["docker", "exec", container, "test", "-x", "/usr/local/bin/ichiran-cli"],
            capture_output=True,
            timeout=DOCKER_PROBE_TIMEOUT_S,
        )
    except FileNotFoundError:
        pytest.skip("docker is not installed")
    except subprocess.TimeoutExpired:
        pytest.skip("docker did not answer")
    if ready.returncode != 0:
        pytest.skip(f"ichiran's container {container} is not up (adapters/ichiran/README.md)")


def test_ichiran_units_match_the_text(tmp_path: Path) -> None:
    spec = load_registry()["ichiran"]
    _skip_without_ichiran(spec.env["ICHIRAN_CONTAINER"])
    d = describe(spec)
    assert d.partition and set(d.fields) == {"form", "reading", "form_reading", "entries", "kind"}
    # ichiran normalizes the text (３ → 3, ﾋﾟ → ピ, 。 → ". "), so its offsets must be mapped back.
    texts = [*SENTENCES, "叫びです。食べさせられた", "ﾋﾟｱﾉ･ｷﾞﾀｰを弾く"]
    with (tmp_path / "stderr.log").open("w", encoding="utf-8") as log:
        predictions = list(run(spec, [(str(i), text) for i, text in enumerate(texts)], log))
    for text, p in zip(texts, predictions, strict=True):
        assert p.status == "ok" and p.units, (text, p)
        for u in p.units:
            assert text[u.start : u.end] == u.surface, (text, u)
            assert u.kind in UNIT_KINDS, (text, u)
    by_surface = {u.surface: u for p in predictions for u in p.units}
    chain = by_surface["始めてしまった"]
    assert (chain.form, chain.form_reading, chain.entries) == ("始める", "はじめる", (1307550,))
    assert (by_surface["は"].kind, by_surface["は"].reading) == ("particle", "は")
    assert by_surface["３つ"].entries == (2220330,)
    # A JMdict entry that is a conjugated form keeps its own seq first; a
    # conjugation of a conjugation (via 食べさせる) still reaches its root.
    assert (by_surface["です"].kind, by_surface["です"].entries[0]) == ("copula", 1628500)
    via = by_surface["食べさせられた"]
    assert (via.form, via.entries) == ("食べる", (1358280,))
    assert [(u.surface, u.form) for u in predictions[-1].units][:2] == [("ﾋﾟｱﾉ", "ピアノ"), ("ｷﾞﾀｰ", "ギター")]


def _adapter(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"{name}_adapter", repo_root() / f"adapters/{name}/adapter.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_anki_miner_refuses_a_checkout_off_its_pin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _adapter("anki_miner")
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    plain = ["-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, *plain, "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    head = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    with pytest.raises(SystemExit, match=f"at {head}, not the pinned {adapter.PINNED_COMMIT}"):
        adapter.check_commit(tmp_path)
    monkeypatch.setattr(adapter, "PINNED_COMMIT", head)
    assert adapter.check_commit(tmp_path) == head


def test_ichiran_restarts_its_loop_when_it_falls_out_of_step() -> None:
    _skip_without_ichiran(load_registry()["ichiran"].env["ICHIRAN_CONTAINER"])
    adapter = _adapter("ichiran")
    loop = adapter._ichiran
    try:
        good = adapter.analyze("猫が見た")
        # A form that prints a line of its own, not JSON or JSON, leaves the loop a line behind.
        with pytest.raises(RuntimeError, match="not JSON"):
            loop.eval('(progn (princ "noise") (terpri) 1)')
        with pytest.raises(TypeError):
            adapter.analyze("猫が見た")  # reads the stray 1
        assert adapter.analyze("猫が見た") == good
        assert loop.eval("(progn (princ 1) (terpri) 2)") == 1
        with pytest.raises(TypeError):
            adapter.analyze("猫が見た")
        assert adapter.analyze("猫が見た") == good
        # A stale answer for another sentence: its words cannot be placed in this one.
        loop.proc.stdin.write(
            '(list (ichiran:romanize* "犬" :limit 1 :wordprop-fn (lambda (r w) (declare (ignore r))'
            " (ichiran/dict:word-info-json w))) nil)\n"
        )
        with pytest.raises(RuntimeError, match="not in the sentence"):
            adapter.analyze("猫が見た")
        assert adapter.analyze("猫が見た") == good
    finally:
        loop.reset()


def test_yomitan_units_match_the_text(tmp_path: Path) -> None:
    spec = load_registry()["yomitan"]
    home = Path(spec.env["YOMITAN_HOME"])
    if (
        shutil.which(spec.command[0]) is None
        or not (home / "src" / "ext" / "lib" / "zip.js").exists()
        or not (home / "src" / "node_modules" / "fake-indexeddb").exists()
        or not (home / "JMdict_english.zip").exists()
    ):
        pytest.skip("node, Yomitan or its dictionary is not set up (adapters/yomitan/README.md)")
    d = describe(spec)
    assert (d.dictionary_date, d.partition) == ("2026-10-12", True)
    assert set(d.fields) == {"form", "reading", "form_reading", "entries", "kind"}
    texts = [*SENTENCES, "猫が猫を見た"]
    with (tmp_path / "stderr.log").open("w", encoding="utf-8") as log:
        predictions = list(run(spec, [(str(i), text) for i, text in enumerate(texts)], log))
    for text, p in zip(texts, predictions, strict=True):
        assert p.status == "ok" and p.units, (text, p)
        for u in p.units:
            assert text[u.start : u.end] == u.surface, (text, u)
            assert u.kind is None or u.kind in UNIT_KINDS, (text, u)
    by_surface = {u.surface: u for p in predictions for u in p.units}
    chain = by_surface["始めてしまった"]
    assert (chain.form, chain.reading, chain.form_reading, chain.entries) == (
        "始める",
        "はじめてしまった",
        "はじめる",
        (1307550,),
    )
    assert by_surface["は"].kind == "particle"
    # Code points, not UTF-16: 𠮷 is one.
    assert (by_surface["𠮷野家"].start, by_surface["食べた"].start) == (0, 6)
    # A search-only spelling: jmdict-yomitan's negated seq, and no part of speech.
    stretched = by_surface["すご〜い"]
    assert (stretched.form, stretched.entries, stretched.kind) == ("すご〜い", (1374550,), None)
    assert [u.start for u in predictions[-1].units if u.surface == "猫"] == [0, 2]


def test_jiten_units_match_the_text(tmp_path: Path) -> None:
    spec = load_registry()["jiten"]
    container = spec.command[3]
    try:
        ready = subprocess.run(
            ["docker", "exec", container, "test", "-f", "/app/adapter/MonosashiJiten.dll"],
            capture_output=True,
            timeout=DOCKER_PROBE_TIMEOUT_S,
        )
    except FileNotFoundError:
        pytest.skip("docker is not installed")
    except subprocess.TimeoutExpired:
        pytest.skip("docker did not answer")
    if ready.returncode != 0:
        pytest.skip(f"Jiten's container {container} is not up (adapters/jiten/README.md)")
    d = describe(spec)
    assert (d.dictionary_date, d.partition) == ("2026-10-15", True)
    assert set(d.fields) == {"form", "form_reading", "entries", "kind"}
    texts = [*SENTENCES, "猫が猫を見た", "1人で来た", "でしたね。こうするしかない"]
    with (tmp_path / "stderr.log").open("w", encoding="utf-8") as log:
        predictions = list(run(spec, [(str(i), text) for i, text in enumerate(texts)], log))
    for text, p in zip(texts, predictions, strict=True):
        assert p.status == "ok", (text, p)
        for u in p.units:
            assert text[u.start : u.end] == u.surface, (text, u)
            assert u.kind in UNIT_KINDS, (text, u)
    # Jiten resolves no word in すご〜い, so it is all gap; every other sentence has words.
    assert [bool(p.units) for p in predictions] == [True, True, True, False, True, True, True, True]
    by_surface = {u.surface: u for p in predictions for u in p.units}
    chain = by_surface["始めてしまった"]
    assert (chain.form, chain.form_reading, chain.entries, chain.kind) == (
        "始める",
        "はじめる",
        (1307550,),
        "word",
    )
    assert by_surface["は"].kind == "particle"
    # Code points, not UTF-16: 𠮷 is one (Jiten's parser drops it, a gap).
    assert by_surface["食べた"].start == 6
    # A JMnedict entry keeps its own id; でした is the copula です.
    assert (by_surface["田中"].kind, by_surface["田中"].entries) == ("name", (5543705,))
    assert (by_surface["でした"].form, by_surface["でした"].entries, by_surface["でした"].kind) == (
        "です",
        (1628500,),
        "copula",
    )
    # The parser reads 1人 as １人; it is still placed on 1人. こうする is Jiten's own word, no entry.
    assert (by_surface["1人"].start, by_surface["1人"].entries) == (0, (1576150,))
    assert by_surface["こうする"].entries == ()
    assert [u.start for u in predictions[5].units if u.surface == "猫"] == [0, 2]
