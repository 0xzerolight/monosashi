"""Category taxonomy (SPEC.md §6).

A category names the hard thing one unit stands for; it is attached to that
unit's ``targets``, and a record's categories are the union over its units.
Most categories descend from anki_miner's parse-benchmark corpus; heteronym,
counter-reading, name and kansai are new. SPEC.md §6 prints each
definition word for word, and a test keeps the two in step.
"""

from __future__ import annotations

CATEGORIES: dict[str, str] = {
    # Unit boundaries
    "compound": "A compound or lexical phrase that is one JMdict entry (一人暮らし, 気に入る, どうでもいい).",
    "grammar-expression": "An expression of function words, the copula or auxiliaries that is one JMdict entry (かもしれない, ですか, んです).",
    "inflection-chain": "A verb or adjective with two or more transforms in its chain (食べさせられなかった).",
    "te-auxiliary": "A chain through て + いる/しまう/おく/みる/くる/いく/ある/あげる/くれる/もらう/ほしい, contracted or not (始めてしまった, 食べちゃった, 見せてもらった).",
    "contraction": "A colloquial contraction, inside a chain or as its own entry (ちゃう, てる, なきゃ, ねえ, わかんない, こりゃ).",
    "suru-verb": "A noun + する unit mapped to the noun's entry (勉強している).",
    "counter": "A number + counter unit (三本, 二人, 5回).",
    "prefix": "A word with a prefix, joined by its entry or as a separate unit; tagged on the word (ご注文, お|仲間).",
    "suffix": "A word with a suffix, joined by its entry or as a separate unit; tagged on the word (田中|さん, 学生|たち).",
    "long-compound": "A kanji run of four or more characters that is not one entry, tagged on each of its content units (選挙管理委員会).",
    "katakana": "A katakana loanword or run, including runs that tempt a mis-split (アイス|ベア).",
    "name": "A proper name of an individual: a person, place, organization, work or product.",
    "kana-written": "A word usually written in kanji, written in kana (きれい, すごい, わかる); not where kana is standard.",
    # Forms
    "jiru-zuru": "An inflected じる/ずる verb, whichever headword its surface forces (感じた -> 感じる, 感ぜられ -> 感ずる).",
    "archaic-classical": "A classical or archaic form, including historical kana (美しき, せねば, ざる).",
    "potential-ranuki": "A chain with a potential transform, ra-nuki or not (見れる, 来れる, 書ける, 食べられる).",
    "kanji-variant": "A spelling JMdict lacks, or marks irregular, outdated or search-only, for a word it lists (塗みれた, 寝ころがる, ヴォイド).",
    "colloquial-variant": "A variant with its own entry and a normalized block naming the standard word (すげー -> すごい).",
    "elongation": "A visibly stretched surface: a long vowel, 〜, an added small kana or an emphatic っ (すご〜い, 手ぇ, ほんっと).",
    "kana-run": "A run of repeated kana or an interjection made of one (どおおお, あああ).",
    "katakana-form": "A word normally written in hiragana or kanji, written in katakana (ヤル, ワタシ, スゴイ).",
    # Readings
    "heteronym": "A spelling with readings in common use that belong to different words or senses, picked by context (一日, 何, 方); not free variants (行く いく/ゆく).",
    "counter-reading": "Any reading change where a number meets a counter or another kanji (三本 さんぼん, １４人 じゅうよにん, 一切 いっさい).",
    "kinship": "A kinship or address term written with kanji whose kanji take a reading they have only in such terms (お兄ちゃん おにいちゃん).",
    # Robustness
    "kansai": "Kansai-ben forms (へん, やん, あかん, ちゃう, おおきに).",
    "ellipsis-truncation": "A word actually cut off by an ellipsis or a stammer (欲し…, あ、あの); not a whole word that trails off.",
    "onomatopoeia": "A mimetic or sound-symbolic word (ドキドキ, ふわふわ).",
    "oov": "A content word JMdict lacks in the sense used (slang, a technical term, a loanword); never a name or an unlisted spelling.",
}
