"""Tracing and logging utilities shared across CLI and API.

Provides simple step-by-step console logs and JSONL trace persistence.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from .types import TraceSink


# --- Logging setup ---------------------------------------------------------

def init_logging(level: str | int | None = None) -> None:
    """Initialize basic logging once with a simple, readable format.

    If handlers already exist on the root logger, this is a no-op.
    """
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return

    env_level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    numeric_level = getattr(logging, env_level, logging.INFO)

    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


# --- Trace file helpers ----------------------------------------------------

def get_daily_trace_path() -> Path:
    """Return the JSONL trace file path for the current day, creating folders."""
    trace_dir = Path(os.getenv("TRACE_DIR", "logs/traces")).resolve()
    trace_dir.mkdir(parents=True, exist_ok=True)
    filename = datetime.now(UTC).strftime("%Y%m%d") + ".jsonl"
    return trace_dir / filename


# --- Trace sinks -----------------------------------------------------------

class JsonlTraceSink(TraceSink):
    """Append step-wise trace events to a JSONL file (one JSON object per line)."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def record(self, step: str, data: dict[str, object]) -> None:  # pragma: no cover - simple IO
        payload = {"timestamp": datetime.now(UTC).isoformat(), "step": step, **data}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
            f.write("\n")


class LoggingTraceSink(TraceSink):
    """Emit step-wise trace events to the standard logger at INFO level."""

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self._logger = logger or logging.getLogger("pipeline.trace")

    def record(self, step: str, data: dict[str, object]) -> None:
        try:
            payload = json.dumps(data, ensure_ascii=False)
        except Exception:
            # Fallback to repr if data is not JSON-serializable
            payload = repr(data)
        self._logger.info("%s: %s", step, payload)


class CompositeTrace(TraceSink):
    """Broadcast trace events to multiple sinks (e.g., console and JSONL)."""

    def __init__(self, *sinks: TraceSink) -> None:
        self._sinks = list(sinks)

    def record(self, step: str, data: dict[str, object]) -> None:
        for sink in self._sinks:
            try:
                sink.record(step, data)
            except Exception:
                # Never let tracing failures break the main flow
                continue


# --- Global trace for adapters (e.g., LLM) ---------------------------------

_global_trace: Optional[TraceSink] = None


def set_global_trace(sink: Optional[TraceSink]) -> None:
    """Set the process-global trace sink used by adapters that live outside the engine."""
    global _global_trace
    _global_trace = sink


def get_global_trace() -> Optional[TraceSink]:
    return _global_trace
