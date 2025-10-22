"""Tests for the gene sets API endpoint."""

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_get_gene_set_colorectal():
    """Test fetching colorectal therapy genes."""
    response = client.post("/graph-gene-sets", json={"preset_id": "colorectal_therapy_genes"})

    assert response.status_code == 200
    data = response.json()

    assert "genes" in data
    assert "description" in data
    assert isinstance(data["genes"], list)
    assert len(data["genes"]) > 0
    assert data["description"] == "Genes targeted by therapies for Colorectal Cancer"

    # Check that genes are strings
    for gene in data["genes"]:
        assert isinstance(gene, str)
        assert len(gene) > 0


def test_get_gene_set_lung():
    """Test fetching lung therapy genes."""
    response = client.post("/graph-gene-sets", json={"preset_id": "lung_therapy_genes"})

    assert response.status_code == 200
    data = response.json()

    assert "genes" in data
    assert "description" in data
    assert isinstance(data["genes"], list)
    assert data["description"] == "Genes targeted by therapies for Lung Cancer"


def test_get_gene_set_resistance():
    """Test fetching resistance biomarker genes."""
    response = client.post("/graph-gene-sets", json={"preset_id": "resistance_biomarker_genes"})

    assert response.status_code == 200
    data = response.json()

    assert "genes" in data
    assert "description" in data
    assert isinstance(data["genes"], list)
    assert data["description"] == "All genes with known resistance biomarkers"


def test_get_gene_set_egfr():
    """Test fetching EGFR pathway genes."""
    response = client.post("/graph-gene-sets", json={"preset_id": "egfr_pathway_genes"})

    assert response.status_code == 200
    data = response.json()

    assert "genes" in data
    assert "description" in data
    assert isinstance(data["genes"], list)
    assert data["description"] == "Genes targeted by EGFR pathway therapies"


def test_get_gene_set_top_biomarkers():
    """Test fetching top biomarker genes."""
    response = client.post("/graph-gene-sets", json={"preset_id": "top_biomarker_genes"})

    assert response.status_code == 200
    data = response.json()

    assert "genes" in data
    assert "description" in data
    assert isinstance(data["genes"], list)
    assert data["description"] == "Top biomarker genes across all cancers"


def test_get_gene_set_invalid_preset():
    """Test error handling for invalid preset ID."""
    response = client.post("/graph-gene-sets", json={"preset_id": "invalid_preset"})

    assert response.status_code == 400
    data = response.json()

    assert "detail" in data
    assert "Unknown preset_id" in data["detail"]
    assert "invalid_preset" in data["detail"]


def test_get_gene_set_missing_preset_id():
    """Test error handling for missing preset_id."""
    response = client.post("/graph-gene-sets", json={})

    assert response.status_code == 422  # Validation error


def test_get_gene_set_empty_preset_id():
    """Test error handling for empty preset_id."""
    response = client.post("/graph-gene-sets", json={"preset_id": ""})

    assert response.status_code == 400  # Business logic error for empty preset
