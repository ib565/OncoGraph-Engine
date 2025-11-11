"""Pytest configuration for making the src package importable."""

import sys
from pathlib import Path

import pytest

from pipeline.utils import TTLCache

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"

if SRC_DIR.exists():
    sys.path.insert(0, str(SRC_DIR))


@pytest.fixture(autouse=True)
def disable_db_side_effects(monkeypatch):
    # Never talk to Postgres in tests
    for var in ("CACHE_DATABASE_URL", "TRACE_DATABASE_URL", "DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)
    # Also silence stdout tracing
    monkeypatch.setenv("TRACE_STDOUT", "0")


@pytest.fixture(autouse=True)
def isolate_llm_cache(monkeypatch):
    # Force a fresh in-memory LLM cache per test
    cache = TTLCache()
    monkeypatch.setattr("pipeline.utils.get_llm_cache", lambda: cache)
    try:
        yield
    finally:
        cache.clear()


@pytest.fixture(autouse=True)
def isolate_trace_logs(tmp_path, monkeypatch):
    """Redirect trace logs to a temporary directory during tests to avoid polluting production logs."""
    test_log_dir = tmp_path / "test_logs"
    test_log_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TRACE_LOG_DIR", str(test_log_dir))


@pytest.fixture(autouse=True)
def isolate_enrichment_cache(monkeypatch):
    """Ensure enrichment cache is fresh and in-memory for each test."""
    cache = TTLCache()
    monkeypatch.setattr("pipeline.enrichment.get_enrichment_cache", lambda: cache)
    yield
    cache.clear()
