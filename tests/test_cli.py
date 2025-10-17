"""Smoke test for the CLI wiring with a stubbed engine build."""

from __future__ import annotations

from pathlib import Path

from pipeline import QueryEngine


def test_cli_runs_with_stubbed_engine(monkeypatch, tmp_path: Path, capsys):
    from pipeline import cli as cli_mod

    class StubEngine(QueryEngine):  # type: ignore[misc]
        def __init__(self):
            pass

        def run(self, question: str):
            return type(
                "_Result",
                (),
                {
                    "answer": "stub answer",
                    "cypher": "MATCH (n) RETURN n LIMIT 1",
                    "rows": [{"x": 1}],
                },
            )()

    def stub_build_engine():
        return StubEngine()  # type: ignore[return-value]

    monkeypatch.setattr(cli_mod, "_build_engine", stub_build_engine)
    monkeypatch.setenv("PYTHONHASHSEED", "0")

    rc = cli_mod.main(["What is KRAS?", "--no-log"])
    assert rc == 0

    captured = capsys.readouterr().out
    assert "Cypher:" in captured
    assert "Rows:" in captured
    assert "stub answer" in captured
