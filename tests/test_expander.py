"""Unit tests for the SimpleExpander."""

from __future__ import annotations

import pytest

from pipeline import PipelineConfig
from pipeline.expander import SimpleExpander
from pipeline.types import PipelineError


def test_expander_rejects_empty_question():
    expander = SimpleExpander()
    with pytest.raises(PipelineError):
        expander.expand_instructions("")


def test_expander_returns_plain_text_with_question():
    expander = SimpleExpander()
    out = expander.expand_instructions("Find KRAS evidence")

    # Basic shape
    assert "Gene" in out and "Variant" in out and "Therapy" in out and "Disease" in out
    assert "User question:" in out
    assert "Find KRAS evidence" in out
