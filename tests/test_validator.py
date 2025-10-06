"""Unit tests for the rule-based Cypher validator."""

from __future__ import annotations

import pytest

from pipeline import PipelineConfig
from pipeline.types import PipelineError
from pipeline.validator import RuleBasedValidator


def make_validator(config: PipelineConfig | None = None) -> RuleBasedValidator:
    return RuleBasedValidator(config=config or PipelineConfig())


def test_validator_adds_default_limit_when_missing():
    validator = make_validator()
    cypher = "MATCH (g:Gene) RETURN g"

    validated = validator.validate_cypher(cypher)

    assert validated.endswith("LIMIT 100")


def test_validator_rejects_write_clauses():
    validator = make_validator()

    with pytest.raises(PipelineError):
        validator.validate_cypher("MATCH (g:Gene) DELETE g")


def test_validator_caps_limit_to_config_max():
    config = PipelineConfig(max_limit=150)
    validator = make_validator(config=config)

    validated = validator.validate_cypher("MATCH (g:Gene) RETURN g LIMIT 999")

    assert validated.endswith(f"LIMIT {config.max_limit}")


def test_validator_rejects_unknown_label():
    validator = make_validator()

    with pytest.raises(PipelineError):
        validator.validate_cypher("MATCH (x:UnknownLabel) RETURN x LIMIT 5")
