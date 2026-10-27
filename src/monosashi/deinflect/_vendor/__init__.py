"""Vendored deinflection engine and Japanese rule table.

Source: anki_miner at commit 77088491a2116b9a144ab918d362251c87dc4872
(GPL-3.0-or-later), which ports Yomitan commit e2ed450c2f11a591922822e77f008e70a87daf0c.

- ``transforms.py`` is ``anki_miner/services/japanese_transforms.py``, unmodified.
- ``engine.py`` is ``anki_miner/services/deinflection.py`` lines 1-255 plus
  ``conditions_match_mask``. The helpers that read MeCab tokens
  (``find_highlight_end``, ``resolve_dictionary_form``) are left out, because
  monosashi only deinflects plain strings.

Re-vendor by copying the same ranges again; do not edit these files in place.
"""
