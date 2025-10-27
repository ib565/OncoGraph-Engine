"""CIViC → CSV generator for the OncoGraph graph builder.

This CLI fetches (or loads) CIViC evidence, transforms it into the same
CSV layout used by the existing graph builder, and writes outputs to a
non-committed data directory (e.g., data/civic/<YYYYMMDD>/ and latest/).

Outputs (relative to --out-dir):
  nodes/genes.csv (symbol,hgnc_id,synonyms)
  nodes/variants.csv (name,hgvs_p,consequence,synonyms)
  nodes/therapies.csv (name,modality,tags,chembl_id,synonyms)
  nodes/diseases.csv (name,doid,synonyms)
  relationships/variant_of.csv (variant_name,gene_symbol)
  relationships/affects_response.csv (
    biomarker_type,biomarker_name,therapy_name,
    effect,disease_name,pmids,source,notes
  )
  relationships/targets.csv (
    therapy_name,gene_symbol,source,moa,action_type,ref_sources,ref_ids,ref_urls
  )

Design notes:
- Minimal external deps (standard library only) to avoid requirements churn.
- TARGETS populated from OpenTargets only (no heuristic inference).
- Tag enrichment uses OpenTargets targets + name suffix heuristics (mab/tinib).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .opentargets import build_targets_and_enrichments

# Curated seed TARGETS pairs with clear mechanism of action
CURATED_TARGETS: set[tuple[str, str]] = {
    ("Cetuximab", "EGFR"),
    ("Vemurafenib", "BRAF"),
    ("Gefitinib", "EGFR"),
    ("Osimertinib", "EGFR"),
    ("Afatinib", "EGFR"),
    ("Dacomitinib", "EGFR"),
    ("Dabrafenib", "BRAF"),
    ("Encorafenib", "BRAF"),
    ("Sotorasib", "KRAS"),
    ("Trastuzumab", "ERBB2"),
    ("Margetuximab", "ERBB2"),
    ("Alectinib", "ALK"),
    ("Crizotinib", "ALK"),
    ("Ceritinib", "ALK"),
    ("Brigatinib", "ALK"),
    ("Entrectinib", "ALK"),
    ("Imatinib", "ABL1"),
    ("Dasatinib", "ABL1"),
    ("Gilteritinib", "FLT3"),
    ("Ivosidenib", "IDH1"),
}

# Known non-target denylist to avoid accidental inference
NON_TARGET_DENYLIST: set[tuple[str, str]] = {
    ("Cetuximab", "KRAS"),
}


@dataclass
class CivicEvidence:
    gene_symbol: str | None
    variant_name: str | None
    variant_hgvs_p: str | None
    disease_name: str | None
    disease_doid: str | None
    therapies: list[str]
    clinical_significance: str | None
    pmids: list[str]
    evidence_statement: str | None


def _safe_get(obj: dict, path: list[str], default: str | None = None) -> str | None:
    cur: object = obj
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur if isinstance(cur, str) else default


def _load_civic_json(input_json: str | None, url: str | None) -> list[dict]:
    if input_json:
        print(f"[civic] Loading local JSON: {input_json}")
        with open(input_json, encoding="utf-8") as f:
            data = json.load(f)
        print(f"[civic] Local JSON loaded: " f"{len(data) if isinstance(data, list) else 'records' in data}")
        return data if isinstance(data, list) else data.get("records", [])

    if not url:
        print("[civic] No URL provided for legacy v1; returning empty set")
        return []
    try:
        print(f"[civic] Fetching legacy v1 URL: {url}")
        with urlopen(url) as resp:
            text = resp.read().decode("utf-8")
            data = json.loads(text)
        count = len(data) if isinstance(data, list) else len(data.get("records", []))
        print(f"[civic] v1 response received; type={type(data).__name__}; count={count}")
        return data if isinstance(data, list) else data.get("records", [])
    except URLError as exc:
        print(f"[civic][error] v1 fetch failed: {exc}")
        return []


def _fetch_civic_v2_graphql(api_url: str, page_size: int = 500, max_pages: int | None = None) -> list[dict]:
    """Fetch CIViC v2 EvidenceItems via GraphQL with cursor pagination.

    Returns a list of raw dicts normalized to the v1-like shape expected by
    _to_evidence_items (keys: gene, variant, disease, drugs, sources, etc.).
    """
    print(f"[civic] Fetching CIViC v2 GraphQL from {api_url} with page size {page_size}")
    query = """
        query EvidenceItems($after: String, $first: Int!) {
          evidenceItems(first: $first, after: $after) {
            pageInfo { hasNextPage endCursor }
            edges {
              node {
                id
                description
                molecularProfile { name }
                disease { name doid }
                therapies { name }
                significance
                evidenceDirection
                source { citationId link }
              }
            }
          }
        }
        """.strip()

    headers = {"Content-Type": "application/json"}
    after: str | None = None
    results: list[dict] = []
    page_num = 0

    while True:
        payload = {"query": query, "variables": {"first": page_size, "after": after}}
        data_bytes = json.dumps(payload).encode("utf-8")
        try:
            req = Request(api_url, data=data_bytes, headers=headers, method="POST")
            with urlopen(req) as resp:
                text = resp.read().decode("utf-8")
        except (URLError, HTTPError) as exc:
            print(f"[civic][error] v2 request failed: {exc}")
            break

        try:
            data_obj = json.loads(text)
        except json.JSONDecodeError as exc:
            print(f"[civic][error] JSON decode failed: {exc}")
            print(text[:500])
            break

        if "errors" in data_obj:
            print(f"[civic][error] GraphQL errors: {data_obj['errors']}")
            break

        conn = ((data_obj.get("data") or {}).get("evidenceItems")) or {}
        page_info = conn.get("pageInfo") or {}
        edges = conn.get("edges") or []

        for edge in edges:
            node = (edge or {}).get("node") or {}
            # Normalize to v1-ish shape consumed by _to_evidence_items
            mp = node.get("molecularProfile") or {}
            mp_name = mp.get("name")
            raw = {
                "gene": {},  # v2 EvidenceItem has no direct gene field
                "variant": {
                    "name": mp_name,
                    "display_name": mp_name,
                    "hgvs_expressions": {},
                },
                "molecular_profile": {"name": mp_name} if mp_name else {},
                "disease": node.get("disease") or {},
                "drugs": node.get("therapies") or [],
                "clinical_significance": node.get("significance"),
                "evidence_direction": node.get("evidenceDirection"),
                "sources": [node.get("source")] if node.get("source") else [],
                "evidence_statement": node.get("description"),
            }
            # Normalize sources keys to known names
            norm_sources: list[dict] = []
            for s in raw["sources"]:
                if not isinstance(s, dict):
                    continue
                citation_id = s.get("citationId")
                url_or_link = s.get("link") or s.get("url") or ""
                pmid: str | None = None
                # Prefer numeric citationId as PubMed ID when possible
                if isinstance(citation_id, (int, str)) and str(citation_id).isdigit():
                    pmid = str(citation_id)
                else:
                    # Try extracting PMID from URL like https://pubmed.ncbi.nlm.nih.gov/33857313/
                    m = re.search(r"pubmed\\.ncbi\\.nlm\\.nih\\.gov/(\\d+)", url_or_link)
                    if m:
                        pmid = m.group(1)
                norm_sources.append(
                    {
                        "pubmed_id": pmid,
                        "pmid": pmid,
                        "citation_id": citation_id,
                    }
                )
            raw["sources"] = norm_sources
            results.append(raw)

        page_num += 1
        print(
            f"[civic] Page {page_num} fetched: items={len(edges)}; "
            f"hasNext={page_info.get('hasNextPage')}; endCursor={page_info.get('endCursor')}"
        )
        if max_pages is not None and page_num >= max_pages:
            print(f"[civic] Reached max_pages={max_pages}; stopping pagination")
            break
        has_next = bool(page_info.get("hasNextPage"))
        after = page_info.get("endCursor") if has_next else None
        if not has_next:
            break

    return results


def _to_evidence_items(raw_items: list[dict]) -> list[CivicEvidence]:
    items: list[CivicEvidence] = []
    for obj in raw_items:
        gene_symbol = None
        if isinstance(obj.get("gene"), dict):
            gene_symbol = _safe_get(obj, ["gene", "name"]) or _safe_get(obj, ["gene", "symbol"])  # type: ignore[arg-type]

        # v2 fallback: derive gene symbol from molecular profile name if missing
        if not gene_symbol and isinstance(obj.get("molecular_profile"), dict):
            mp_name = _safe_get(obj, ["molecular_profile", "name"])  # type: ignore[arg-type]
            if mp_name:
                first_token = mp_name.split(" ")[0].strip()
                # For fusions like ETV6::NTRK3, use the left-most base gene token
                base_token = first_token.split("::")[0].strip()
                if base_token and base_token.upper() == base_token:
                    gene_symbol = base_token

        # Variant: CIViC often provides display_name and hgvs (we may not have hgvs)
        variant_name_raw = None
        variant_hgvs_p = None
        if isinstance(obj.get("variant"), dict):
            variant_name_raw = _safe_get(obj, ["variant", "name"]) or _safe_get(obj, ["variant", "display_name"])
            variant_hgvs_p = _safe_get(obj, ["variant", "hgvs_expressions", "p_dot"]) or _safe_get(
                obj, ["variant", "hgvs_expressions", "protein"]
            )
        # v2: if no variant dict, fall back to molecular profile name
        if not variant_name_raw and isinstance(obj.get("molecular_profile"), dict):
            variant_name_raw = _safe_get(obj, ["molecular_profile", "name"])  # type: ignore[arg-type]

        # Disease (take first if list provided)
        disease_name = None
        disease_doid = None
        disease = obj.get("disease")
        if isinstance(disease, dict):
            disease_name = _safe_get(disease, ["name"]) or _safe_get(disease, ["display_name"])  # type: ignore[arg-type]
            # Normalize DOID: keep numeric part only
            raw_doid = _safe_get(disease, ["doid"])
            if isinstance(raw_doid, str) and raw_doid.upper().startswith("DOID:"):
                disease_doid = raw_doid.split(":", 1)[1]
            else:
                disease_doid = raw_doid
        elif isinstance(disease, list) and disease:
            first = disease[0]
            if isinstance(first, dict):
                disease_name = _safe_get(first, ["name"]) or _safe_get(first, ["display_name"])  # type: ignore[arg-type]
                raw_doid = _safe_get(first, ["doid"])  # type: ignore[arg-type]
                if isinstance(raw_doid, str) and raw_doid.upper().startswith("DOID:"):
                    disease_doid = raw_doid.split(":", 1)[1]
                else:
                    disease_doid = raw_doid

        # Drugs/therapies
        therapies: list[str] = []
        drugs = obj.get("drugs") or obj.get("therapy") or obj.get("therapies")
        if isinstance(drugs, list):
            for d in drugs:
                if isinstance(d, dict):
                    name = _safe_get(d, ["name"]) or _safe_get(d, ["drug_name"])  # type: ignore[arg-type]
                else:
                    name = str(d)
                if name:
                    therapies.append(name.strip())
        elif isinstance(drugs, dict):
            name = _safe_get(drugs, ["name"]) or _safe_get(drugs, ["drug_name"])  # type: ignore[arg-type]
            if name:
                therapies.append(name.strip())

        # Clinical significance and PMIDs
        clinical_significance = _safe_get(obj, ["clinical_significance"]) or _safe_get(obj, ["evidence_direction"])
        pmids: list[str] = []
        sources = obj.get("sources") or obj.get("citations") or obj.get("evidence_sources")
        if isinstance(sources, list):
            for s in sources:
                pmid = None
                if isinstance(s, dict):
                    pmid = (
                        _safe_get(s, ["pubmed_id"]) or _safe_get(s, ["pmid"]) or _safe_get(s, ["citation_id"])
                    )  # type: ignore[arg-type]
                if pmid:
                    pmids.append(str(pmid))

        evidence_statement = _safe_get(obj, ["evidence_statement"]) or _safe_get(obj, ["description"])

        items.append(
            CivicEvidence(
                gene_symbol=gene_symbol.strip() if isinstance(gene_symbol, str) else None,
                variant_name=(variant_name_raw.strip() if isinstance(variant_name_raw, str) else None),
                variant_hgvs_p=variant_hgvs_p.strip() if isinstance(variant_hgvs_p, str) else None,
                disease_name=disease_name.strip() if isinstance(disease_name, str) else None,
                disease_doid=disease_doid.strip() if isinstance(disease_doid, str) else None,
                therapies=[t for t in therapies if t],
                clinical_significance=(
                    clinical_significance.strip() if isinstance(clinical_significance, str) else None
                ),
                pmids=[p for p in pmids if p],
                evidence_statement=(evidence_statement.strip() if isinstance(evidence_statement, str) else None),
            )
        )
    return items


def _normalize_variant_name(gene_symbol: str | None, variant_name_raw: str | None) -> tuple[str | None, str | None]:
    if not gene_symbol or not variant_name_raw:
        return None, variant_name_raw
    token = variant_name_raw
    if token.upper().startswith(gene_symbol.upper() + " "):
        token = token[len(gene_symbol) + 1 :]
    normalized = f"{gene_symbol} {token}".strip()
    return normalized, token


def _effect_from_clinical_significance(value: str | None) -> str | None:
    if not value:
        return None
    lower = value.lower()
    # Positive response signals
    if ("sensitivity" in lower) or ("responsive" in lower) or ("benefit" in lower):
        return "sensitivity"
    # Negative response signals
    if (
        ("resistance" in lower)
        or ("adverse" in lower)
        or ("nonresponse" in lower)
        or ("no response" in lower)
        or ("lack of response" in lower)
    ):
        return "resistance"
    return None


def _write_csv(path: Path, header: list[str], rows: Iterable[Iterable[str | None]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for row in rows:
            writer.writerow(["" if v is None else v for v in row])


def _enrich_tags(therapy_name: str, targets: set[str]) -> set[str]:
    tags: set[str] = set()
    name_lower = therapy_name.lower()
    for gene_symbol in targets:
        if name_lower.endswith("mab"):
            tags.add("Antibody")
            tags.add(f"anti-{gene_symbol}")
        else:
            if name_lower.endswith("tinib"):
                tags.add("TKI")
            tags.add(f"{gene_symbol} Inhibitor")
    return tags


def _today_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d")


def run_civic_ingest(
    out_dir: Path,
    input_json: str | None,
    url: str | None,
    enrich_tags: bool,
    api: str = "v2",
    page_size: int = 500,
    max_pages: int | None = None,
) -> None:
    print(
        f"[civic] Starting ingest: api={api}, out_dir={out_dir}, "
        f"input_json={bool(input_json)}, url={url}, enrich_tags={enrich_tags}, "
        f"page_size={page_size}, max_pages={max_pages}"
    )
    if api == "v2" and not input_json:
        # Prefer GraphQL v2
        api_url = url or "https://civicdb.org/api/graphql"
        raw = _fetch_civic_v2_graphql(api_url, page_size=page_size, max_pages=max_pages)
    else:
        # Fallback to legacy v1-style list endpoint or local JSON
        raw = _load_civic_json(input_json, url)
    print(f"[civic] Raw records loaded: {len(raw)}")
    evidence_items = _to_evidence_items(raw)

    # Collectors
    gene_symbols: set[str] = set()
    variant_rows: dict[str, dict[str, str | None]] = {}
    variant_of_pairs: set[tuple[str, str]] = set()
    disease_rows: dict[str, dict[str, str | None]] = {}
    therapy_rows: dict[str, dict[str, object]] = {}
    affects_rows: list[dict[str, object]] = []

    # TARGETS no longer inferred from CIViC; will be sourced from OpenTargets

    print(f"[civic] Evidence items parsed: {len(evidence_items)}")
    for ev in evidence_items:
        # Ensure basic node presence when possible
        if ev.gene_symbol and "::" not in ev.gene_symbol:
            gene_symbols.add(ev.gene_symbol)

        variant_name_norm, variant_token = _normalize_variant_name(ev.gene_symbol, ev.variant_name)
        # Treat as a variant when we have a name and a gene symbol (include umbrella states)
        is_variant_like = bool(variant_name_norm)
        if variant_name_norm and ev.gene_symbol and is_variant_like:
            variant_rows.setdefault(
                variant_name_norm,
                {
                    "name": variant_name_norm,
                    "hgvs_p": ev.variant_hgvs_p,
                    "consequence": None,
                    "synonyms": None,
                },
            )
            # Multi-edge for fusions (e.g., BCR::ABL1) → split to base genes
            base_genes = [g.strip() for g in str(ev.gene_symbol).split("::") if g.strip()]
            for base_gene in base_genes:
                variant_of_pairs.add((variant_name_norm, base_gene))
                gene_symbols.add(base_gene)

        # Ensure we do not write fusion symbols as standalone gene nodes
        if ev.gene_symbol and "::" in ev.gene_symbol:
            for base in [g.strip() for g in ev.gene_symbol.split("::") if g.strip()]:
                gene_symbols.add(base)

        disease_name = ev.disease_name
        if disease_name:
            disease_rows.setdefault(
                disease_name,
                {"name": disease_name, "doid": ev.disease_doid, "synonyms": None},
            )

        for therapy_name in ev.therapies:
            therapy_rows.setdefault(
                therapy_name,
                {
                    "name": therapy_name,
                    "modality": None,
                    "tags": set(),
                    "chembl_id": None,
                    "synonyms": None,
                },
            )

            effect = _effect_from_clinical_significance(ev.clinical_significance)
            # Require at least a gene symbol and therapy to build relationships
            if effect and ev.gene_symbol and disease_name:
                biomarker_type = "Variant" if variant_name_norm else "Gene"
                biomarker_name = variant_name_norm if variant_name_norm else ev.gene_symbol
                affects_rows.append(
                    {
                        "biomarker_type": biomarker_type,
                        "biomarker_name": biomarker_name,
                        "therapy_name": therapy_name,
                        "effect": effect,
                        "disease_name": disease_name,
                        "pmids": ";".join(sorted(set(ev.pmids))) if ev.pmids else "",
                        "source": "civic",
                        "notes": "",
                    }
                )

                # We no longer use CIViC to infer TARGETS; skip accumulation

    # Build TARGETS and enrichments from OpenTargets
    print(f"[civic] Querying OpenTargets for {len(therapy_rows)} therapies…")
    ot_target_rows, ot_extra_genes, ot_enrich = build_targets_and_enrichments(therapy_rows)
    print("[civic] OpenTargets returned " f"{len(ot_target_rows)} TARGETS rows; extra genes={len(ot_extra_genes)}")

    # Apply therapy enrichments and extend genes list
    for tname, enrich in ot_enrich.items():
        if tname not in therapy_rows:
            continue
        if enrich.get("chembl_id"):
            therapy_rows[tname]["chembl_id"] = enrich.get("chembl_id")
        if enrich.get("synonyms"):
            existing_syn = therapy_rows[tname].get("synonyms") or []
            merged = sorted(set(existing_syn) | set(enrich.get("synonyms") or []))
            therapy_rows[tname]["synonyms"] = ";".join(merged) if merged else None
    for g in ot_extra_genes:
        gene_symbols.add(g)

    # Tag enrichment based on targets
    if enrich_tags:
        therapy_to_targets: dict[str, set[str]] = defaultdict(set)
        for r in ot_target_rows:
            tname = str(r.get("therapy_name") or "").strip()
            gsym = str(r.get("gene_symbol") or "").strip()
            if tname and gsym:
                therapy_to_targets[tname].add(gsym)
        for therapy_name, meta in therapy_rows.items():
            targets = therapy_to_targets.get(therapy_name, set())
            if not targets:
                continue
            inferred_tags = _enrich_tags(therapy_name, targets)
            current_tags = meta.get("tags", set())
            if isinstance(current_tags, set):
                meta["tags"] = current_tags.union(inferred_tags)

            # Best-effort modality based on name
            name_lower = therapy_name.lower()
            if name_lower.endswith("mab"):
                meta["modality"] = "Antibody"
            elif name_lower.endswith("tinib"):
                meta["modality"] = "TKI"

    # Prepare output directory structure
    date_dir = out_dir
    date_tag = _today_stamp()
    if out_dir.name == "latest":
        date_dir = out_dir.parent / date_tag
    (date_dir / "nodes").mkdir(parents=True, exist_ok=True)
    (date_dir / "relationships").mkdir(parents=True, exist_ok=True)
    # Also ensure latest/ exists (mirror/copy paths kept simple by writing twice)
    (out_dir / "nodes").mkdir(parents=True, exist_ok=True)
    (out_dir / "relationships").mkdir(parents=True, exist_ok=True)

    # Write nodes
    # Filter out synthetic fusion symbols from genes before writing
    base_gene_symbols = sorted({s for s in gene_symbols if "::" not in s})
    print(
        f"[civic] Writing nodes: genes={len(base_gene_symbols)}, variants={len(variant_rows)},"
        f" therapies={len(therapy_rows)}, diseases={len(disease_rows)}"
    )
    if not base_gene_symbols:
        print("[civic][warn] No genes derived. Check molecularProfile.name parsing.")
    if not variant_rows:
        print("[civic][warn] No variants derived. Evidence set may be gene-level only, " "or tokens lacked digits.")
    _write_csv(
        date_dir / "nodes" / "genes.csv",
        ["symbol", "hgnc_id", "synonyms"],
        ((symbol, "", "") for symbol in base_gene_symbols),
    )
    _write_csv(
        out_dir / "nodes" / "genes.csv",
        ["symbol", "hgnc_id", "synonyms"],
        ((symbol, "", "") for symbol in base_gene_symbols),
    )

    _write_csv(
        date_dir / "nodes" / "variants.csv",
        ["name", "hgvs_p", "consequence", "synonyms"],
        (
            tuple(variant_rows[name].get(k) for k in ("name", "hgvs_p", "consequence", "synonyms"))
            for name in sorted(variant_rows.keys())
        ),
    )
    _write_csv(
        out_dir / "nodes" / "variants.csv",
        ["name", "hgvs_p", "consequence", "synonyms"],
        (
            tuple(variant_rows[name].get(k) for k in ("name", "hgvs_p", "consequence", "synonyms"))
            for name in sorted(variant_rows.keys())
        ),
    )

    def _tags_to_str(val: object) -> str:
        if isinstance(val, set):
            return ";".join(sorted(val))
        if isinstance(val, list):
            return ";".join(val)
        return str(val) if val is not None else ""

    therapies_sorted = sorted(therapy_rows.keys())
    _write_csv(
        date_dir / "nodes" / "therapies.csv",
        ["name", "modality", "tags", "chembl_id", "synonyms"],
        (
            (
                therapy_rows[name].get("name"),
                therapy_rows[name].get("modality"),
                _tags_to_str(therapy_rows[name].get("tags", set())),
                therapy_rows[name].get("chembl_id"),
                therapy_rows[name].get("synonyms"),
            )
            for name in therapies_sorted
        ),
    )
    _write_csv(
        out_dir / "nodes" / "therapies.csv",
        ["name", "modality", "tags", "chembl_id", "synonyms"],
        (
            (
                therapy_rows[name].get("name"),
                therapy_rows[name].get("modality"),
                _tags_to_str(therapy_rows[name].get("tags", set())),
                therapy_rows[name].get("chembl_id"),
                therapy_rows[name].get("synonyms"),
            )
            for name in therapies_sorted
        ),
    )

    diseases_sorted = sorted(disease_rows.keys())
    _write_csv(
        date_dir / "nodes" / "diseases.csv",
        ["name", "doid", "synonyms"],
        (
            (
                disease_rows[name].get("name"),
                disease_rows[name].get("doid"),
                disease_rows[name].get("synonyms"),
            )
            for name in diseases_sorted
        ),
    )
    _write_csv(
        out_dir / "nodes" / "diseases.csv",
        ["name", "doid", "synonyms"],
        (
            (
                disease_rows[name].get("name"),
                disease_rows[name].get("doid"),
                disease_rows[name].get("synonyms"),
            )
            for name in diseases_sorted
        ),
    )

    # Write relationships
    print(
        "[civic] Writing relationships: "
        f"variant_of={len(variant_of_pairs)}, "
        f"affects_response={len(affects_rows)}, "
        f"targets={len(ot_target_rows)}"
    )
    _write_csv(
        date_dir / "relationships" / "variant_of.csv",
        ["variant_name", "gene_symbol"],
        sorted(variant_of_pairs),
    )
    _write_csv(
        out_dir / "relationships" / "variant_of.csv",
        ["variant_name", "gene_symbol"],
        sorted(variant_of_pairs),
    )

    def _affects_rows_iter():
        for r in affects_rows:
            yield (
                str(r.get("biomarker_type") or ""),
                str(r.get("biomarker_name") or ""),
                str(r.get("therapy_name") or ""),
                str(r.get("effect") or ""),
                str(r.get("disease_name") or ""),
                str(r.get("pmids") or ""),
                str(r.get("source") or ""),
                str(r.get("notes") or ""),
            )

    _write_csv(
        date_dir / "relationships" / "affects_response.csv",
        [
            "biomarker_type",
            "biomarker_name",
            "therapy_name",
            "effect",
            "disease_name",
            "pmids",
            "source",
            "notes",
        ],
        _affects_rows_iter(),
    )
    _write_csv(
        out_dir / "relationships" / "affects_response.csv",
        [
            "biomarker_type",
            "biomarker_name",
            "therapy_name",
            "effect",
            "disease_name",
            "pmids",
            "source",
            "notes",
        ],
        _affects_rows_iter(),
    )

    def _targets_rows_iter():
        for r in ot_target_rows:
            yield (
                str(r.get("therapy_name") or ""),
                str(r.get("gene_symbol") or ""),
                str(r.get("source") or ""),
                str(r.get("moa") or ""),
                str(r.get("action_type") or ""),
                (
                    ";".join(r.get("ref_sources") or [])
                    if isinstance(r.get("ref_sources"), list)
                    else str(r.get("ref_sources") or "")
                ),
                (
                    ";".join(r.get("ref_ids") or [])
                    if isinstance(r.get("ref_ids"), list)
                    else str(r.get("ref_ids") or "")
                ),
                (
                    ";".join(r.get("ref_urls") or [])
                    if isinstance(r.get("ref_urls"), list)
                    else str(r.get("ref_urls") or "")
                ),
            )

    _write_csv(
        date_dir / "relationships" / "targets.csv",
        [
            "therapy_name",
            "gene_symbol",
            "source",
            "moa",
            "action_type",
            "ref_sources",
            "ref_ids",
            "ref_urls",
        ],
        _targets_rows_iter(),
    )
    _write_csv(
        out_dir / "relationships" / "targets.csv",
        [
            "therapy_name",
            "gene_symbol",
            "source",
            "moa",
            "action_type",
            "ref_sources",
            "ref_ids",
            "ref_urls",
        ],
        _targets_rows_iter(),
    )

    print(f"[civic] Done. Wrote CSVs to: {date_dir} and {out_dir}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate CSVs from CIViC for OncoGraph")
    parser.add_argument(
        "--out-dir",
        default="data/civic/latest",
        help="Output directory root (will also write a dated snapshot sibling)",
    )
    parser.add_argument(
        "--input-json",
        help="Path to a local CIViC JSON export (skips network fetch)",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Override CIViC API URL. For v2, defaults to https://civicdb.org/api/graphql",
    )
    parser.add_argument(
        "--api",
        choices=["v2", "v1"],
        default="v2",
        help="Choose CIViC API version: v2 GraphQL (default) or v1 legacy",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=500,
        help="GraphQL page size for v2 pagination",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Maximum number of GraphQL pages to fetch (v2 only)",
    )
    parser.add_argument(
        "--enrich-tags",
        action="store_true",
        help="Derive therapy tags and modality from inferred/curated targets",
    )
    args = parser.parse_args(argv)

    out_path = Path(args.out_dir)
    run_civic_ingest(
        out_path,
        args.input_json,
        args.url,
        args.enrich_tags,
        api=args.api,
        page_size=args.page_size,
        max_pages=args.max_pages,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
