"""Cut the test fixture (tests/fixtures/jmdict-mini.json, jmnedict-mini.json) from the pinned snapshot.

The fixture is real JMdict/JMnedict data (CC BY-SA 4.0, EDRDG), so tests
exercise the same shapes the full index holds. Re-run after a pin bump:

    uv run python scripts/make_jmdict_fixture.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from monosashi.jmdict import JMDICT, JMNEDICT, cache_dir, ensure_index, load_pins, repo_root

# Every entry with one of these spellings goes into the JMdict fixture.
JMDICT_SPELLINGS = [
    "彼女", "は", "を", "が", "に", "一人暮らし", "一人", "暮らし", "始める", "食べる", "凄い", "すげー",
    "勉強", "する", "気に入る", "かもしれない", "ですか", "そう", "一日", "学生", "見る", "いる",
    "しまう", "感じる", "感ずる", "本", "三本", "今日", "行く", "なる", "方", "彼", "私", "何", "宛がう", "嘘", "に決まっている", "ながら", "です", "か",
    "じゃない", "来る", "あの", "こっち", "仲間", "ご注文", "一日中", "知らせる",
    "やる", "分かる", "ＣＤ", "３つ", "明日", "付き合う", "可愛い", "美味しい", "ねえ", "やだ",
    "さん", "木", "二十", "十", "選挙", "管理", "委員会", "ならない",
    "見せる", "出る", "待つ", "言う", "やめる", "少ない", "一人で", "として", "賞与", "くれる",
    "に沿って",
    "塗れる", "ボイド", "どういう", "ほんと", "写る", "また", "思う", "って", "気", "気を付ける", "買う",
    "よ", "三歳", "歳", "年上", "頑張る", "灯明", "皿", "４", "得点", "日間", "世紀", "万", "時", "回目",
    "代目", "ずっと", "もっと", "全く", "食", "票", "円",
    "使える", "使う", "行う", "為れる", "了解", "帰る",
    "候補者", "候補", "者", "存じ", "候", "ざるを得ない", "けりをつける", "冊", "一切", "切", "書く", "欲しい",
    "欲", "お兄ちゃん", "おじいさん", "人", "年", "年間", "間", "つ", "いけない",
    "思える", "行ける", "用いる", "食べられる", "見れる", "ます", "階", "軒", "回", "分", "三階", "何階", "四分",
    "セント", "誘う", "眼を開く", "開ける", "聞き取る", "取れる", "話し合う", "合える",
    "キャンバス", "腹が減る", "ヴィオロン", "いいえ", "おめえ", "エールフランス", "おおきに",
]  # fmt: skip
# Names by id only: JMnedict has hundreds of entries per common spelling.
JMNEDICT_IDS = [
    *range(5543705, 5543715),
    5074354,
    5046507,
]  # 田中 (its ten person entries), ヘレナ, セントヘレナ島


def _cut(path: Path, keep: Any) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    words = [w for w in data["words"] if keep(w)]
    return {k: v for k, v in data.items() if k != "words"} | {"words": words}


def main() -> None:
    ensure_index()  # fetches and extracts the pinned archives
    pins = load_pins()
    extracted = cache_dir() / "extracted" / pins[JMDICT].version
    spellings = set(JMDICT_SPELLINGS)
    jmdict = _cut(
        next(extracted.glob("jmdict-eng-*.json")),
        lambda w: any(k["text"] in spellings for k in w.get("kanji", []) + w.get("kana", [])),
    )
    names = set(JMNEDICT_IDS)
    jmnedict = _cut(next(extracted.glob("jmnedict-all-*.json")), lambda w: int(w["id"]) in names)
    out_dir = repo_root() / "tests" / "fixtures"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, data in ((f"{JMDICT}-mini.json", jmdict), (f"{JMNEDICT}-mini.json", jmnedict)):
        with (out_dir / name).open("w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=0)
            fh.write("\n")
        print(out_dir / name, len(data["words"]), "entries")


if __name__ == "__main__":
    main()
