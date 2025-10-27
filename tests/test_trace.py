from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from pipeline.trace import JsonlTraceSink, daily_trace_path


def test_daily_trace_path_uses_current_date(tmp_path: Path, monkeypatch) -> None:
    fake_now = datetime(2025, 10, 17)
    monkeypatch.setattr("pipeline.trace.datetime", type("_DT", (), {"now": staticmethod(lambda tz=None: fake_now)}))

    path = daily_trace_path(tmp_path)

    assert path.parent == tmp_path.resolve()
    assert path.name == "20251017.jsonl"


def test_jsonl_trace_sink_writes_line(tmp_path: Path) -> None:
    trace_file = tmp_path / "trace.jsonl"
    sink = JsonlTraceSink(trace_file)

    sink.record("step", {"foo": "bar"})

    assert trace_file.exists()
    contents = trace_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(contents) == 1
    payload = json.loads(contents[0])
    assert payload["step"] == "step"
    assert payload["foo"] == "bar"
