"""Lightweight helpers for pipeline tracing."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
import psycopg

from .types import TraceSink


class JsonlTraceSink:
    """Append trace events to a JSONL file."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def record(self, step: str, data: dict[str, object]) -> None:
        payload = {"timestamp": datetime.now(UTC).isoformat(), "step": step, **data}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
                handle.write("\n")
        except Exception:
            # Tracing should never crash the pipeline.
            pass


class StdoutTraceSink:
    """Print trace events to stdout."""

    def record(self, step: str, data: dict[str, object]) -> None:
        payload = {"timestamp": datetime.now(UTC).isoformat(), "step": step, **data}
        try:
            print(f"TRACE {step}: {json.dumps(payload, ensure_ascii=False)}")
        except Exception:
            pass


class CompositeTraceSink:
    """Forward trace events to two sinks."""

    def __init__(self, primary: TraceSink, secondary: TraceSink) -> None:
        self._primary = primary
        self._secondary = secondary

    def record(self, step: str, data: dict[str, object]) -> None:
        self._primary.record(step, data)
        self._secondary.record(step, data)


class ContextTraceSink:
    """Injects a fixed context payload into every trace event."""

    def __init__(self, sink: TraceSink, context: dict[str, object]) -> None:
        self._sink = sink
        # Shallow copy to avoid accidental external mutation
        self._context = dict(context)

    def record(self, step: str, data: dict[str, object]) -> None:
        merged = {**self._context, **data}
        self._sink.record(step, merged)


class PostgresTraceSink:
    """Persist trace events to a Postgres table as JSONB rows.

    Expects a table created via:
      create table if not exists traces (
        id bigserial primary key,
        timestamp timestamptz not null default now(),
        step text not null,
        payload jsonb not null,
        day date generated always as (timestamp::date) stored
      );
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def record(self, step: str, data: dict[str, object]) -> None:
        payload = {"timestamp": datetime.now(UTC).isoformat(), "step": step, **data}
        run_id = data.get("run_id")
        try:
            with psycopg.connect(self._dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    if isinstance(run_id, str) and run_id:
                        try:
                            cur.execute(
                                "insert into traces (run_id, timestamp, step, payload) values (%s, now(), %s, %s::jsonb)",
                                (run_id, step, json.dumps(payload, ensure_ascii=False)),
                            )
                            return
                        except Exception:
                            # Fall back if run_id column doesn't exist yet
                            pass
                    cur.execute(
                        "insert into traces (timestamp, step, payload) values (now(), %s, %s::jsonb)",
                        (step, json.dumps(payload, ensure_ascii=False)),
                    )
        except Exception:
            # Tracing failures must be non-fatal.
            pass


def daily_trace_path(base: Path | None = None) -> Path:
    directory = (base or Path("logs") / "traces").resolve()
    filename = datetime.now(UTC).strftime("%Y%m%d.jsonl")
    return directory / filename
