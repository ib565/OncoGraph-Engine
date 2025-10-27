from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

OT_URL = "https://api.platform.opentargets.org/api/v4/graphql"


def _post_graphql(query: str, variables: dict[str, Any] | None = None, *, url: str = OT_URL) -> dict[str, Any]:
    payload = {"query": query, "variables": variables or {}}
    data_bytes = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}

    # Simple retry policy for 429/5xx
    for attempt in range(1, 4):
        try:
            req = Request(url, data=data_bytes, headers=headers, method="POST")
            with urlopen(req, timeout=60) as resp:
                text = resp.read().decode("utf-8")
            data_obj = json.loads(text)
            if "errors" in data_obj:
                raise RuntimeError(f"OpenTargets GraphQL errors: {data_obj['errors']}")
            return data_obj.get("data", {})
        except HTTPError as exc:
            code = getattr(exc, "code", None)
            if code in (429, 500, 502, 503, 504) and attempt < 3:
                sleep_s = 2**attempt
                print(f"[opentargets][warn] HTTP {code}; retrying in {sleep_s}s " f"(attempt {attempt}/3)")
                time.sleep(sleep_s)
                continue
            raise
        except URLError:
            if attempt < 3:
                sleep_s = 2**attempt
                print(f"[opentargets][warn] Network error; retrying in {sleep_s}s " f"(attempt {attempt}/3)")
                time.sleep(sleep_s)
                continue
            raise


def search_drugs_by_name(names: list[str], *, page_size: int = 5) -> dict[str, dict[str, Any]]:
    """Resolve therapy names to OpenTargets drug objects (CHEMBL ID, synonyms, etc.).

    Returns mapping of input name -> {
        chembl_id, canonical_name, synonyms, trade_names, drug_type
    }.
    """
    query = """
        query searchDrug($q: String!, $size: Int!) {
          search(
            queryString: $q,
            entityNames: ["drug"],
            page: { index: 0, size: $size }
          ) {
            hits {
              id
              name
              entity
              score
              object {
                ... on Drug {
                  id
                  name
                  drugType
                  synonyms
                  tradeNames
                  crossReferences { source ids }
                }
              }
            }
          }
        }
        """.strip()

    results: dict[str, dict[str, Any]] = {}
    for raw_name in names:
        name = raw_name.strip()
        if not name:
            continue
        try:
            data = _post_graphql(query, {"q": name, "size": page_size})
        except Exception as exc:  # noqa: BLE001
            print(f"[opentargets][error] search failed for '{name}': {exc}")
            continue

        hits = ((data.get("search") or {}).get("hits")) or []
        best = None
        name_lower = name.lower()
        for hit in hits:
            obj = (hit or {}).get("object") or {}
            drug = obj or {}
            # prefer exact case-insensitive match in name, synonyms, or tradeNames
            synonyms = set((drug.get("synonyms") or []) + (drug.get("tradeNames") or []))
            if str(drug.get("name") or "").lower() == name_lower or name_lower in {s.lower() for s in synonyms}:
                best = hit
                break
        if best is None and hits:
            best = hits[0]
        if not best:
            print(f"[opentargets][warn] no drug match for '{name}'")
            continue

        drug_obj = best.get("object") or {}
        results[name] = {
            "chembl_id": drug_obj.get("id") or best.get("id"),
            "canonical_name": drug_obj.get("name") or best.get("name"),
            "synonyms": (drug_obj.get("synonyms") or []),
            "trade_names": (drug_obj.get("tradeNames") or []),
            "drug_type": drug_obj.get("drugType"),
        }
        print(f"[opentargets] resolved '{name}' -> {results[name]['chembl_id']}")
    return results


def fetch_drugs_targets(chembl_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch linked targets and mechanisms for a batch of CHEMBL IDs.

    Returns mapping chembl_id -> drug data object including targets and mechanisms.
    """
    if not chembl_ids:
        return {}
    query = """
        query drugsTargets($ids: [String!]!) {
          drugs(chemblIds: $ids) {
            id
            name
            drugType
            linkedTargets { rows { approvedSymbol } count }
            mechanismsOfAction {
              rows {
                mechanismOfAction
                actionType
                targets { approvedSymbol }
                references { source ids urls }
              }
            }
          }
        }
        """.strip()

    # Batch in chunks to avoid excessive payloads
    out: dict[str, dict[str, Any]] = {}
    chunk_size = 50
    for i in range(0, len(chembl_ids), chunk_size):
        batch = chembl_ids[i : i + chunk_size]
        try:
            data = _post_graphql(query, {"ids": batch})
        except Exception as exc:  # noqa: BLE001
            print(f"[opentargets][error] drugs query failed for {len(batch)} ids: {exc}")
            continue
        for d in data.get("drugs") or []:
            chembl_id = d.get("id")
            if not chembl_id:
                continue
            out[chembl_id] = d
            print(f"[opentargets] fetched drug {chembl_id} with targets and MoA")
    return out


def build_targets_and_enrichments(
    therapy_rows: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], set[str], dict[str, dict[str, Any]]]:
    """
    Build TARGETS relationship rows and therapy enrichments from OpenTargets.

    Returns (targets_rows, extra_gene_symbols, therapy_enrichments)
    """
    therapy_names = sorted(therapy_rows.keys())
    print(f"[opentargets] resolving {len(therapy_names)} therapies by name")
    name_to_drug = search_drugs_by_name(therapy_names)

    # Collect all chembl IDs we resolved
    chembl_list = [v.get("chembl_id") for v in name_to_drug.values() if v.get("chembl_id")]
    chembl_list = [c for c in chembl_list if isinstance(c, str)]
    chembl_set = sorted(set(chembl_list))
    print(f"[opentargets] fetching drugs targets for {len(chembl_set)} CHEMBL IDs")
    chembl_to_drug = fetch_drugs_targets(chembl_set)

    # Enrich therapies map and create targets rows
    targets_rows: list[dict[str, Any]] = []
    extra_genes: set[str] = set()
    therapy_enrichments: dict[str, dict[str, Any]] = {}

    # Helper to dedup collect
    def _norm(s: str | None) -> str | None:
        if not s:
            return None
        return s.strip()

    def _pmid_from_url(u: str) -> str | None:
        lower = (u or "").lower()
        # Common PubMed URL patterns
        # - europepmc.org/abstract/MED/<pmid>
        # - ncbi.nlm.nih.gov/pubmed/<pmid>
        # - pubmed.ncbi.nlm.nih.gov/<pmid>/
        m = re.search(r"(?:med/|/pubmed/|pubmed\.ncbi\.nlm\.nih\.gov/)(\d+)", lower)
        return m.group(1) if m else None

    for therapy_name in therapy_names:
        resolved = name_to_drug.get(therapy_name)
        if not resolved:
            continue
        chembl_id = resolved.get("chembl_id")
        therapy_enrichments[therapy_name] = {
            "chembl_id": chembl_id,
            "synonyms": sorted(
                set([s for s in (resolved.get("synonyms") or []) if s])
                | set([s for s in (resolved.get("trade_names") or []) if s])
            ),
        }

        drug_data = chembl_to_drug.get(chembl_id or "") or {}
        # Prefer mechanismsOfAction targets; fallback to linkedTargets when missing
        # Aggregate per gene
        gene_to_moa: dict[str, set[str]] = {}
        gene_to_action: dict[str, set[str]] = {}
        gene_to_refs: dict[str, set[tuple[str, str, str]]] = {}

        moa_rows = ((drug_data.get("mechanismsOfAction") or {}).get("rows")) or []
        for row in moa_rows:
            labels = [_norm(gs.get("approvedSymbol")) for gs in (row.get("targets") or []) if isinstance(gs, dict)]
            labels = [g for g in labels if g]
            if not labels:
                continue
            moa_text = _norm(row.get("mechanismOfAction"))
            action_type = _norm(row.get("actionType"))
            refs = row.get("references") or []
            ref_tuples: set[tuple[str, str, str]] = set()
            for r in refs:
                src = _norm(r.get("source")) or ""
                ids = r.get("ids") or []
                urls = r.get("urls") or []
                # Always capture URLs
                for u in urls:
                    u_norm = _norm(u) or ""
                    if u_norm:
                        ref_tuples.add((src, "", u_norm))
                        # Infer PubMed ID from URL if possible (helps populate IDs consistently)
                        pmid = _pmid_from_url(u_norm)
                        if pmid:
                            ref_tuples.add(("PubMed" if src == "" else src, pmid, ""))
                # Also capture explicit (source, id) pairs
                for rid in ids:
                    rid_norm = _norm(rid) or ""
                    if rid_norm:
                        ref_tuples.add((src, rid_norm, ""))
            for gene in labels:
                gene_to_moa.setdefault(gene, set())
                gene_to_action.setdefault(gene, set())
                gene_to_refs.setdefault(gene, set())
                if moa_text:
                    gene_to_moa[gene].add(moa_text)
                if action_type:
                    gene_to_action[gene].add(action_type)
                gene_to_refs[gene].update(ref_tuples)

        # Fallback to linkedTargets if no MoA-derived targets
        if not gene_to_moa:
            lt_rows = ((drug_data.get("linkedTargets") or {}).get("rows")) or []
            for lt in lt_rows:
                sym = _norm(lt.get("approvedSymbol"))
                if not sym:
                    continue
                gene_to_moa.setdefault(sym, set())
                gene_to_action.setdefault(sym, set())
                gene_to_refs.setdefault(sym, set())

        # Emit rows
        for gene, _ in sorted(gene_to_moa.items()):
            extra_genes.add(gene)
            moa_join = " | ".join(sorted(gene_to_moa.get(gene) or [])) or None
            action_join = " | ".join(sorted(gene_to_action.get(gene) or [])) or None
            refs = gene_to_refs.get(gene) or set()
            # dedup primarily by URL; else by (source,id)
            urls = sorted({u for (_s, _i, u) in refs if u})
            pairs = sorted({(s, i) for (s, i, u) in refs if not u and (s or i)})
            ref_sources = ";".join([s for (s, _i) in pairs]) if pairs else None
            ref_ids = ";".join([i for (_s, i) in pairs]) if pairs else None
            ref_urls = ";".join(urls) if urls else None

            targets_rows.append(
                {
                    "therapy_name": therapy_name,
                    "gene_symbol": gene,
                    "source": "opentargets",
                    "moa": moa_join,
                    "action_type": action_join,
                    "ref_sources": ref_sources,
                    "ref_ids": ref_ids,
                    "ref_urls": ref_urls,
                }
            )

    print(f"[opentargets] produced {len(targets_rows)} TARGETS rows across {len(extra_genes)} genes")
    return targets_rows, extra_genes, therapy_enrichments
