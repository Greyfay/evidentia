"""Shared fixtures. The sample dossier is located via an environment variable so the
fictional organizer data never needs to live in version control."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def sample_dossier() -> Path:
    raw = os.environ.get("EVIDENTIA_SAMPLE_DOSSIER")
    if not raw or not Path(raw).exists():
        pytest.skip("set EVIDENTIA_SAMPLE_DOSSIER to the sample dossier directory to run")
    return Path(raw)
