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


def _relationship_combos(index: CivicIndex, template_id: str, placeholder_keys: set[str]) -> list[dict[str, str]]:
    """Derive placeholder combos from relationships for high hit-rate where possible.

    Returns a list of dicts mapping placeholder -> value.
    """
    combos: list[dict[str, str]] = []
    keys = placeholder_keys

    # Common helpers
    targets_pairs = index.get_targets_pairs()
    targets_genes = index.get_targets_genes()
    targets_therapies = index.get_targets_therapies()

    # F1 / F2.1 patterns
    if keys == {"gene_symbol", "therapy_name"}:
        for tname, gsym in targets_pairs:
            combos.append({"therapy_name": tname, "gene_symbol": gsym})
        return combos
    if keys == {"gene_symbol"}:
        for gsym in targets_genes:
            combos.append({"gene_symbol": gsym})
        return combos
    if keys == {"therapy_name"}:
        for tname in targets_therapies:
            combos.append({"therapy_name": tname})
        return combos

    # AFFECTS: gene-only by therapy+disease (general)
    if keys == {"therapy_name", "disease_name"}:
        effect: str | None = None
        if "resistance" in template_id:
            effect = "resistance"
        elif "sensitivity" in template_id:
            effect = "sensitivity"
        for tname, dname in index.get_affects_pairs(effect=effect, require_variant=None):
            combos.append({"therapy_name": tname, "disease_name": dname})
        return combos

    # AFFECTS: variant-specific
    if keys == {"variant_name", "therapy_name", "disease_name"}:
        effect = None
        if "resistance" in template_id:
            effect = "resistance"
        elif "sensitivity" in template_id:
            effect = "sensitivity"
        for vname, tname, dname in index.get_affects_variant_triples(effect=effect):
            combos.append({"variant_name": vname, "therapy_name": tname, "disease_name": dname})
        return combos

    # Evidence: variant + therapy (no disease filter)
    if keys == {"variant_name", "therapy_name"}:
        effect = None
        if "resistance" in template_id:
            effect = "resistance"
        elif "sensitivity" in template_id:
            effect = "sensitivity"
        seen: set[tuple[str, str]] = set()
        for vname, tname, _dname in index.get_affects_variant_triples(effect=effect):
            pair = (vname, tname)
            if pair in seen:
                continue
            seen.add(pair)
            combos.append({"variant_name": vname, "therapy_name": tname})
        return combos

    # F5 disease centric (use diseases present in affects)
    if keys == {"disease_name"}:
        seen_d: set[str] = set()
        for _v, _tname, dname in index.get_affects_variant_triples(effect=None):
            if dname not in seen_d:
                seen_d.add(dname)
                combos.append({"disease_name": dname})
        # Fallback to any disease present in affects (gene-only rows)
        for _tname, dname in index.get_affects_pairs(effect=None, require_variant=None):
            if dname not in seen_d:
                seen_d.add(dname)
                combos.append({"disease_name": dname})
        return combos

    # F3 set operations
    if template_id == "f3_1_therapies_union_genes" and keys == {"gene_symbol_a", "gene_symbol_b"}:
        genes = targets_genes
        for i in range(0, min(len(genes), 200), 2):
            if i + 1 < len(genes):
                combos.append({"gene_symbol_a": genes[i], "gene_symbol_b": genes[i + 1]})
        return combos

    if template_id == "f3_2_therapies_intersection_genes" and keys == {"gene_symbol_a", "gene_symbol_b"}:
        # Build gene -> set(therapies)
        from collections import defaultdict

        g2t: dict[str, set[str]] = defaultdict(set)
        for tname, gsym in targets_pairs:
            g2t[gsym].add(tname)
        genes = list(g2t.keys())
        for i in range(len(genes)):
            for j in range(i + 1, len(genes)):
                inter = g2t[genes[i]] & g2t[genes[j]]
                if inter:
                    combos.append({"gene_symbol_a": genes[i], "gene_symbol_b": genes[j]})
                    if len(combos) >= 200:
                        return combos
        return combos

    if template_id == "f3_3_therapies_target_a_not_b" and keys == {"gene_symbol_include", "gene_symbol_exclude"}:
        from collections import defaultdict

        g2t: dict[str, set[str]] = defaultdict(set)
        for tname, gsym in targets_pairs:
            g2t[gsym].add(tname)
        genes = list(g2t.keys())
        for gi in genes:
            for gx in genes:
                if gi == gx:
                    continue
                if g2t[gi] - g2t[gx]:
                    combos.append({"gene_symbol_include": gi, "gene_symbol_exclude": gx})
                    if len(combos) >= 200:
                        return combos
        return combos

    # F4.2 / F6.4: alternative therapies from resistance genes
    if template_id in {
        "f4_2_alternative_therapies_from_resistance_genes",
        "f6_4_alternative_therapies_for_resistance_in_disease",
    } and keys == {"therapy_name", "disease_name"}:
        for tname, dname in index.get_affects_pairs(effect="resistance", require_variant=None):
            combos.append({"therapy_name": tname, "disease_name": dname})
        return combos

    # F4.1: target validation gene+disease (pick gene with a therapy that has affects in disease)
    if template_id == "f4_1_target_validation_gene_disease" and keys == {"gene_symbol", "disease_name"}:
        from collections import defaultdict

        # therapy -> set(diseases with affects)
        t2d: dict[str, set[str]] = defaultdict(set)
        for tname, dname in index.get_affects_pairs(effect=None, require_variant=None):
            t2d[tname].add(dname)
        # gene -> set(therapies)

        g2t: dict[str, set[str]] = defaultdict(set)
        for tname, gsym in targets_pairs:
            g2t[gsym].add(tname)
        for gsym, tset in g2t.items():
            for tname in tset:
                if tname in t2d:
                    for dname in t2d[tname]:
                        combos.append({"gene_symbol": gsym, "disease_name": dname})
                        if len(combos) >= 200:
                            return combos
        return combos

    # F6.1: resistance genes for union therapies in disease
    if template_id == "f6_1_resistance_genes_for_union_therapies_in_disease" and keys == {
        "therapy_name_a",
        "therapy_name_b",
        "disease_name",
    }:
        from collections import defaultdict

        d2t: dict[str, set[str]] = defaultdict(set)
        for tname, dname in index.get_affects_pairs(effect="resistance", require_variant=None):
            d2t[dname].add(tname)
        for dname, tset in d2t.items():
            tlist = list(tset)
            for i in range(0, len(tlist) - 1):
                combos.append({"therapy_name_a": tlist[i], "therapy_name_b": tlist[i + 1], "disease_name": dname})
                if len(combos) >= 200:
                    return combos
        return combos

    # F6.2: therapies target include gene not other with disease evidence
    if template_id == "f6_2_therapies_target_gene_not_other_with_disease_evidence" and keys == {
        "gene_include",
        "gene_exclude",
        "disease_name",
    }:
        from collections import defaultdict

        t2d: dict[str, set[str]] = defaultdict(set)
        for tname, dname in index.get_affects_pairs(effect=None, require_variant=None):
            t2d[tname].add(dname)
        g2t: dict[str, set[str]] = defaultdict(set)
        for tname, gsym in targets_pairs:
            g2t[gsym].add(tname)
        for gsym, tset in g2t.items():
            for tname in tset:
                if tname in t2d:
                    for dname in t2d[tname]:
                        # choose an exclude gene different from gsym
                        for gx in g2t.keys():
                            if gx != gsym:
                                combos.append({"gene_include": gsym, "gene_exclude": gx, "disease_name": dname})
                                if len(combos) >= 200:
                                    return combos
        return combos

    # F6.3: therapies target gene with variant resistance in disease -> sample (gene, disease)
    if template_id == "f6_3_therapies_target_gene_with_variant_resistance_in_disease" and keys == {
        "gene_symbol",
        "disease_name",
    }:
        from collections import defaultdict

        # For each variant-resistance record, map therapy to its target genes
        for _vname, tname, dname in index.get_affects_variant_triples(effect="resistance"):
            # find genes targeted by tname
            for t_pair in targets_pairs:
                if t_pair[0] == tname:
                    combos.append({"gene_symbol": t_pair[1], "disease_name": dname})
                    if len(combos) >= 200:
                        return combos
        return combos

    return combos


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

        # Determine placeholders
        placeholder_config = tpl.get("placeholders", {})

        # Curated lists per entity type
        curated_genes = ["BRAF", "EGFR", "KRAS", "ALK", "PIK3CA"]
        curated_therapies = ["Dabrafenib", "Osimertinib", "Cetuximab", "Trastuzumab", "Imatinib"]
        curated_variants = ["BRAF V600E", "KRAS G12C", "EGFR Exon19del", "EGFR T790M", "BCR BCR::ABL1 Fusion"]
        curated_diseases = ["Colorectal Cancer", "Lung Cancer", "Skin Melanoma", "Breast Cancer"]
        declared_keys = list(placeholder_config.keys())
        if not declared_keys:
            print("[generate_dataset] Skipping: no placeholders in template")
            continue

        # First try relationship-driven combos using declared keys (supports multi-key templates)
        rel_combos = _relationship_combos(index, tpl["template_id"], set(declared_keys))
        if rel_combos:
            key_order = declared_keys
            all_combos = [tuple(combo[k] for k in key_order) for combo in rel_combos]
        else:
            # Fall back to sampling only for recognized single-key placeholders
            placeholders_list: list[tuple[str, list[str]]] = []
            if "gene_symbol" in placeholder_config:
                genes = index.get_gene_symbols()
                placeholders_list.append(("gene_symbol", sample_entities("gene_symbol", genes, curated_genes)))
            if "therapy_name" in placeholder_config:
                therapies = index.get_therapy_names()
                placeholders_list.append(
                    ("therapy_name", sample_entities("therapy_name", therapies, curated_therapies))
                )
            if "variant_name" in placeholder_config:
                variants = index.get_variant_names()
                # For variant-only templates (e.g., F1.3), sample a larger set for parity with other families
                placeholders_list.append(
                    ("variant_name", sample_entities("variant_name", variants, curated_variants, count=200))
                )
            if "disease_name" in placeholder_config:
                diseases = index.get_disease_names()
                placeholders_list.append(("disease_name", sample_entities("disease_name", diseases, curated_diseases)))

            if not placeholders_list:
                print("[generate_dataset] Skipping: no supported placeholders and no relationship combos")
                continue

            # Simple cartesian product over independently sampled entities
            from itertools import product

            key_order = [k for (k, _vals) in placeholders_list]
            value_lists = [vals for (_k, vals) in placeholders_list]
            all_combos = list(product(*value_lists))

        # Limit combinations to ~200 per template deterministically
        max_records = 200
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
                placeholders = {k: v for k, v in zip(key_order, combo, strict=False)}
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
                # Print progress after writing all records for this combo (base + paraphrases)
                if written % 50 == 0:
                    print(f"[generate_dataset] Wrote {written} records…")
        print(f"[generate_dataset] Done for {tpl['template_id']}. Total records written: {written}")


if __name__ == "__main__":
    main()
