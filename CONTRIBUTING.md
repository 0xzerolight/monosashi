# Contributing to monosashi

Thanks for helping out. monosashi is a solo-maintained benchmark, and contributions of any size are welcome: a wrong gold label, a new tool, a fix to the scorer, a clearer rule.

## Before you start

- Bugs, gold-label errors and new tools: open an [Issue](https://github.com/0xzerolight/monosashi/issues) with the matching template.
- Questions and discussion: [Discussions](https://github.com/0xzerolight/monosashi/discussions).
- Security vulnerabilities: see [SECURITY.md](SECURITY.md). Do not open a public issue.
- Code of Conduct: see [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
- What a gold label means: [SPEC.md](SPEC.md). It is the authority; where a label and the spec disagree, the spec wins.

## Development setup

```bash
git clone https://github.com/0xzerolight/monosashi.git
cd monosashi
uv sync                          # Python 3.12, with the dev tools
uv run monosashi jmdict build    # the pinned JMdict + JMnedict, indexed into ~/.cache/monosashi (MONOSASHI_CACHE overrides)
```

The light adapters (fugashi, Sudachi) live in the optional `adapters` group: run them with `uv run --group adapters`. The heavy ones each have their own setup in `adapters/<name>/README.md`.

## Workflow

1. Fork the repo and create a branch from `main`.
2. Keep PRs focused: one fix, one tool or one rule change per PR.
3. Run the gate (below).
4. Add an entry under `## [Unreleased]` in [CHANGELOG.md](CHANGELOG.md).
5. Open the PR against `main`. The PR template will populate automatically.

Conventional Commits are preferred (`feat:`, `fix:`, `docs:`, `test:`, `ci:`, `chore:`).

## The gate

`scripts/health.sh` is what CI runs: `uv sync --locked`, `ruff check`, `ruff format --check`, `mypy` (strict) and `pytest`. It prints `SUMMARY GREEN` or `SUMMARY RED` and exits non-zero on red. Its `uv sync` removes the `adapters` group, so don't run it while an adapter run is going.

## Tests

- Tests build their JMdict index from `tests/fixtures/jmdict-mini.json`; they never fetch or touch the real cache. A test that needs a new entry adds its spelling to `scripts/make_jmdict_fixture.py` and regenerates the fixture from the real snapshot.
- `tests/test_validate.py` keeps one deliberate breakage per validator rule; a new rule gets one there.
- Every worked example in SPEC.md is a record in `tests/fixtures/spec-examples.jsonl`, tested in both directions.
- The mini fixture lacks most homographs, so probe a rule change against the real index too (`uv run monosashi validate data/core/*.jsonl`).

## Fixing a gold label

1. Find the record in `data/core/*.jsonl` by its id, and the rule in SPEC.md that decides it.
2. Fix the unit. `uv run monosashi candidates 'TEXT'` lists every JMdict entry that could match, and `uv run monosashi jmdict lookup WORD` shows one spelling's entries.
3. Run `uv run monosashi validate data/core/*.jsonl`.
4. In the PR, name the record id and the SPEC section, and say why the old label was wrong.

If the rule itself is unclear or wrong, open an issue instead: changing a rule changes every record it touches.

## Changing the spec

- A labeling rule change bumps the version at the top of SPEC.md and adds a changelog line. Records labeled under the older version then fail validation until they are re-checked.
- A scoring rule (§7) changes no label, so records keep their version; the changelog line says "scoring".
- A rule the validator can check gets a named rule in `validate.py`, listed in §8, and a breakage in `tests/test_validate.py`.

## Adding a tool

1. Write an adapter: a command that reads `{"id", "text"}` lines on stdin and answers each with `{"id", "units": [...], "ms"}`. Offsets count Unicode code points, end exclusive; adapters for Node, .NET and Rust convert from UTF-16 or bytes. The contract is in [predictions.py](src/monosashi/predictions.py); [protocol.py](src/monosashi/adapters/protocol.py) is a standard-library helper.
2. `--describe` prints the tool's name, version, commit, dictionary and dictionary date, whether its units cover the whole sentence, and which optional fields it outputs (`form`, `reading`, `form_reading`, `entries`, `kind`). A tool is scored only on the fields it outputs.
3. List it in [adapters/registry.toml](adapters/registry.toml).
4. A tool that needs more than this repo's venv gets its own directory, `adapters/<name>/`, with a README that pins every third-party source by commit SHA (or release + sha256) and gives the exact setup commands. Nothing heavy runs in CI.
5. Run it (`uv run monosashi run NAME`) and score it (`uv run monosashi score runs/NAME`). Run a tool as its users can: a setting changed from its defaults goes in its README and in `NOTES` in `src/monosashi/report.py`, which RESULTS.md prints next to its scores.

## Results

When predictions change, rerun `uv run monosashi score runs/* --out RESULTS.md`, commit the run's predictions to `results/<tool>/` (seed records left out), and update the table in README.md.

## Data rules

- Every record carries its source and license. `tests/test_licenses.py` checks them against the allowlist in `src/monosashi/licenses.py`.
- Every download is pinned in `data/sources.toml` with its URL, version, license, attribution and sha256, and fetched hash-checked. Raw corpora stay in the cache and are never committed; only selected sentences are, with attribution.
- Never commit text that isn't free to publish. The seed records quote song lyrics and novels, so their labels ship without text in `data/seed-labels/`.

## License

By contributing, you agree that your code is licensed GPL-3.0-or-later and your data CC BY-SA 4.0, as the rest of the repo.
