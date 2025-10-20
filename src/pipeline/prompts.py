from textwrap import dedent

SCHEMA_SNIPPET = dedent(
    """
    Graph schema (condensed):
    - Labels: Gene(symbol, hgnc_id, synonyms),
      Variant(name, hgvs_p, consequence, synonyms),
      Therapy(name, modality, tags, chembl_id, synonyms),
      Disease(name, doid, synonyms)
    - Helper label: Biomarker (applied to Gene and Variant)
    - Relationships:
      (Variant)-[:VARIANT_OF]->(Gene)
      (Therapy)-[:TARGETS {source}]->(Gene)
      (Biomarker)-[:AFFECTS_RESPONSE_TO {effect, disease_name, disease_id?,
        pmids, source, notes?}]->(Therapy)
    - Array properties: pmids, tags
    - No parameters: inline single-quoted literals only
      (no $variables)

    Canonical return contract (aliases and order required):
    RETURN
      CASE WHEN biomarker:Variant THEN coalesce(biomarker.name, biomarker.hgvs_p)
      END AS variant_name,
      CASE WHEN biomarker:Gene THEN biomarker.symbol ELSE gene.symbol
      END AS gene_symbol,
      therapy.name AS therapy_name,
      rel.effect AS effect,
      rel.disease_name AS disease_name,
      coalesce(rel.pmids, []) AS pmids
    LIMIT …

    Canonical example (adapt values as needed):
      MATCH (b:Biomarker)-[rel:AFFECTS_RESPONSE_TO]->(t:Therapy)
      WHERE (
        any(tag IN t.tags WHERE toLower(tag) CONTAINS toLower('anti-EGFR'))
        OR (t)-[:TARGETS]->(:Gene {symbol: 'EGFR'})
      )
      AND rel.effect = 'resistance'
      AND toLower(rel.disease_name) = toLower('colorectal cancer')
      OPTIONAL MATCH (b)-[:VARIANT_OF]->(g:Gene)
      RETURN
        CASE WHEN b:Variant THEN coalesce(b.name, b.hgvs_p) END AS variant_name,
        CASE WHEN b:Gene THEN b.symbol ELSE g.symbol END AS gene_symbol,
        t.name AS therapy_name,
        rel.effect AS effect,
        rel.disease_name AS disease_name,
        coalesce(rel.pmids, []) AS pmids
      LIMIT 10

    Canonical rules:
    - Gene-only: match biomarker as the Gene OR any Variant VARIANT_OF that Gene
      (prefer single MATCH + OR; avoid WHERE immediately after UNWIND).
    - Specific variant:
      - Always require VARIANT_OF to the named gene.
      - Prefer equality on Variant.name for full names like 'KRAS G12C' or
        'BCR::ABL1 Fusion'. Fallback to toLower(Variant.name) CONTAINS toLower('<TOKEN>').
      - For fusion tokens (e.g., "EML4-ALK", "EML4::ALK"), match either orientation:
        toLower(Variant.name) CONTAINS toLower('EML4::ALK') OR
        toLower(Variant.name) CONTAINS toLower('ALK::EML4').
      - For alteration-class tokens ("Amplification", "Overexpression", "Deletion",
        "Loss-of-function", "Fusion", "Wildtype"), use toLower(Variant.name)
        CONTAINS toLower('<TOKEN>') together with VARIANT_OF to the gene.
    - Gene synonyms: allow equality on symbol OR equality on any synonyms (case-insensitive).
    - Therapy class: match via tags (case-insensitive contains) OR via TARGETS to the gene.
    - Disease filters: for umbrella terms (e.g., "lung cancer"), prefer case-insensitive
      CONTAINS on rel.disease_name; use equality only when the question names an exact disease.
    - Filter scoping: place WHERE filters that constrain (b)-[rel:AFFECTS_RESPONSE_TO]->(t)
      immediately after introducing those bindings. Do not attach such filters to OPTIONAL MATCH.
    - Do not assume the biomarker equals the therapy’s target gene unless explicitly named as the biomarker.
    """  # noqa: E501
).strip()

INSTRUCTION_PROMPT_TEMPLATE = dedent(
    """
    You are an oncology knowledge graph assistant.
    Produce concise guidance for a Cypher generator following the schema and
    canonical rules below.
    {schema}

    Task: Rewrite the user's question as 3–6 short bullet points that
    reference the schema labels, relationships, and property names. Keep guidance
    tumor‑agnostic unless a disease is explicitly named. Output only bullets
    starting with "- "; no Cypher and no JSON.

    Important: If only an amino‑acid token (e.g., "G12C") appears in the
    question, do NOT write equality on Variant.name or Variant.hgvs_p to that
    bare token. Instead, reference the guarded token‑handling pattern from the
    canonical rules (VARIANT_OF + name CONTAINS + hgvs_p 'p.<TOKEN>' or CONTAINS
    + synonyms CONTAINS). If a full variant name (e.g., "KRAS G12C") appears,
    prefer exact equality on Variant.name together with the VARIANT_OF guard.

    User question: {question}
    """
).strip()

CYPHER_PROMPT_TEMPLATE = dedent(
    """
    You are generating a single Cypher query for the oncology knowledge graph
    described below.
    {schema}

    Follow these requirements:
    - Use the instruction text exactly once to decide filters, MATCH clauses,
      and RETURN columns.
    - Produce a single Cypher query only (no commentary or fences).
    - Include a RETURN clause and a LIMIT.
    - Follow the canonical rules above (gene‑or‑variant, VARIANT_OF for variants,
      therapy class via tags or TARGETS, case-insensitive disease equality,
      filter scoping, and no parameters).
    - For tokenized variants (e.g., "G12C") or alteration classes ("Amplification",
      "Overexpression", "Deletion", "Loss-of-function", "Fusion", "Wildtype"),
      prefer equality on Variant.name when a full name is known, otherwise use
      toLower(Variant.name) CONTAINS toLower('<TOKEN>') together with VARIANT_OF.
    - For fusions ("EML4-ALK", "EML4::ALK"), match both orientations in Variant.name.
    - Do NOT use parameters (no $variables); inline single-quoted literals from
      the instruction text.
    - The RETURN clause MUST project these aliases in order:
      variant_name, gene_symbol, therapy_name, effect, disease_name, pmids.
      Use CASE and COALESCE so columns always exist (pmids must be an array,
      default []).

    Instruction text:
    {instructions}
    """
).strip()


SUMMARY_PROMPT_TEMPLATE = dedent(
    """
    You are summarizing query results from an oncology knowledge graph.

    Original question:
    {question}

    Result rows:
    {rows}

    Produce a concise answer in 2-5 sentences. Cite PubMed IDs (PMIDs) inline when available.
    If there are no rows, explicitly state that no evidence was found. Do not invent data.
    """
).strip()
