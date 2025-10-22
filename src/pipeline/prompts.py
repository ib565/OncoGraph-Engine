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
      (Therapy)-[:TARGETS {source, moa?, action_type?, ref_sources?, ref_ids?, ref_urls?}]->(Gene)
      (Biomarker)-[:AFFECTS_RESPONSE_TO {effect, disease_name, disease_id?,
        pmids, source, notes?}]->(Therapy)
    - Array properties: pmids, tags
    - No parameters: inline single-quoted literals only
      (no $variables)
    
    Preferred return columns (choose minimally sufficient for the question):
    - AFFECTS queries (predictive evidence): project
      variant_name, gene_symbol, therapy_name, effect, disease_name, pmids.
    - TARGETS queries (mechanism/targeting): project
      gene_symbol, therapy_name, r.moa AS targets_moa (if available), and
      r.ref_sources, r.ref_ids, r.ref_urls. Optionally also derive pmids from
      reference source/ids.
    - Always include therapy_name and at least one of gene_symbol or variant_name.
    - For mixed queries, set missing columns to NULL; include pmids only when
      available (AFFECTS) or derived from references.

    Canonical example (AFFECTS; adapt values as needed):
      MATCH (b:Biomarker)-[rel:AFFECTS_RESPONSE_TO]->(t:Therapy)
      WHERE (
        any(tag IN t.tags WHERE toLower(tag) CONTAINS toLower('anti-EGFR'))
        OR (t)-[:TARGETS]->(:Gene {symbol: 'EGFR'})
      )
      AND rel.effect = 'resistance'
      AND toLower(rel.disease_name) CONTAINS toLower('colorectal')
      OPTIONAL MATCH (b)-[:VARIANT_OF]->(g:Gene)
      RETURN
        CASE WHEN b:Variant THEN coalesce(b.name, b.hgvs_p) END AS variant_name,
        CASE WHEN b:Gene THEN b.symbol ELSE g.symbol END AS gene_symbol,
        t.name AS therapy_name,
        rel.effect AS effect,
        rel.disease_name AS disease_name,
        coalesce(rel.pmids, []) AS pmids
      LIMIT 10

    Canonical example (TARGETS; adapt values as needed):
      MATCH (t:Therapy)-[r:TARGETS]->(g:Gene)
      WHERE toLower(g.symbol) = toLower('KRAS')
      WITH t, g, r,
        CASE
          WHEN r.ref_sources IS NULL OR r.ref_ids IS NULL THEN []
          ELSE [i IN range(0, size(r.ref_sources) - 1)
                WHERE toLower(r.ref_sources[i]) CONTAINS 'pubmed' OR toLower(r.ref_sources[i]) = 'pmid'
                | r.ref_ids[i]]
        END AS pmids
      RETURN
        NULL AS variant_name,
        g.symbol AS gene_symbol,
        t.name AS therapy_name,
        NULL AS effect,
        NULL AS disease_name,
        pmids,
        r.moa AS targets_moa,
        coalesce(r.ref_sources, []) AS ref_sources,
        coalesce(r.ref_ids, []) AS ref_ids,
        coalesce(r.ref_urls, []) AS ref_urls
      LIMIT 20

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
    - Therapy name: when a specific therapy is named, prefer case-insensitive equality on
      t.name; allow fallbacks to synonyms equality (case-insensitive) or toLower(t.name)
      CONTAINS when needed.
    - Disease filters: for umbrella terms (e.g., "lung cancer"), prefer a single minimal
      anchor token match on rel.disease_name (case-insensitive), e.g.,
      toLower(rel.disease_name) CONTAINS toLower('lung'). Avoid requiring additional tokens
      like 'cancer'/'carcinoma' to maximize recall. Use case-insensitive equality only when
      the question names a specific disease entity.
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

    - When the question uses an umbrella disease term (e.g., "lung cancer"), include a
      bullet instructing minimal anchor filtering: require only 'lung' (case‑insensitive)
      to appear in rel.disease_name. Do not require 'cancer'/'carcinoma' to maximize recall.
    - When a therapy is explicitly named, include a bullet to match Therapy by
      case‑insensitive name equality and allow synonyms/CONTAINS as fallbacks.
    - When the question asks which therapies target a gene or requests mechanisms of
      action (MOA), include a bullet to match (t:Therapy)-[r:TARGETS]->(g:Gene) for the
      gene (consider synonyms) and to project r.moa AS targets_moa.

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
    - Return the minimally sufficient set of columns for the question:
      • For AFFECTS queries, project variant_name, gene_symbol, therapy_name, effect,
        disease_name, pmids (pmids must be an array; default []).
      • For TARGETS queries, project gene_symbol, therapy_name, r.moa AS targets_moa.
      • Always include therapy_name and at least one of variant_name or gene_symbol.
      • When mixing patterns, set missing columns to NULL (and pmids to []) for stability.
    - Prefer case-insensitive equality for exact entity names (Variant.name,
      Therapy.name, Gene.symbol). Include robust fallbacks where appropriate:
        • Variant: equality on full name; OR name CONTAINS token; OR hgvs_p equality
          to 'p.<TOKEN>'; OR synonyms CONTAINS token; always guard with VARIANT_OF
          to the gene when variant-specific.
        • Therapy: equality on t.name; OR synonyms equality; OR toLower(t.name) CONTAINS.
        • Disease (umbrella terms): minimal anchor filtering as described above
          (e.g., toLower(rel.disease_name) CONTAINS toLower('lung')); otherwise use
          case-insensitive equality for specific diseases.

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

    Produce a concise answer in clear bullet points. Include mechanisms of action when
    provided (e.g., targets_moa). Cite PubMed IDs (PMIDs) inline when available.
    If there are rows irrelevant to the question, exclude them from the answer.
    If there are no rows, explicitly state that no evidence was found. Do not invent data.
    """
).strip()

ENRICHMENT_SUMMARY_PROMPT_TEMPLATE = dedent(
    """
    You are analyzing gene enrichment results to provide biological insights and suggest follow-up questions.

    Gene list analyzed: {gene_list}

    Enrichment results:
    {enrichment_results}

    Provide a clear, concise summary of the top biological themes revealed by this gene list.
    Focus on the most significant pathways and processes (top 3-5 terms by statistical significance).
    Explain what these enriched terms suggest about the biological function or disease relevance
    of the gene set. Use plain language accessible to researchers and clinicians.

    Format your response as:
    1. A brief overview of what the analysis reveals
    2. Key biological themes (bullet points for top pathways/processes)
    3. Clinical or research implications if apparent

    If no significant enrichments were found, explain what this might indicate about the gene list.

    Additionally, suggest 1-3 follow-up questions that:
    - Are answerable using the OncoGraph knowledge graph (genes, variants, therapies, diseases, biomarkers)
    - Help researchers explore therapeutic implications or resistance mechanisms
    - Reference specific genes, pathways, or disease contexts from the analysis
    - Focus on actionable research questions that could be investigated using the knowledge graph

    Examples of good follow-up questions:
    - "What therapies target [specific gene] in [disease context]?"
    - "What resistance mechanisms are known for [pathway] inhibitors?"
    - "Which biomarkers predict response to [therapy class] in [cancer type]?"

    Return your response as JSON with the following structure:
    {{
        "summary": "Your detailed biological summary here...",
        "followUpQuestions": ["Question 1", "Question 2", "Question 3"]
    }}
    """
).strip()
