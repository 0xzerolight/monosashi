"""UniDic part-of-speech names to unit kinds, shared by the MeCab and Sudachi adapters.

The mapping is the minimum any consumer applies: function parts of speech
become function kinds, so a raw tool is not charged junk for its particles.
Symbols and spaces return None and are not output at all.
"""

from __future__ import annotations

_KINDS = {
    "助詞": "particle",
    "助動詞": "auxiliary",
    "接頭辞": "prefix",
    "接尾辞": "suffix",
    "感動詞": "interjection",
}
_SKIP = frozenset({"補助記号", "空白", "記号"})


def kind_of(pos1: str, pos2: str | None) -> str | None:
    if pos1 in _SKIP:
        return None
    if pos1 == "名詞" and pos2 == "固有名詞":
        return "name"
    return _KINDS.get(pos1, "word")
