"""Convenience launcher for the pipeline CLI.

Usage:
  python run.py "Your question here"
"""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    # Ensure 'src' is on sys.path so 'pipeline' can be imported.
    project_root = Path(__file__).resolve().parent
    src_dir = project_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    from pipeline.cli import main as cli_main  # noqa: WPS433 (intentional local import)

    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
