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
      (Therapy)-[:TARGETS {{source, moa?, action_type?, ref_sources?, ref_ids?, ref_urls?}}]->(Gene)
      (Biomarker)-[:AFFECTS_RESPONSE_TO {{effect, disease_name, disease_id?,
        pmids, source, notes?}}]->(Therapy)
    - Array properties: pmids, tags
    - No parameters: inline single-quoted literals only
      (no $variables)
    
    Preferred return columns (choose minimally sufficient for the question):
    - AFFECTS queries (predictive evidence): project
      variant_name, gene_symbol, therapy_name, effect, disease_name, pmids.
      Always include pmids as an array; default to [] when absent.
    - Gene-only AFFECTS queries ("Which genes..."):
      set variant_name = NULL, return gene_symbol, therapy_name, effect,
      disease_name, pmids, and de-duplicate by gene_symbol, therapy_name,
      disease_name. Aggregate pmids across evidence rows into a single array.
    - TARGETS queries (mechanism/targeting): project
      gene_symbol, therapy_name, r.moa AS targets_moa. Include
      r.ref_sources, r.ref_ids, r.ref_urls for transparency.
    - Always include therapy_name and at least one of gene_symbol or variant_name.
    - For mixed queries, set missing columns to NULL; include pmids only when
      available (AFFECTS) or derived from references (TARGETS).

    Always include evidence (pmids) where applicable:
    - For AFFECTS queries, use rel.pmids (coalesce to []).
    - For gene-only AFFECTS, aggregate pmids across all evidence rows that
      contribute to a gene–therapy–disease tuple.
    - For TARGETS queries, include reference arrays (r.ref_sources, r.ref_ids,
      r.ref_urls) if present.

    Canonical example (AFFECTS; gene-only with pmid aggregation; adapt values):
      MATCH (b:Biomarker)-[rel:AFFECTS_RESPONSE_TO]->(t:Therapy)
      WHERE (
        toLower(t.name) = toLower('cetuximab')
        OR toLower(t.name) = toLower('panitumumab')
        OR any(s IN coalesce(t.synonyms, [])
               WHERE toLower(s) = toLower('cetuximab'))
        OR any(s IN coalesce(t.synonyms, [])
               WHERE toLower(s) = toLower('panitumumab'))
        OR toLower(t.name) CONTAINS toLower('cetuximab')
        OR toLower(t.name) CONTAINS toLower('panitumumab')
      )
      AND toLower(rel.effect) = 'resistance'
      AND toLower(rel.disease_name) CONTAINS toLower('colorectal')
      OPTIONAL MATCH (b)-[:VARIANT_OF]->(g:Gene)
      WITH
        CASE WHEN b:Gene THEN b.symbol ELSE g.symbol END AS gene_symbol,
        t.name AS therapy_name,
        rel.disease_name AS disease_name,
        coalesce(rel.pmids, []) AS pmids
      WHERE gene_symbol IS NOT NULL
      UNWIND pmids AS p
      WITH gene_symbol, therapy_name, disease_name, collect(DISTINCT p) AS pmids
      RETURN
        NULL AS variant_name,
        gene_symbol,
        therapy_name,
        'resistance' AS effect,
        disease_name,
        pmids
      LIMIT 100

    Canonical example (AFFECTS; adapt values as needed):
      MATCH (b:Biomarker)-[rel:AFFECTS_RESPONSE_TO]->(t:Therapy)
      WHERE (
        any(tag IN coalesce(t.tags, [])
            WHERE toLower(tag) CONTAINS toLower('anti-EGFR'))
        OR (t)-[:TARGETS]->(:Gene {{symbol: 'EGFR'}})
      )
      AND toLower(rel.effect) = 'resistance'
      AND toLower(rel.disease_name) CONTAINS toLower('colorectal')
      OPTIONAL MATCH (b)-[:VARIANT_OF]->(g:Gene)
      RETURN
        CASE WHEN b:Variant THEN coalesce(b.name, b.hgvs_p) END AS variant_name,
        CASE WHEN b:Gene THEN b.symbol ELSE g.symbol END AS gene_symbol,
        t.name AS therapy_name,
        rel.effect AS effect,
        rel.disease_name AS disease_name,
        coalesce(rel.pmids, []) AS pmids
      LIMIT 100

    Canonical example (TARGETS; adapt values as needed):
      MATCH (t:Therapy)-[r:TARGETS]->(g:Gene)
      WHERE toLower(g.symbol) = toLower('KRAS')
         OR any(s IN coalesce(g.synonyms, []) WHERE toLower(s) = toLower('KRAS'))
      RETURN
        NULL AS variant_name,
        g.symbol AS gene_symbol,
        t.name AS therapy_name,
        NULL AS effect,
        NULL AS disease_name,
        r.moa AS targets_moa,
        coalesce(r.ref_sources, []) AS ref_sources,
        coalesce(r.ref_ids, []) AS ref_ids,
        coalesce(r.ref_urls, []) AS ref_urls
      LIMIT 100

    Canonical example (Variant lookup; simple query):
      MATCH (v:Variant)-[:VARIANT_OF]->(g:Gene)
      WHERE toLower(g.symbol) = toLower('RRM1')
         OR any(s IN coalesce(g.synonyms, []) WHERE toLower(s) = toLower('RRM1'))
      RETURN v.name AS variant_name, g.symbol AS gene_symbol
      LIMIT 100

    Canonical example (Exclusion pattern: therapies targeting G1 but NOT G2 with evidence):
      MATCH (t:Therapy)-[:TARGETS]->(gi:Gene)
      WHERE toLower(gi.symbol) = toLower('G1')
         OR any(s IN coalesce(gi.synonyms, []) WHERE toLower(s) = toLower('G1'))
      OPTIONAL MATCH (t)-[:TARGETS]->(gx:Gene)
      WHERE toLower(gx.symbol) = toLower('G2')
         OR any(s IN coalesce(gx.synonyms, []) WHERE toLower(s) = toLower('G2'))
      WITH t, gi, gx
      WHERE gx IS NULL
      MATCH (b:Biomarker)-[rel:AFFECTS_RESPONSE_TO]->(t)
      WHERE toLower(rel.disease_name) CONTAINS toLower('disease')
      OPTIONAL MATCH (b)-[:VARIANT_OF]->(g:Gene)
      RETURN
        CASE WHEN b:Variant THEN b.name ELSE NULL END AS variant_name,
        CASE WHEN b:Gene THEN b.symbol ELSE g.symbol END AS gene_symbol,
        t.name AS therapy_name,
        rel.effect AS effect,
        rel.disease_name AS disease_name,
        coalesce(rel.pmids, []) AS pmids
      LIMIT 100

    Canonical rules:
    - Case sensitivity: ALWAYS use toLower() for all string comparisons (gene symbols,
      synonyms, therapy names, disease names, effects, variant names). Never compare
      strings directly without toLower() as database values may vary in case.
    - Gene-only: match biomarker as the Gene OR any Variant VARIANT_OF that Gene.
      For gene-only questions, collapse to gene-level in the RETURN:
        • return NULL AS variant_name,
        • return gene_symbol (from b:Gene or via VARIANT_OF),
        • de-duplicate by gene_symbol, therapy_name, disease_name,
        • aggregate pmids across evidence rows: use UNWIND pmids AS p, then
          collect(DISTINCT p) AS pmids to ensure no duplicates.
    - Specific variant:
      - Always require VARIANT_OF to the named gene.
      - Prefer equality on Variant.name for full names like 'KRAS G12C' or
        'BCR::ABL1 Fusion'. Fallback to toLower(Variant.name) CONTAINS
        toLower('<TOKEN>'), or hgvs_p = 'p.<TOKEN>', or synonyms CONTAINS.
      - For fusion tokens (e.g., 'EML4-ALK', 'EML4::ALK'), match either orientation:
        toLower(Variant.name) CONTAINS toLower('EML4::ALK') OR
        toLower(Variant.name) CONTAINS toLower('ALK::EML4').
      - For alteration-class tokens ('Amplification', 'Overexpression',
        'Deletion', 'Loss-of-function', 'Fusion', 'Wildtype'), use
        toLower(Variant.name) CONTAINS toLower('<TOKEN>') together with VARIANT_OF.
    - Gene synonyms: ALWAYS use case-insensitive matching with toLower():
      toLower(g.symbol) = toLower('<SYMBOL>') OR
      any(s IN coalesce(g.synonyms, []) WHERE toLower(s) = toLower('<SYMBOL>')).
    - Therapy class: match via tags (case-insensitive contains) OR via TARGETS to the gene.
    - Therapy name: when a specific therapy is named, ALWAYS use case-insensitive equality
      with toLower(t.name); allow fallbacks to synonyms equality (case-insensitive) or
      toLower(t.name) CONTAINS when needed.
    - Disease filters: CRITICAL - Extract individual tokens from disease names and match
      each token separately. For "Non-small Cell Lung Carcinoma", use separate CONTAINS
      clauses: toLower(rel.disease_name) CONTAINS toLower('lung') AND
      toLower(rel.disease_name) CONTAINS toLower('non-small') AND
      toLower(rel.disease_name) CONTAINS toLower('cell') AND
      toLower(rel.disease_name) CONTAINS toLower('carcinoma'). NEVER use phrase matching
      like CONTAINS 'non-small cell lung' as this will fail. For umbrella terms (e.g.,
      "lung cancer"), prefer a single minimal anchor token match on rel.disease_name
      (case-insensitive), e.g., toLower(rel.disease_name) CONTAINS toLower('lung').
      Avoid requiring additional tokens like 'cancer'/'carcinoma' to maximize recall.
    - Exclusion patterns: When query asks for "therapies targeting G1 excluding G2", use:
      MATCH (t:Therapy)-[:TARGETS]->(gi:Gene) WHERE gi matches G1,
      OPTIONAL MATCH (t)-[:TARGETS]->(gx:Gene) WHERE gx matches G2,
      WITH t, gi, gx WHERE gx IS NULL (therapy does NOT target excluded gene).
      Then continue with biomarker matching. Never use NOT t.name = 'G2' as G2 is a gene,
      not a therapy name.
    - Return columns: Return ONLY the columns needed for the question. For simple variant
      lookups (e.g., "What variants are known for gene X?"), return only variant_name and
      gene_symbol. Do NOT add unnecessary NULL columns (therapy_name, effect, disease_name,
      pmids) unless the query requires them. Always match return columns to query type:
      AFFECTS queries return variant_name, gene_symbol, therapy_name, effect, disease_name,
      pmids; TARGETS queries return gene_symbol, therapy_name, targets_moa, ref_sources.
    - Filter scoping: place WHERE filters that constrain (b)-[rel:AFFECTS_RESPONSE_TO]->(t)
      immediately after introducing those bindings. Do not attach such filters to OPTIONAL MATCH.
    - Effect filtering: ALWAYS compare case-insensitively: toLower(rel.effect) = 'resistance'
      or 'sensitivity'.
    - Array usage: wrap arrays with coalesce(..., []) before any()/all() checks.
    - Do not assume the biomarker equals the therapy's target gene unless explicitly named
      as the biomarker.
    - LIMIT: ALWAYS use LIMIT 100 for all queries. Never use a different limit value.
    """
).strip()

INSTRUCTION_PROMPT_TEMPLATE = dedent(
    """
    You are an oncology knowledge graph assistant.
    Produce concise guidance for a Cypher generator following the schema and
    canonical rules below.
    {schema}

    Task: Rewrite the user's question as 3–6 short bullet points that
    reference the schema labels, relationships, and property names. Keep guidance
    tumor-agnostic unless a disease is explicitly named. Output only bullets
    starting with "- "; no Cypher and no JSON.

    Always include evidence (PMIDs):
    - For AFFECTS queries, return pmids from rel.pmids (array; default []).
    - For gene-only AFFECTS questions, collapse to gene-level and aggregate pmids
      across evidence rows for each gene–therapy–disease tuple.
    - For TARGETS queries, derive pmids from r.ref_sources/r.ref_ids by selecting
      entries where the source contains 'pubmed' or equals 'pmid' (case-insensitive).

    - If the question asks for "genes" (no specific variant named), instruct to:
      • match (b:Gene) OR (b:Variant)-[:VARIANT_OF]->(g:Gene),
      • return gene_symbol only (set variant_name to NULL),
      • de-duplicate by gene_symbol, therapy_name, and disease_name,
      • aggregate pmids across evidence rows.

    - When checking array properties (e.g., synonyms, tags), wrap with coalesce(..., [])
      before using any()/all() to avoid nulls.
    - Compare effect case-insensitively with toLower(rel.effect).

    Important: If only an amino-acid token (e.g., "G12C") appears in the
    question, do NOT write equality on Variant.name or Variant.hgvs_p to that
    bare token. Instead, reference the guarded token-handling pattern from the
    canonical rules (VARIANT_OF + name CONTAINS + hgvs_p 'p.<TOKEN>' or CONTAINS
    + synonyms CONTAINS). If a full variant name (e.g., "KRAS G12C") appears,
    prefer exact equality on Variant.name together with the VARIANT_OF guard.

    - Disease tokenization: CRITICAL - When a disease is mentioned, extract individual
      tokens and require each token to appear separately. For "Non-small Cell Lung Carcinoma",
      instruct to match all tokens: 'lung', 'non-small', 'cell', 'carcinoma' using separate
      CONTAINS clauses with AND. NEVER use phrase matching like CONTAINS 'non-small cell lung'
      as this will fail. For umbrella terms (e.g., "lung cancer"), use minimal anchor filtering:
      require only 'lung' (case-insensitive) to appear in rel.disease_name. Do not require
      'cancer'/'carcinoma' to maximize recall.
    - Disease name awareness: Users may phrase diseases using alternative names, synonyms,
      or variant spellings (e.g., "Chronic Myelogenous Leukaemia" vs "Chronic Myeloid Leukemia",
      "NSCLC" vs "Non-small Cell Lung Carcinoma"). When a disease is mentioned, map the user's
      phrasing to canonical disease tokens for filtering. Use token-based matching with each
      token as a separate CONTAINS condition.
    - Case sensitivity: Always instruct to use toLower() for all string comparisons (gene
      symbols, synonyms, therapy names, disease names, effects).
    - When a therapy is explicitly named, include a bullet to match Therapy by
      case-insensitive name equality and allow synonyms/CONTAINS as fallbacks.
    - When the question asks which therapies target a gene or requests mechanisms of
      action (MOA), include a bullet to match (t:Therapy)-[r:TARGETS]->(g:Gene) for the
      gene (consider synonyms) and to project r.moa AS targets_moa. Include reference
      arrays (r.ref_sources, r.ref_ids, r.ref_urls) if present.

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
    - Include a RETURN clause and ALWAYS use LIMIT 100 (never a different limit).
    - Keep queries simple: prefer MATCH/OPTIONAL MATCH, WHERE, WITH, RETURN.
    - Follow the canonical rules above (gene‑or‑variant, VARIANT_OF for variants,
      therapy class via tags or TARGETS, case-insensitive disease handling,
      filter scoping, and no parameters).
    - Case sensitivity: ALWAYS use toLower() for ALL string comparisons (gene symbols,
      synonyms, therapy names, disease names, effects). Never compare strings directly.
    - For tokenized variants (e.g., "G12C") or alteration classes ("Amplification",
      "Overexpression", "Deletion", "Loss-of-function", "Fusion", "Wildtype"),
      prefer equality on Variant.name when a full name is known, otherwise use
      toLower(Variant.name) CONTAINS toLower('<TOKEN>') together with VARIANT_OF.
    - For fusions ("EML4-ALK", "EML4::ALK"), match both orientations in
      Variant.name.
    - Do NOT use parameters (no $variables); inline single-quoted literals from
      the instruction text.

    Always include evidence (pmids) where applicable:
    - For AFFECTS queries, project pmids from rel.pmids as an array
      (use coalesce(rel.pmids, [])).
    - If the question asks for genes (not variants), collapse evidence to the
      gene level: map Variant->Gene via VARIANT_OF, return NULL AS variant_name,
      de-duplicate rows by gene_symbol, therapy_name, disease_name, and aggregate
      pmids using UNWIND pmids AS p, then collect(DISTINCT p) AS pmids to ensure
      no duplicates.
    - For TARGETS queries, include reference arrays (r.ref_sources, r.ref_ids, r.ref_urls)
      if present.

    Return the minimally sufficient set of columns for the question:
    - Return ONLY the columns needed for the specific query type. Do NOT add
      unnecessary NULL columns for simple queries (e.g., variant lookup queries
      should return only variant_name and gene_symbol, not therapy_name, effect, etc.).
    - For AFFECTS queries, project variant_name, gene_symbol, therapy_name, effect,
      disease_name, pmids (pmids must be an array; default []).
    - For TARGETS queries, project gene_symbol, therapy_name, r.moa AS targets_moa,
      and include r.ref_sources, r.ref_ids, r.ref_urls.
    - For simple variant lookups (e.g., "What variants are known for gene X?"),
      return ONLY variant_name and gene_symbol.
    - Always include therapy_name and at least one of variant_name or gene_symbol
      ONLY when the query involves therapies (AFFECTS or TARGETS patterns).
    - When mixing patterns, set missing columns to NULL (and pmids to []) for
      stability.

    Robust fallbacks:
    - Variant: equality on full name; OR name CONTAINS token; OR hgvs_p equality
      to 'p.<TOKEN>'; OR synonyms CONTAINS token; always guard with VARIANT_OF
      to the gene when variant-specific. Always use toLower() for case-insensitive matching.
    - Gene matching: ALWAYS use toLower(g.symbol) = toLower('<SYMBOL>') OR
      any(s IN coalesce(g.synonyms, []) WHERE toLower(s) = toLower('<SYMBOL>'))
      for case-insensitive matching. Never compare gene symbols directly.
    - Therapy: ALWAYS use case-insensitive matching: toLower(t.name) = toLower('<NAME>');
      OR synonyms equality with toLower(); OR toLower(t.name) CONTAINS; wrap arrays
      with coalesce(..., []).
    - Disease filtering: CRITICAL - Extract individual tokens from disease names and
      match each token separately with AND conditions. For "Non-small Cell Lung Carcinoma",
      use: toLower(rel.disease_name) CONTAINS toLower('lung') AND
      toLower(rel.disease_name) CONTAINS toLower('non-small') AND
      toLower(rel.disease_name) CONTAINS toLower('cell') AND
      toLower(rel.disease_name) CONTAINS toLower('carcinoma'). NEVER use phrase matching
      like CONTAINS 'non-small cell lung' as this will fail to match. Users may phrase
      diseases using alternative names, synonyms, or variant spellings. Map the user's
      phrasing to canonical disease tokens for filtering. For umbrella terms (e.g.,
      "lung cancer"), use minimal anchor filtering (e.g., toLower(rel.disease_name)
      CONTAINS toLower('lung')).
    - Exclusion patterns: When excluding a gene (e.g., "targeting G1 excluding G2"),
      use OPTIONAL MATCH to check for the excluded gene: OPTIONAL MATCH (t)-[:TARGETS]->(gx:Gene)
      WHERE toLower(gx.symbol) = toLower('G2'), then WITH t, gi, gx WHERE gx IS NULL.
      The excluded entity is a gene, not a therapy name.
    - Effect: ALWAYS compare case-insensitively: toLower(rel.effect) = 'resistance' or 'sensitivity'.
    - Arrays: when using any()/all() over arrays (e.g., synonyms, tags), wrap with
      coalesce(property, []) to avoid null issues.

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
    Use simple markdown formatting for the answer.
    """
).strip()

ENRICHMENT_SUMMARY_PROMPT_TEMPLATE = dedent(
    """
    You are an expert-level cancer biologist and data scientist. 
    Your task is to analyze gene enrichment results and provide a biological summary and 
    suggest actionable follow-up questions for a researcher using the OncoGraph knowledge graph.

    PART 1: Biological Summary
    Based on the provided gene list and enrichment results, write a clear, concise biological summary.

    - First, provide a brief overview of the analysis.
    - Then, identify 2-4 key biological themes in bullet points. 
    For each theme, explain its role in cancer (for example, cell growth, apoptosis, immune response).
    - Finally, comment on the potential clinical or research implications.
    - If no significant enrichments were found, explain what this might indicate.

    PART 2: Follow-up Questions

    Based on your biological summary, suggest 1-3 actionable and simple follow-up questions
    that can be answered using the OncoGraph knowledge graph.
    - The questions must be highly relevant to the biological themes you identified.
    - The questions should explore therapeutic options, biomarkers, or resistance mechanisms.
    - Refer to specific genes or pathways from the analysis.
    - It must be answerable using the graph schema. The OncoGraph has the following structure:
      Nodes:
      - Gene {{symbol, hgnc_id}}
      - Variant {{name, hgvs_p, consequence}}
      - Therapy {{name, modality, moa}}
      - Disease {{name}}
      Relationships:
      - (Variant)-[:VARIANT_OF]->(Gene)
      - (Therapy)-[:TARGETS {{action_type}}]->(Gene)
      - (Biomarker)-[:AFFECTS_RESPONSE_TO {{effect, disease_name, pmids}}]->(Therapy)
      Biomarker can be a Gene or a Variant.
      Effect can be 'Sensitivity' or 'Resistance'.

    Example follow-up questions:
    1.  "What therapies target the gene EGFR in Non-Small Cell Lung Cancer, and what is their mechanism of action?"
    2.  "For Colorectal Cancer, which variants in the KRAS gene are known to cause resistance to Cetuximab?"
    3.  "Which known biomarkers predict response to immunotherapy in Melanoma?"
    4.  "What is the known mechanism of action for therapies that target the BRAF gene?"

    Use simple markdown formatting for the summary.

    INPUT DATA:
    - Gene list size: {gene_list_count} genes
    - Top {top_n} Enrichment Results : {enrichment_results}

    OUTPUT FORMAT:
    Return your response as a single, valid JSON object with the following structure.
    {{
        "summary": "Your detailed biological summary here...",
        "followUpQuestions": ["Actionable Question 1", "Actionable Question 2", "Actionable Question 3"]
    }}
    """
).strip()
