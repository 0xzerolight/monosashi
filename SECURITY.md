# Security Policy

## Reporting a vulnerability

Please do not open a public issue for security vulnerabilities.

Report privately via GitHub Security Advisories:
<https://github.com/0xzerolight/monosashi/security/advisories/new>

monosashi is maintained by a single person on a best-effort basis. You can expect an acknowledgment within a reasonable time.

## Scope

In scope:

- Downloads and their integrity checks: the pinned JMdict, JMnedict and corpora in `data/sources.toml`, fetched and sha256-checked by `monosashi jmdict build` and `monosashi pool`.
- The adapter runner: the commands it starts from `adapters/registry.toml`, and how it reads their output.
- The adapter setups in `adapters/<name>/` (Dockerfiles, compose files, build commands).

Out of scope:

- Vulnerabilities in the tools under test (ichiran, himotoki, Jiten, Yomitan, anki_miner, MeCab, Sudachi); report those to their projects.
- Issues requiring local filesystem write access already granted to the user, such as editing `adapters/registry.toml`.

## Supported versions

The latest release is supported.
