# Labeling instructions

You label Japanese sentences for monosashi, a benchmark of tokenizers for language learners. Another labeler labels the same sentences without seeing your work, and the two labelings are compared unit by unit. Label each sentence the way `SPEC.md` says, not the way any tool would.

Everything you need is in your bundle, the directory the prompt names as `<BUNDLE>`. Paths below are relative to it, and `NAME` is your batch.

## Before you start

Read `SPEC.md` from start to end. It is the authority. Its worked examples (§9) are in `spec-examples.jsonl`; read that file too, since it shows the exact JSON of correct records. SPEC.md mentions a few repository paths, and you need none of them: `tests/fixtures/spec-examples.jsonl` is your `spec-examples.jsonl`, and §6 itself holds every category definition.

## What you get

- `NAME.input.jsonl`: one skeleton record per sentence, with `units` empty.
- `NAME.sheets.md`: for each sentence, its text, the tagger's category hints and the JMdict candidate sheet. Each candidate line is `[start:end] surface -> seq form【readings】 (pos) chain=... gloss`, where the gloss is only the start of the first sense. A ★ marks a common entry; `name` marks a JMnedict entry.
- `NAME.senses.md`: every sense of every entry on the sheets, one line per entry. SPEC §4 lets an entry win only when one of its senses fits the sentence, so judge a candidate by its senses here, not by the gloss on the sheet.

Record ids are opaque (`RUN-0001`), and `source`, `register` and `slice` are placeholders: every record says `blind`, `conversation` and `open`, wherever it comes from. Leave them as they are, and read each sentence for what it says.

## What you write

`labels/NAME.jsonl`: the same records, in the same order, with `units` filled in and every other field unchanged, `text` included (`label.status` stays `draft`). One JSON object per line.

## How to label a sentence

1. Decide the correct reading of the whole sentence in context first. A sentence too short to settle a reading takes the most frequent one (SPEC §5).
2. Cut it into units by SPEC §4: inflection chains as far as the deinflector carries them (the sheet's `chain=`), noun + する as one unit, the longest JMdict entry whose senses fit, numbers with their counters, names, words JMdict lacks. Punctuation, symbols and spaces belong to no unit.
3. Fill each unit's fields by SPEC §5. Take `entries`, `form`, `chain` and readings from the sheet whenever a candidate fits; when you are sure no candidate fits, follow §4.7 (no entry). Function units (`particle`, `copula`, `auxiliary`, `prefix`, `suffix`) have only `start`, `end`, `surface` and `kind`.
4. `targets`: tag every unit from the SPEC §6 definitions. The hints on the sheet are only suggestions: keep a hint's category on the unit that carries it when the definition fits, drop it when it doesn't, and add a category no hint names wherever a unit stands for it.
5. `split_points` on compounds and expressions whose parts are words (§4.3, §4.4).

Offsets are code points into `text`, end exclusive; `text[start:end]` must equal `surface`. Build the JSON with a short script in your scratch directory rather than by hand, so offsets and escaping are right.

## Check before you hand in

Run

    {monosashi} validate <BUNDLE>/labels/NAME.jsonl

and fix every issue until it prints `0 issue(s)`. A rule id in brackets names the SPEC §8 rule that failed. A line starting `note:` is an advisory: check that unit against the rule it cites, but it fails nothing. For anything the sheet and the senses do not answer, ask the dictionary the same way:

    {monosashi} candidates 'TEXT'
    {monosashi} jmdict lookup WORD

`jmdict lookup` lists each entry's spelling【reading】 pairs in JMdict's order, stars a reading JMdict marks common (`いちにち*`), and shows a spelling's JMdict tags in parentheses: `sK`/`sk` search-only, `iK`/`ik`/`io` irregular, `oK`/`ok` outdated, `rK`/`rk` rare, `ateji`.

## Rules

- Read nothing outside your bundle and your own scratch directory, and never open the repository's files. Your shell starts in the repository only because the labeling workflow runs there. Nothing technical keeps you out of it, so this rule holds only if you keep it; the three commands above are your only use of the repository.
- Never run a tokenizer or morphological analyzer. The sheets, the senses and the dictionary commands are your only tools.
- Write nothing except `labels/NAME.jsonl` and files in your own scratch directory (the prompt names it).
- When the spec does not settle a case, choose the reading a learner would look up, label it, and list the case under "Spec questions" in your final answer, with the record id and what was unclear.
