import json
import random
from pathlib import Path

import yaml

from finetuning.src.dataset_generation.loaders.civic_loader import CivicIndex

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = ROOT / "src" / "dataset_generation" / "templates"
DATASET_OUT = ROOT / "dataset" / "generated_pairs.preview.jsonl"


def render_template(text: str, placeholders: dict[str, str]) -> str:
    rendered = text
    for key, value in placeholders.items():
        rendered = rendered.replace(f"{{{{ {key} }}}}", value)
    return rendered


def load_yaml_template(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def try_load_paraphrase_templates(template_path: Path) -> list[str] | None:
    """If a sibling .paraphrases.yaml exists, load and return list of templates."""
    paraphrase_path = template_path.with_suffix("")
    paraphrase_path = paraphrase_path.with_name(paraphrase_path.name + ".paraphrases.yaml")
    if paraphrase_path.exists():
        with paraphrase_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        paras = data.get("paraphrases") or []
        print(f"[generate_dataset] Found paraphrase templates: {paraphrase_path} (count={len(paras)})")
        return paras
    print("[generate_dataset] No paraphrase templates found; using base only")
    return None


def main() -> None:
    print("[generate_dataset] Starting base generation (F1.1)")
    random.seed(42)

    # Load template
    template_path = TEMPLATES_DIR / "f1_1_targets_gene.yaml"
    print(f"[generate_dataset] Loading template: {template_path}")
    tpl = load_yaml_template(template_path)
    print(f"[generate_dataset] Template loaded: family_id={tpl['family_id']} template_id={tpl['template_id']}")
    paraphrase_templates = try_load_paraphrase_templates(template_path)

    # Build CIViC index
    print("[generate_dataset] Building CIViC index…")
    index = CivicIndex()
    index.build()
    gene_symbols = index.get_gene_symbols()
    print(f"[generate_dataset] Gene symbols available: {len(gene_symbols)}")

    # Curated-first sampling, then random from CIViC to reach 20 base examples
    curated = ["BRAF", "EGFR", "KRAS", "ALK", "PIK3CA"]
    curated = [g for g in curated if g in gene_symbols]
    print(f"[generate_dataset] Curated present in CIViC: {curated}")

    remaining_needed = max(0, 20 - len(curated))
    pool = [g for g in gene_symbols if g not in curated]
    random_sample = random.sample(pool, k=remaining_needed) if remaining_needed > 0 else []
    base_genes = curated + random_sample
    print(
        f"[generate_dataset] Sampling complete: curated={len(curated)} random={len(random_sample)} total={len(base_genes)}"
    )

    # Generate examples; expand with template-level paraphrases if available
    DATASET_OUT.parent.mkdir(parents=True, exist_ok=True)
    print(f"[generate_dataset] Writing output JSONL: {DATASET_OUT}")
    written = 0
    with DATASET_OUT.open("w", encoding="utf-8") as out_f:
        for i, gene in enumerate(base_genes, start=1):
            placeholders = {"gene_symbol": gene}
            q_text = render_template(tpl["question"], placeholders)
            cypher_text = render_template(tpl["cypher"], placeholders)
            record = {
                "id": f"F1.1-{i:06d}",
                "family_id": tpl["family_id"],
                "template_id": tpl["template_id"],
                "question": q_text,
                "cypher": cypher_text,
                "placeholders": placeholders,
                "source": "base",
                "paraphrase_of": None,
            }
            out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
            written += 1
            if written % 5 == 0:
                print(f"[generate_dataset] Wrote {written} records…")
            if paraphrase_templates:
                for j, qtpl in enumerate(paraphrase_templates, start=1):
                    q_text_p = render_template(qtpl, placeholders)
                    new_rec = {
                        **record,
                        "id": f"F1.1-{i:06d}-P{j}",
                        "question": q_text_p,
                        "source": "paraphrase",
                        "paraphrase_of": record["id"],
                    }
                    out_f.write(json.dumps(new_rec, ensure_ascii=False) + "\n")
                    written += 1
                    if written % 5 == 0:
                        print(f"[generate_dataset] Wrote {written} records…")
    print(f"[generate_dataset] Done. Total records written: {written}")


if __name__ == "__main__":
    main()
