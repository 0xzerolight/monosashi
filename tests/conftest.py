from __future__ import annotations

from pathlib import Path

import pytest

from monosashi.jmdict import Dictionary, build_index

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def index_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("jmdict") / "mini.sqlite"
    build_index(
        FIXTURES / "jmdict-mini.json", FIXTURES / "jmnedict-mini.json", out, {"jmdict_version": "mini"}
    )
    return out


@pytest.fixture(scope="session")
def dictionary(index_path: Path) -> Dictionary:
    return Dictionary(index_path)
