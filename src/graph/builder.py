import os
from collections.abc import Callable, Iterable
from math import ceil
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

# Allow overriding the CSV root directory via environment variable for generated datasets
DATA_DIR = os.getenv("DATA_DIR", "data/manual")
# Batch size for UNWIND-based bulk writes. Tune between ~100-5000 depending on memory & DB.
BATCH_SIZE = int(os.getenv("NEO4J_BATCH_SIZE", "500"))

ALLOWED_BIOMARKER_TYPES = {"Gene", "Variant"}


def chunked(records: list[dict], size: int) -> Iterable[list[dict]]:
    """Yield successive chunks from records with length `size` (last chunk may be smaller)."""
    for i in range(0, len(records), size):
        yield records[i : i + size]


class OncoGraphBuilder:
    def __init__(self):
        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "password")
        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self._driver.close()

    def run_ingestion(self):
        """Orchestrates the entire ingestion process."""
        print("Step 0: Clearing existing graph...")
        self.clear_graph()

        print("Step 1: Creating constraints...")
        self.create_constraints()

        print("\nStep 2: Ingesting nodes...")
        # Note: switched to batch versions for performance (UNWIND)
        self.ingest_csv_data(os.path.join(DATA_DIR, "nodes/genes.csv"), self._create_genes_batch)
        self.ingest_csv_data(os.path.join(DATA_DIR, "nodes/variants.csv"), self._create_variants_batch)
        self.ingest_csv_data(os.path.join(DATA_DIR, "nodes/therapies.csv"), self._create_therapies_batch)
        self.ingest_csv_data(os.path.join(DATA_DIR, "nodes/diseases.csv"), self._create_diseases_batch)

        print("\nStep 3: Ingesting relationships...")
        self.ingest_csv_data(os.path.join(DATA_DIR, "relationships/variant_of.csv"), self._create_variant_of_batch)
        self.ingest_csv_data(os.path.join(DATA_DIR, "relationships/targets.csv"), self._create_targets_batch)
        # affects_response requires special handling because biomarker_type controls the node label/property
        self.ingest_csv_data(
            os.path.join(DATA_DIR, "relationships/affects_response.csv"),
            self._create_affects_response_batch,
        )

    def create_constraints(self):
        with self._driver.session() as session:
            queries = [
                "CREATE CONSTRAINT IF NOT EXISTS FOR (g:Gene) REQUIRE g.symbol IS UNIQUE",
                "CREATE CONSTRAINT IF NOT EXISTS FOR (v:Variant) REQUIRE v.name IS UNIQUE",
                "CREATE CONSTRAINT IF NOT EXISTS FOR (t:Therapy) REQUIRE t.name IS UNIQUE",
                "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Disease) REQUIRE d.name IS UNIQUE",
            ]
            for query in queries:
                session.run(query)

    def clear_graph(self):
        with self._driver.session() as session:
            session.execute_write(self._clear_graph_batch)

    @staticmethod
    def _clear_graph_batch(tx):
        tx.run("MATCH (n) DETACH DELETE n")

    def ingest_csv_data(self, file_path: str, creation_func: Callable):
        """
        Read CSV, clean rows, and send to DB in batches using the provided creation_func.

        creation_func is expected to be a function of the form (tx, rows: List[dict]) -> None.
        """
        print(f"  -> Processing {file_path}")
        df = pd.read_csv(file_path)
        records = [self._clean_row(r) for r in df.to_dict(orient="records")]
        total = len(records)
        if total == 0:
            print("    (no rows)")
            return

        # Detect whether we're handling affects_response (bound method identity via __func__)
        is_affects_response = (
            getattr(creation_func, "__func__", creation_func) is self._create_affects_response_batch.__func__
        )

        # For affects_response we need to validate biomarker_type values ahead of time
        if is_affects_response:
            invalid_rows = [
                r
                for r in records
                if (r.get("biomarker_type") not in ALLOWED_BIOMARKER_TYPES and r.get("biomarker_type") is not None)
            ]
            if invalid_rows:
                # preserve original behavior: raise ValueError if an unsupported biomarker_type is encountered
                # include a helpful message and stop ingestion for this file.
                bad = invalid_rows[0].get("biomarker_type")
                raise ValueError(f"Unsupported biomarker_type '{bad}' in affects_response.csv")

        with self._driver.session() as session:
            num_batches = ceil(total / BATCH_SIZE)
            for idx, batch in enumerate(chunked(records, BATCH_SIZE), start=1):
                print(f"    sending batch {idx}/{num_batches} (size={len(batch)})")
                # Special-case affects_response: split by biomarker_type so Cypher can use concrete labels
                if is_affects_response:
                    gene_rows = [r for r in batch if r.get("biomarker_type") == "Gene"]
                    variant_rows = [r for r in batch if r.get("biomarker_type") == "Variant"]
                    if gene_rows:
                        session.execute_write(self._create_affects_response_batch_gene, gene_rows)
                    if variant_rows:
                        session.execute_write(self._create_affects_response_batch_variant, variant_rows)
                else:
                    session.execute_write(creation_func, batch)

    @staticmethod
    def _clean_row(row: dict[str, Any]) -> dict[str, Any]:
        cleaned: dict[str, Any] = {}

        for key, value in row.items():
            if isinstance(value, str):
                value = value.strip()
                if value == "":
                    value = None
            elif pd.isna(value):
                value = None
            cleaned[key] = value

        def split_semicolon_list(raw: Any) -> list[str]:
            if raw is None:
                return []
            return [item.strip() for item in str(raw).split(";") if item.strip()]

        for key in ("synonyms", "tags", "pmids", "ref_sources", "ref_ids", "ref_urls"):
            if key in row:
                cleaned[key] = split_semicolon_list(row.get(key))

        for optional_key in ("disease_id",):
            cleaned.setdefault(optional_key, None)

        # Convert evidence_rating to integer if present and numeric
        if "evidence_rating" in cleaned and cleaned["evidence_rating"] is not None:
            try:
                cleaned["evidence_rating"] = int(cleaned["evidence_rating"])
            except (ValueError, TypeError):
                # If conversion fails, set to None
                cleaned["evidence_rating"] = None

        return cleaned

    # --- Batch Node Creation Methods (UNWIND rows) ---
    @staticmethod
    def _create_genes_batch(tx, rows: list[dict[str, Any]]):
        tx.run(
            """
            UNWIND $rows AS r
            MERGE (g:Gene {symbol: r.symbol})
            SET g.hgnc_id = r.hgnc_id,
                g.synonyms = r.synonyms
            """,
            {"rows": rows},
        )

    @staticmethod
    def _create_variants_batch(tx, rows: list[dict[str, Any]]):
        tx.run(
            """
            UNWIND $rows AS r
            MERGE (v:Variant {name: r.name})
            SET v.hgvs_p = r.hgvs_p,
                v.consequence = r.consequence,
                v.synonyms = r.synonyms
            """,
            {"rows": rows},
        )

    @staticmethod
    def _create_therapies_batch(tx, rows: list[dict[str, Any]]):
        tx.run(
            """
            UNWIND $rows AS r
            MERGE (t:Therapy {name: r.name})
            SET t.modality = r.modality,
                t.tags = r.tags,
                t.chembl_id = r.chembl_id,
                t.synonyms = r.synonyms
            """,
            {"rows": rows},
        )

    @staticmethod
    def _create_diseases_batch(tx, rows: list[dict[str, Any]]):
        tx.run(
            """
            UNWIND $rows AS r
            MERGE (d:Disease {name: r.name})
            SET d.doid = r.doid,
                d.synonyms = r.synonyms
            """,
            {"rows": rows},
        )

    # --- Batch Relationship Creation Methods ---
    @staticmethod
    def _create_variant_of_batch(tx, rows: list[dict[str, Any]]):
        tx.run(
            """
            UNWIND $rows AS r
            MATCH (v:Variant {name: r.variant_name})
            MATCH (g:Gene {symbol: r.gene_symbol})
            MERGE (v)-[:VARIANT_OF]->(g)
            """,
            {"rows": rows},
        )

    @staticmethod
    def _create_targets_batch(tx, rows: list[dict[str, Any]]):
        tx.run(
            """
            UNWIND $rows AS r
            MATCH (t:Therapy {name: r.therapy_name})
            MATCH (g:Gene {symbol: r.gene_symbol})
            MERGE (t)-[rel:TARGETS]->(g)
            SET rel.source = r.source,
                rel.moa = coalesce(r.moa, rel.moa),
                rel.action_type = coalesce(r.action_type, rel.action_type),
                rel.ref_sources = coalesce(r.ref_sources, rel.ref_sources),
                rel.ref_ids = coalesce(r.ref_ids, rel.ref_ids),
                rel.ref_urls = coalesce(r.ref_urls, rel.ref_urls)
            """,
            {"rows": rows},
        )

    def _create_affects_response_batch(self, tx, rows: list[dict[str, Any]]):
        """
        This method is not used directly by ingest_csv_data because we split rows by biomarker_type
        and call the specialized gene/variant batch methods. Keep as a placeholder in case it's used.
        """
        # For safety, do nothing: ingest_csv_data handles the splitting and calls the more specific tx methods.
        pass

    @staticmethod
    def _create_affects_response_batch_gene(tx, rows: list[dict[str, Any]]):
        """
        Handle rows where biomarker_type == 'Gene'.
        """
        tx.run(
            """
            UNWIND $rows AS r
            MATCH (b:Gene {symbol: r.biomarker_name})
            MATCH (t:Therapy {name: r.therapy_name})
            SET b:Biomarker
            MERGE (b)-[rlt:AFFECTS_RESPONSE_TO {
                effect: r.effect,
                disease_name: r.disease_name,
                disease_id: coalesce(r.disease_id, ''),
                source: r.source
            }]->(t)
            WITH rlt, r
            WITH rlt, coalesce(rlt.pmids, []) + coalesce(r.pmids, []) AS pmids_all, r
            UNWIND pmids_all AS p
            WITH rlt, r, collect(DISTINCT p) AS pmids_uniq
            SET rlt.pmids = pmids_uniq,
                rlt.notes = r.notes,
                rlt.evidence_level = coalesce(r.evidence_level, rlt.evidence_level),
                rlt.evidence_rating = coalesce(r.evidence_rating, rlt.evidence_rating)
            """,
            {"rows": rows},
        )

    @staticmethod
    def _create_affects_response_batch_variant(tx, rows: list[dict[str, Any]]):
        """
        Handle rows where biomarker_type == 'Variant'.
        """
        tx.run(
            """
            UNWIND $rows AS r
            MATCH (b:Variant {name: r.biomarker_name})
            MATCH (t:Therapy {name: r.therapy_name})
            SET b:Biomarker
            MERGE (b)-[rlt:AFFECTS_RESPONSE_TO {
                effect: r.effect,
                disease_name: r.disease_name,
                disease_id: coalesce(r.disease_id, ''),
                source: r.source
            }]->(t)
            WITH rlt, r
            WITH rlt, coalesce(rlt.pmids, []) + coalesce(r.pmids, []) AS pmids_all, r
            UNWIND pmids_all AS p
            WITH rlt, r, collect(DISTINCT p) AS pmids_uniq
            SET rlt.pmids = pmids_uniq,
                rlt.notes = r.notes,
                rlt.evidence_level = coalesce(r.evidence_level, rlt.evidence_level),
                rlt.evidence_rating = coalesce(r.evidence_rating, rlt.evidence_rating)
            """,
            {"rows": rows},
        )


if __name__ == "__main__":
    builder = OncoGraphBuilder()
    try:
        builder.run_ingestion()
        print("\nDone.")
    finally:
        builder.close()
