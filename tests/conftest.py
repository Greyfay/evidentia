"""Shared fixtures. The sample dossier is located via an environment variable so the
fictional organizer data never needs to live in version control."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _offline_partners(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the suite offline and deterministic: no live OpenAI/Cognee calls in tests.

    The API and CLI load a real ``.env`` at import time; without this the planner would run
    live OpenAI/Cognee per request, making tests slow and non-deterministic. Live smoke tests
    that genuinely want the cloud re-set their own key within their own scope.
    """

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("COGNEE_API_KEY", raising=False)


@pytest.fixture(scope="session")
def sample_dossier() -> Path:
    raw = os.environ.get("EVIDENTIA_SAMPLE_DOSSIER")
    if not raw or not Path(raw).exists():
        pytest.skip("set EVIDENTIA_SAMPLE_DOSSIER to the sample dossier directory to run")
    return Path(raw)
