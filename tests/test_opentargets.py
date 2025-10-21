from unittest.mock import patch

from pipeline.opentargets import (
    _post_graphql,
    build_targets_and_enrichments,
)


def test_build_targets_and_enrichments_basic():
    # Mock search -> map therapy names to CHEMBL IDs
    def fake_post_graphql(query, variables=None, url=None):  # type: ignore[override]
        if "search(" in query:
            q = variables["q"]
            if q.lower() == "sotorasib":
                return {
                    "search": {
                        "hits": [
                            {
                                "id": "CHEMBL4535757",
                                "name": "SOTORASIB",
                                "object": {
                                    "id": "CHEMBL4535757",
                                    "name": "SOTORASIB",
                                    "drugType": "Small molecule",
                                    "synonyms": ["AMG-510", "Sotorasib"],
                                    "tradeNames": ["Lumakras"],
                                },
                            }
                        ]
                    }
                }
            return {"search": {"hits": []}}
        # drugs query
        return {
            "drugs": [
                {
                    "id": "CHEMBL4535757",
                    "name": "SOTORASIB",
                    "drugType": "Small molecule",
                    "linkedTargets": {"rows": [{"approvedSymbol": "KRAS"}]},
                    "mechanismsOfAction": {
                        "rows": [
                            {
                                "mechanismOfAction": "GTPase KRas inhibitor",
                                "actionType": "INHIBITOR",
                                "targets": [{"approvedSymbol": "KRAS"}],
                                "references": {
                                    "source": "PubMed",
                                    "ids": ["31189530"],
                                    "urls": ["http://europepmc.org/abstract/MED/31189530"],
                                },
                            }
                        ]
                    },
                }
            ]
        }

    with patch("src.pipeline.opentargets._post_graphql", side_effect=fake_post_graphql):
        therapy_rows = {
            "Sotorasib": {
                "name": "Sotorasib",
                "modality": None,
                "tags": set(),
                "chembl_id": None,
                "synonyms": None,
            }
        }
        targets_rows, extra_genes, enrich = build_targets_and_enrichments(therapy_rows)

        assert any(r["gene_symbol"] == "KRAS" for r in targets_rows)
        assert enrich["Sotorasib"]["chembl_id"] == "CHEMBL4535757"
        assert "Lumakras" in enrich["Sotorasib"]["synonyms"]
        assert "KRAS" in extra_genes
