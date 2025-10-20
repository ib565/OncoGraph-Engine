import os
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

# Allow overriding the CSV root directory via environment variable for generated datasets
DATA_DIR = os.getenv("DATA_DIR", "data/manual")

ALLOWED_BIOMARKER_TYPES = {"Gene", "Variant"}


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
        print("Step 1: Creating constraints...")
        self.create_constraints()

        print("\nStep 2: Ingesting nodes...")
        self.ingest_csv_data(os.path.join(DATA_DIR, "nodes/genes.csv"), self._create_gene_node)
        self.ingest_csv_data(
            os.path.join(DATA_DIR, "nodes/variants.csv"), self._create_variant_node
        )
        self.ingest_csv_data(
            os.path.join(DATA_DIR, "nodes/therapies.csv"), self._create_therapy_node
        )
        self.ingest_csv_data(
            os.path.join(DATA_DIR, "nodes/diseases.csv"), self._create_disease_node
        )

        print("\nStep 3: Ingesting relationships...")
        self.ingest_csv_data(
            os.path.join(DATA_DIR, "relationships/variant_of.csv"), self._create_variant_of_rel
        )
        self.ingest_csv_data(
            os.path.join(DATA_DIR, "relationships/targets.csv"), self._create_targets_rel
        )
        self.ingest_csv_data(
            os.path.join(DATA_DIR, "relationships/affects_response.csv"),
            self._create_affects_response_rel,
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

    def ingest_csv_data(self, file_path, creation_func):
        print(f"  -> Processing {file_path}")
        df = pd.read_csv(file_path)
        with self._driver.session() as session:
            for _, row in df.iterrows():
                cleaned_row = self._clean_row(row.to_dict())
                session.execute_write(creation_func, cleaned_row)

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

        for key in ("synonyms", "tags", "pmids"):
            if key in row:
                cleaned[key] = split_semicolon_list(row.get(key))

        for optional_key in ("disease_id",):
            cleaned.setdefault(optional_key, None)

        return cleaned

    # --- Node Creation Methods ---
    @staticmethod
    def _create_gene_node(tx, row):
        tx.run(
            "MERGE (g:Gene {symbol: $symbol}) SET g.hgnc_id = $hgnc_id, g.synonyms = $synonyms",
            row,
        )

    @staticmethod
    def _create_variant_node(tx, row):
        tx.run(
            """
            MERGE (v:Variant {name: $name})
            SET v.hgvs_p = $hgvs_p, 
                v.consequence = $consequence, 
                v.synonyms = $synonyms
            """,
            row,
        )

    @staticmethod
    def _create_therapy_node(tx, row):
        tx.run(
            """
            MERGE (t:Therapy {name: $name})
            SET t.modality = $modality, 
                t.tags = $tags, 
                t.chembl_id = $chembl_id, 
                t.synonyms = $synonyms
            """,
            row,
        )

    @staticmethod
    def _create_disease_node(tx, row):
        tx.run(
            "MERGE (d:Disease {name: $name}) SET d.doid = $doid, d.synonyms = $synonyms",
            row,
        )

    # --- Relationship Creation Methods ---
    @staticmethod
    def _create_variant_of_rel(tx, row):
        tx.run(
            """
            MATCH (v:Variant {name: $variant_name})
            MATCH (g:Gene {symbol: $gene_symbol})
            MERGE (v)-[:VARIANT_OF]->(g)
            """,
            row,
        )

    @staticmethod
    def _create_targets_rel(tx, row):
        tx.run(
            (
                "MATCH (t:Therapy {name: $therapy_name}) "
                "MATCH (g:Gene {symbol: $gene_symbol}) "
                "MERGE (t)-[r:TARGETS]->(g) "
                "SET r.source = $source"
            ),
            row,
        )

    @staticmethod
    def _create_affects_response_rel(tx, row):
        # Determine the property to match the biomarker on ('symbol' for Gene, 'name' for Variant)
        biomarker_type = row.get("biomarker_type")
        if biomarker_type not in ALLOWED_BIOMARKER_TYPES:
            raise ValueError(
                f"Unsupported biomarker_type '{biomarker_type}' in affects_response.csv"
            )

        biomarker_prop = "symbol" if biomarker_type == "Gene" else "name"

        query = f"""
        MATCH (b:{biomarker_type} {{{biomarker_prop}: $biomarker_name}})
        MATCH (t:Therapy {{name: $therapy_name}})
        SET b:Biomarker
        MERGE (b)-[r:AFFECTS_RESPONSE_TO]->(t)
        SET r.effect = $effect,
            r.disease_name = $disease_name,
            r.disease_id = $disease_id,
            r.pmids = $pmids,
            r.source = $source,
            r.notes = $notes
        """
        tx.run(query, row)


if __name__ == "__main__":

    builder = OncoGraphBuilder()
    builder.run_ingestion()
    print("\nDone.")
    builder.close()
