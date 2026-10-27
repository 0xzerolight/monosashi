# Attribution

## Dictionaries

- **JMdict and JMnedict**, © Electronic Dictionary Research and Development Group, used under [CC BY-SA 4.0](https://www.edrdg.org/edrdg/licence.html). The JSON editions come from [jmdict-simplified](https://github.com/scriptin/jmdict-simplified); the pinned versions are in `data/sources.toml`. The full snapshot is downloaded into a local cache and never committed. `tests/fixtures/jmdict-mini.json` and `tests/fixtures/jmnedict-mini.json` are small excerpts, cut by `scripts/make_jmdict_fixture.py`, under the same license.

Gold entry ids refer to JMdict and JMnedict, so the gold data is distributed under CC BY-SA 4.0 (`data/LICENSE`).

## Code

- **Deinflection rule table and engine** (`src/monosashi/deinflect/_vendor/`): from [Yomitan](https://github.com/yomidevs/yomitan) (GPL-3.0), commit e2ed450c2f11a591922822e77f008e70a87daf0c, through its Python port in anki_miner (GPL-3.0-or-later), commit 77088491a2116b9a144ab918d362251c87dc4872. © 2024-2026 Yomitan Authors, © 2026 anki_miner contributors.

## Sentence sources

Each record names its source and license in its own `source` field; the pinned downloads, with sha256s, are in `data/sources.toml`. Raw corpora stay in a local cache; only the selected sentences are committed.

- **Tatoeba** (https://tatoeba.org), Japanese sentences, [CC BY 2.0 FR](https://creativecommons.org/licenses/by/2.0/fr/). Each record links its sentence and names its owner. Only sentences whose owner declares native Japanese are used.
- **Aozora Bunko** (https://www.aozora.gr.jp), new-orthography editions of works in the public domain in Japan, the US and the EU (the author died by 1945, or by 1955 with the work published before 1931). Each record names the work; the volunteers who typed and proofread each text are credited in `data/sources.toml`.
- **UD Japanese GSD** r2.18 (https://github.com/UniversalDependencies/UD_Japanese-GSD), © Google, Megagon Labs Tokyo and NINJAL, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Only the sentence text is used.
- **Synthetic sentences** (`data/synthetic/`), written for monosashi by Claude (Anthropic), CC BY-SA 4.0 with the rest of the data.

### Seeds

The seed sentences are the test sentences of three tokenizers. They quote song lyrics and novels, so their text is not distributed: their gold records are in `data/seed-labels/` without the text or the units' surfaces. `scripts/import_seeds.py` rebuilds `data/seeds/` from each tool's pinned source (anki_miner's from a clone: `--anki-miner PATH`), and `scripts/seed_labels.py rebuild` puts the text back, into `data/private/core/`.

- **ichiran** test suite (`tests.lisp`, https://github.com/tshatrov/ichiran), MIT:

  > Copyright (c) 2014 Timofei Shatrov
  >
  > Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
  >
  > The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
  >
  > THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

- **Jiten** test suite (`Jiten.Tests/MorphologicalAnalyserTests.cs`, https://github.com/Sirush/Jiten), © Sirush and contributors, [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0). The sentences are reproduced without modification apart from Unicode normalization; Jiten ships no NOTICE file.
- **anki_miner** parse corpus (https://github.com/0xzerolight/anki_miner), © 0xzerolight, relicensed CC BY-SA 4.0 by its author for this data set.
