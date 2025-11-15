import json
import os
import random
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from oncograph_finetuning.dataset_generation.loaders.civic_loader import CivicIndex

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = ROOT / "oncograph_finetuning" / "dataset_generation" / "templates"
DATASET_DIR = ROOT / "data" / "raw"


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
        f"[generate_dataset] Sampling complete for {placeholder_key}: "
        f"curated={len(curated_present)} random={len(random_sample)} total={len(result)}"
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

    # Environment variable configuration
    max_disease_synonyms_env = os.environ.get("GEN_DS_MAX_DISEASE_SYNONYMS")
    print(f"[generate_dataset] max_disease_synonyms_env: {max_disease_synonyms_env}")
    try:
        max_disease_synonyms = int(max_disease_synonyms_env) if max_disease_synonyms_env else 2
    except ValueError:
        max_disease_synonyms = 2
        print(f"[generate_dataset] Invalid GEN_DS_MAX_DISEASE_SYNONYMS, using default: {max_disease_synonyms}")
    print(f"[generate_dataset] max_disease_synonyms: {max_disease_synonyms}")
    seed_env = os.environ.get("GEN_DS_SEED")
    if seed_env and seed_env.lower() != "none":
        try:
            seed_value = int(seed_env)
            random.seed(seed_value)
            print(f"[generate_dataset] Using seed: {seed_value}")
        except ValueError:
            random.seed(42)
            print("[generate_dataset] Invalid GEN_DS_SEED, using default: 42")
    elif seed_env and seed_env.lower() == "none":
        print("[generate_dataset] Seed disabled (GEN_DS_SEED=none)")
    else:
        random.seed(42)

    # Build CIViC index
    print("[generate_dataset] Building CIViC index…")
    index = CivicIndex()
    # Filter therapies by chembl_id and diseases by doid to prefer widely-used entities
    index.build(require_chembl_id=True, require_doid=True)
    DATASET_DIR.mkdir(parents=True, exist_ok=True)

    total_records = 0
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

        def _escape_cypher_literal(value: str) -> str:
            """Escape a Python string for safe inclusion in single-quoted Cypher string literals.

            Rules:
            - Backslashes first (\\ -> \\\\)
            - Single quotes (') as \'
            """
            return value.replace("\\", "\\\\").replace("'", "\\'")

        def _is_umbrella_disease(name: str) -> bool:
            """Check if disease name follows cancer rule (umbrella term like 'Lung Cancer')."""
            lower = name.lower()
            tokens = [t for t in name.split() if t]
            return len(tokens) >= 2 and "cancer" in lower

        def tokenize_disease(name: str, is_umbrella: bool = False) -> list[str]:
            """Tokenize disease name, preserving hyphens.

            Args:
                name: Disease name (e.g., "Non-small Cell Lung Carcinoma")
                is_umbrella: If True, return minimal anchor token(s). If False, return all tokens.

            Returns:
                List of lowercase tokens (e.g., ['lung'] for umbrella,
                ['lung','non-small','cell','carcinoma'] for specific)
            """
            lower = name.lower()
            tokens = [t.strip() for t in lower.split() if t.strip()]

            if is_umbrella:
                # For umbrella terms, return minimal anchor token(s)
                # Remove 'cancer' token(s) if present, keep the rest
                filtered = [t for t in tokens if t != "cancer"]
                return filtered if filtered else tokens
            else:
                # For specific diseases, return all tokens (hyphens preserved)
                return tokens

        def build_disease_filter(tokens: list[str], aliases: list[str] | None = None, use_where: bool = False) -> str:
            """Build Cypher WHERE clause fragment for disease filtering with order-invariant token matching.

            Args:
                tokens: List of lowercase tokens to match (e.g., ['lung','non-small','cell','carcinoma'])
                aliases: Optional list of alias strings (e.g., ['nsclc'])
                use_where: If True, start with WHERE instead of AND (for first condition after MATCH)

            Returns:
                Cypher fragment: "WHERE ( ... )" or "AND ( ... )" depending on use_where
                With optional OR clause for aliases if provided.
            """
            if not tokens:
                return ""

            # Build AND clause for each token
            token_clauses = [f"toLower(rel.disease_name) CONTAINS '{_escape_cypher_literal(t)}'" for t in tokens]
            and_clause = " AND\n    ".join(token_clauses)

            prefix = "WHERE" if use_where else "AND"

            if aliases:
                # Build OR clause for aliases
                alias_clauses = [
                    f"toLower(rel.disease_name) CONTAINS '{_escape_cypher_literal(alias)}'" for alias in aliases
                ]
                alias_or = " OR\n    ".join(alias_clauses)
                return f"{prefix} (\n    {and_clause}\n    OR {alias_or}\n  )"
            else:
                return f"{prefix} (\n    {and_clause}\n  )"

        with out_file.open("w", encoding="utf-8") as out_f:
            for i, combo in enumerate(all_combos, start=1):
                placeholders = {k: v for k, v in zip(key_order, combo, strict=False)}
                # Prepare cypher placeholders with tokenized disease filter
                cypher_placeholders = placeholders.copy()
                if "disease_name" in cypher_placeholders:
                    disease_name = cypher_placeholders["disease_name"]
                    is_umbrella = _is_umbrella_disease(disease_name)
                    tokens = tokenize_disease(disease_name, is_umbrella=is_umbrella)
                    # Build disease filter fragment for templates that use {{ disease_filter }}
                    # Check if template needs WHERE (first condition) or AND (continued condition)
                    cypher_template = tpl.get("cypher", "")
                    disease_filter_pos = cypher_template.find("{{ disease_filter }}")
                    # Look at the text immediately before {{ disease_filter }}
                    text_before = cypher_template[:disease_filter_pos].strip()
                    # Check if it ends with MATCH or if there's a WHERE on the same line context
                    # If disease_filter follows MATCH/OPTIONAL MATCH directly, need WHERE
                    # If disease_filter is part of an existing WHERE clause, use AND
                    use_where = False
                    if text_before:
                        # Find the last MATCH/OPTIONAL MATCH/WITH before disease_filter
                        last_match = max(
                            text_before.rfind("MATCH"),
                            text_before.rfind("OPTIONAL MATCH"),
                            text_before.rfind("WITH"),
                        )
                        if last_match >= 0:
                            # Check if there's a WHERE between the last MATCH/WITH and disease_filter
                            text_after_match = text_before[last_match:].strip()
                            # If there's no WHERE after the last MATCH/WITH, need WHERE
                            if "WHERE" not in text_after_match:
                                use_where = True
                            else:
                                # There's a WHERE clause already, so use AND to continue it
                                use_where = False
                        else:
                            # No MATCH/WITH found, default to WHERE for safety
                            use_where = True
                    cypher_placeholders["disease_filter"] = build_disease_filter(
                        tokens, aliases=None, use_where=use_where
                    )
                    # Keep original disease_name for question templates (escaped)
                    cypher_placeholders["disease_name"] = _escape_cypher_literal(disease_name)
                # Escape values for Cypher string literals (only strings are expected here)
                for k, v in list(cypher_placeholders.items()):
                    if isinstance(v, str) and k != "disease_filter":  # disease_filter is already formatted
                        cypher_placeholders[k] = _escape_cypher_literal(v)

                # Determine disease name variants (canonical + synonyms)
                disease_variants = []
                if "disease_name" in placeholders:
                    disease_name = placeholders["disease_name"]
                    # Always include canonical name as first variant
                    disease_variants.append(disease_name)
                    # Add synonym variants if available
                    synonyms = index.get_disease_synonyms(disease_name)
                    if synonyms:
                        # Sample random number of synonyms (1 to min(max_disease_synonyms, len(synonyms)))
                        num_synonyms = random.randint(1, min(max_disease_synonyms, len(synonyms)))
                        sampled_synonyms = random.sample(synonyms, num_synonyms)
                        disease_variants.extend(sampled_synonyms)
                else:
                    # No disease in this combo, just use canonical placeholder
                    disease_variants = [None]

                # Generate records for each disease variant (canonical + synonyms)
                for s_idx, disease_display_name in enumerate(disease_variants):
                    # Create question placeholders (may use synonym)
                    q_placeholders = placeholders.copy()
                    if disease_display_name is not None:
                        q_placeholders["disease_name"] = disease_display_name

                    # Cypher placeholders always use canonical disease name (from original placeholders)
                    q_text = render_template(tpl["question"], q_placeholders)
                    cypher_text = render_template(tpl["cypher"], cypher_placeholders)

                    # Build record ID: canonical gets base ID, synonyms get -S<N> suffix
                    if s_idx == 0:
                        base_id = f"{tpl['family_id']}-{i:06d}"
                    else:
                        base_id = f"{tpl['family_id']}-{i:06d}-S{s_idx}"

                    record = {
                        "id": base_id,
                        "family_id": tpl["family_id"],
                        "template_id": tpl["template_id"],
                        "question": q_text,
                        "cypher": cypher_text,
                        "placeholders": placeholders,  # Always canonical for ground truth
                        "source": "base",
                        "paraphrase_of": None,
                    }
                    out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    written += 1

                    # Generate paraphrases for this variant
                    if paraphrase_templates:
                        for j, qtpl in enumerate(paraphrase_templates, start=1):
                            q_text_p = render_template(qtpl, q_placeholders)
                            new_rec = {
                                **record,
                                "id": f"{base_id}-P{j}",
                                "question": q_text_p,
                                "source": "paraphrase",
                                "paraphrase_of": record["id"],
                            }
                            out_f.write(json.dumps(new_rec, ensure_ascii=False) + "\n")
                            written += 1

                # Print progress after writing all records for this combo (base + synonyms + paraphrases)
                if written % 50 == 0:
                    print(f"[generate_dataset] Wrote {written} records…")
        print(f"[generate_dataset] Done for {tpl['template_id']}. Total records written: {written}")
        total_records += written

    print(f"[generate_dataset] All templates processed. Total records across all templates: {total_records}")


if __name__ == "__main__":
    main()
