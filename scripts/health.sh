#!/usr/bin/env bash
# Definition-of-Done gate: sync, lint, format check, types, tests.
# Redirect the output to a file and read the exit code in a separate step;
# piping through tail would hide a red gate.
set -u
cd "$(dirname "$0")/.."

# Prefer the real uv binary; on this machine the uv on PATH is a plugin shim.
if [ -x "$HOME/.local/bin/uv" ]; then UV="$HOME/.local/bin/uv"; else UV=uv; fi

fail=0
step() {
    local name="$1"
    shift
    if "$@"; then
        echo "PASS $name"
    else
        echo "FAIL $name"
        fail=1
    fi
}

step sync "$UV" sync --locked --quiet
step ruff-check "$UV" run --no-sync ruff check .
step ruff-format "$UV" run --no-sync ruff format --check .
step mypy "$UV" run --no-sync mypy
step pytest "$UV" run --no-sync pytest

if [ "$fail" -eq 0 ]; then echo "SUMMARY GREEN"; else echo "SUMMARY RED"; fi
exit "$fail"
