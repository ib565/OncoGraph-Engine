import json
import random
import sys
from pathlib import Path

import yaml
from oncograph_finetuning.dataset_generation.loaders.civic_loader import CivicIndex

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = ROOT / "oncograph_finetuning" / "dataset_generation" / "templates"
DATASET_DIR = ROOT / "dataset"


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


def sample_entities(placeholder_key: str, available: list[str], curated: list[str], count: int = 20) -> list[str]:
    """Sample entities with curated-first strategy."""
    curated_present = [e for e in curated if e in available]
    print(f"[generate_dataset] Curated {placeholder_key} present in CIViC: {curated_present}")
    remaining_needed = max(0, count - len(curated_present))
    pool = [e for e in available if e not in curated_present]
    random_sample = random.sample(pool, k=remaining_needed) if remaining_needed > 0 else []
    result = curated_present + random_sample
    print(
        f"[generate_dataset] Sampling complete for {placeholder_key}: curated={len(curated_present)} random={len(random_sample)} total={len(result)}"
    )
    return result


def _list_all_templates() -> list[Path]:
    # All *.yaml except *.paraphrases.yaml
    paths = sorted(p for p in TEMPLATES_DIR.glob("*.yaml") if not str(p.name).endswith(".paraphrases.yaml"))
    return paths


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python generate_dataset.py <template_filename.yaml | --all>", file=sys.stderr)
        raise SystemExit(1)

    arg = sys.argv[1]
    multi = arg in {"--all", "ALL", "all"}
    if multi:
        template_paths = _list_all_templates()
        print(f"[generate_dataset] Running for ALL templates: {len(template_paths)} found")
    else:
        template_path = TEMPLATES_DIR / arg
        if not template_path.exists():
            raise FileNotFoundError(f"Template not found: {template_path}")
        template_paths = [template_path]

    random.seed(42)

    # Build CIViC index
    print("[generate_dataset] Building CIViC index…")
    index = CivicIndex()
    # Filter therapies by chembl_id and diseases by doid to prefer widely-used entities
    index.build(require_chembl_id=True, require_doid=True)
    DATASET_DIR.mkdir(parents=True, exist_ok=True)

    for template_path in template_paths:
        print(f"[generate_dataset] Loading template: {template_path}")
        tpl = load_yaml_template(template_path)
        print(f"[generate_dataset] Template loaded: family_id={tpl['family_id']} template_id={tpl['template_id']}")
        paraphrase_templates = try_load_paraphrase_templates(template_path)

        # Determine placeholders and sample entities
        placeholder_config = tpl.get("placeholders", {})
        placeholders_list: list[tuple[str, list[str]]] = []

        # Curated lists per entity type
        curated_genes = ["BRAF", "EGFR", "KRAS", "ALK", "PIK3CA"]
        curated_therapies = ["Dabrafenib", "Osimertinib", "Cetuximab", "Trastuzumab", "Imatinib"]
        curated_variants = ["BRAF V600E", "KRAS G12C", "EGFR Exon19del", "EGFR T790M", "BCR BCR::ABL1 Fusion"]
        curated_diseases = ["Colorectal Cancer", "Lung Cancer", "Skin Melanoma", "Breast Cancer"]

        if "gene_symbol" in placeholder_config:
            genes = index.get_gene_symbols()
            sampled = sample_entities("gene_symbol", genes, curated_genes)
            placeholders_list.append(("gene_symbol", sampled))
        if "therapy_name" in placeholder_config:
            therapies = index.get_therapy_names()
            sampled = sample_entities("therapy_name", therapies, curated_therapies)
            placeholders_list.append(("therapy_name", sampled))
        if "variant_name" in placeholder_config:
            variants = index.get_variant_names()
            sampled = sample_entities("variant_name", variants, curated_variants)
            placeholders_list.append(("variant_name", sampled))
        if "disease_name" in placeholder_config:
            diseases = index.get_disease_names()
            sampled = sample_entities("disease_name", diseases, curated_diseases)
            placeholders_list.append(("disease_name", sampled))

        # Generate values (now supports multiple placeholders)
        if len(placeholders_list) == 0:
            print("[generate_dataset] Skipping: no placeholders in template")
            continue
        # If template declares placeholders we do not support, skip to keep outputs clean
        declared_keys = set(placeholder_config.keys())
        supported_keys = set(k for (k, _vals) in placeholders_list)
        unsupported = declared_keys - supported_keys
        if unsupported:
            print(f"[generate_dataset] Skipping template due to unsupported placeholders: {sorted(unsupported)}")
            continue

        # Build combinations with a cap to avoid explosion
        from itertools import product

        key_order = [k for (k, _vals) in placeholders_list]
        value_lists = [vals for (_k, vals) in placeholders_list]
        # Limit combinations to ~200 per template deterministically
        max_records = 200
        # Compute cartesian product and downsample if needed
        all_combos = list(product(*value_lists))
        if len(all_combos) > max_records:
            random.shuffle(all_combos)
            all_combos = all_combos[:max_records]

        # Determine output file per template
        out_file = DATASET_DIR / f"generated_pairs.{tpl['template_id']}.jsonl"
        print(f"[generate_dataset] Writing output JSONL: {out_file}")
        written = 0

        def _apply_cancer_rule_simple(name: str) -> str:
            # If name like "XYZ cancer" (case-insensitive), return "XYZ"; otherwise return as-is
            lower = name.lower()
            tokens = [t for t in name.split() if t]
            if len(tokens) >= 2 and "cancer" in lower:
                # remove 'cancer' token(s)
                filtered = [t for t in tokens if t.lower() != "cancer"]
                return " ".join(filtered) if filtered else name
            return name

        with out_file.open("w", encoding="utf-8") as out_f:
            for i, combo in enumerate(all_combos, start=1):
                placeholders = {k: v for k, v in zip(key_order, combo)}
                # Apply simple Cancer Rule only to cypher placeholders
                cypher_placeholders = placeholders.copy()
                if "disease_name" in cypher_placeholders:
                    cypher_placeholders["disease_name"] = _apply_cancer_rule_simple(cypher_placeholders["disease_name"])

                q_text = render_template(tpl["question"], placeholders)
                cypher_text = render_template(tpl["cypher"], cypher_placeholders)
                record = {
                    "id": f"{tpl['family_id']}-{i:06d}",
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
                            "id": f"{tpl['family_id']}-{i:06d}-P{j}",
                            "question": q_text_p,
                            "source": "paraphrase",
                            "paraphrase_of": record["id"],
                        }
                        out_f.write(json.dumps(new_rec, ensure_ascii=False) + "\n")
                        written += 1
                        if written % 5 == 0:
                            print(f"[generate_dataset] Wrote {written} records…")
        print(f"[generate_dataset] Done for {tpl['template_id']}. Total records written: {written}")


if __name__ == "__main__":
    main()
