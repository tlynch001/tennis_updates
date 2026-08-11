from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_RANKINGS_FIXTURE = REPO_ROOT / "data" / "sample" / "rankings_sample.json"
SAMPLE_MATCHES_FIXTURE = REPO_ROOT / "data" / "sample" / "matches_sample.json"


@pytest.fixture()
def repo_root() -> Path:
    return REPO_ROOT
