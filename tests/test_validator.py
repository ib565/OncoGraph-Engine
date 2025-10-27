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


def test_validator_rejects_forbidden_keyword_case_insensitive():
    validator = make_validator()

    with pytest.raises(PipelineError):
        validator.validate_cypher("match (g:Gene) call db.labels() return g")


def test_validator_caps_limit_to_config_max():
    config = PipelineConfig(max_limit=150)
    validator = make_validator(config=config)

    validated = validator.validate_cypher("MATCH (g:Gene) RETURN g LIMIT 999")

    assert validated.endswith(f"LIMIT {config.max_limit}")


def test_validator_rejects_unknown_label():
    validator = make_validator()

    with pytest.raises(PipelineError):
        validator.validate_cypher("MATCH (x:UnknownLabel) RETURN x LIMIT 5")


def test_validator_rejects_unknown_relationship():
    validator = make_validator()

    with pytest.raises(PipelineError):
        validator.validate_cypher("MATCH ()-[r:UNKNOWN_REL]->() RETURN r LIMIT 5")


def test_validator_does_not_misread_relationship_as_label():
    validator = make_validator()
    # Valid relationship should not be flagged as a label
    validated = validator.validate_cypher("MATCH (a:Gene)-[:AFFECTS_RESPONSE_TO]->(t:Therapy) RETURN a, t LIMIT 5")
    assert validated.endswith(f"LIMIT {PipelineConfig().default_limit}") or "LIMIT" in validated


def test_validator_handles_backticked_relationship_type():
    validator = make_validator()
    # Backticks around relationship type should be allowed and recognized
    validated = validator.validate_cypher("MATCH (a:Gene)-[r:`AFFECTS_RESPONSE_TO`]->(t:Therapy) RETURN r LIMIT 5")
    assert "RETURN r" in validated


def test_validator_requires_return_clause():
    validator = make_validator()

    with pytest.raises(PipelineError):
        validator.validate_cypher("MATCH (g:Gene)")


def test_validator_rewrites_disease_name_equality_to_case_insensitive():
    validator = make_validator()
    cypher = (
        "MATCH (b:Biomarker)-[r:AFFECTS_RESPONSE_TO]->(t:Therapy) WHERE r.disease_name = 'colorectal cancer' RETURN r"
    )
    validated = validator.validate_cypher(cypher)
    assert "toLower(r.disease_name) = toLower('colorectal cancer')" in validated
