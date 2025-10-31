import json
import os
import random
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from neo4j import GraphDatabase


ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = ROOT / "dataset"


def load_sample_records(files: list[Path], per_file: int = 2) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for p in files:
        if not p.exists():
            continue
        taken = 0
        with p.open(encoding="utf-8") as f:
            for line in f:
                if taken >= per_file:
                    break
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Expect fields: question, cypher
                if "question" in rec and "cypher" in rec:
                    samples.append(rec)
                    taken += 1
    return samples


def run_queries(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    load_dotenv()
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "neo4j")

    # Basic driver; read-only queries
    driver = GraphDatabase.driver(uri, auth=(user, password))
    results: list[dict[str, Any]] = []
    try:
        with driver.session() as session:
            for rec in records:
                cypher = rec.get("cypher", "")
                question = rec.get("question", "")
                out: dict[str, Any] = {
                    "id": rec.get("id"),
                    "family_id": rec.get("family_id"),
                    "template_id": rec.get("template_id"),
                    "question": question,
                    "cypher": cypher,
                }
                try:
                    rows = session.run(cypher).data()
                    # Normalize arrays that may come back as semicolon strings
                    out["result"] = rows
                    out["error"] = None
                except Exception as exc:  # pragma: no cover
                    out["result"] = []
                    out["error"] = f"{type(exc).__name__}: {exc}"
                results.append(out)
    finally:
        driver.close()
    return results


def main() -> None:
    # Cover all generated family/template files
    files = sorted(DATASET_DIR.glob("generated_pairs.*.jsonl"))
    if not files:
        print(f"[execute] No generated files found under {DATASET_DIR}")
        return

    per_file_env = os.environ.get("EXEC_SAMPLES_PER_FILE")
    try:
        per_file = int(per_file_env) if per_file_env else 2
    except Exception:
        per_file = 2

    random.seed(42)
    records = load_sample_records(files, per_file=per_file)
    print(f"[execute] Loaded {len(records)} records from {len(files)} files (per_file={per_file})")

    results = run_queries(records)
    out_path = DATASET_DIR / "executed_results.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for row in results:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"[execute] Wrote {len(results)} results → {out_path}")


if __name__ == "__main__":
    main()
