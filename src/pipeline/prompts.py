from textwrap import dedent

SCHEMA_SNIPPET = dedent(
    """
    Graph schema (condensed):
    - Labels: Gene(symbol),
      Variant(name),
      Therapy(name, modality, tags, chembl_id, synonyms),
      Disease(name, doid, synonyms)
    - Helper label: Biomarker (applied to Gene and Variant)
    - Relationships:
      (Variant)-[:VARIANT_OF]->(Gene)
      (Therapy)-[:TARGETS {{source, moa?, ref_sources?, ref_ids?, ref_urls?}}]->(Gene)
      (Biomarker)-[:AFFECTS_RESPONSE_TO {{effect, disease_name, disease_id?,
        pmids (array of strings), best_evidence_level? (string, A-E), evidence_levels? (array of strings),
        evidence_count? (integer), avg_rating? (float), max_rating? (integer)}}]->(Therapy)
    - Array properties: pmids, tags, synonyms, ref_sources, ref_ids, ref_urls, evidence_levels
    - No parameters: inline single-quoted literals only (no $variables)

    Preferred return columns (choose minimally sufficient for the question):
    - AFFECTS queries (predictive evidence): project
      variant_name, gene_symbol, therapy_name, effect, disease_name, pmids,
      best_evidence_level, evidence_levels, evidence_count, avg_rating, max_rating.
      Always include pmids as an array; default to [] when absent.
      Include best_evidence_level (string, A-E), evidence_levels (array), evidence_count (integer),
      avg_rating (float, nullable), max_rating (integer, nullable) to describe evidence quality.
    - Gene-only AFFECTS queries ("Which genes..."):
      set variant_name = NULL, return gene_symbol, therapy_name, effect,
      disease_name, pmids, best_evidence_level, evidence_levels, evidence_count, avg_rating, max_rating,
      and de-duplicate by gene_symbol, therapy_name, disease_name. Aggregate pmids across
      evidence rows into a single array. For aggregated metrics, collect relationships per tuple
      and compute summary values (best best_evidence_level, sum evidence_count, average avg_rating, max max_rating),
      and aggregate evidence_levels across relationships (deduplicate tokens).
    - TARGETS queries (mechanism/targeting): project
      gene_symbol, therapy_name, r.moa AS targets_moa. Include
      r.ref_sources, r.ref_ids, r.ref_urls for transparency.
    - Always include therapy_name and at least one of gene_symbol or variant_name
      for queries that involve therapies (AFFECTS or TARGETS). For simple
      variant lookup queries, return only variant_name and gene_symbol.

    Always include evidence where applicable:
    - For AFFECTS queries, use rel.pmids (coalesce to []), rel.best_evidence_level (string),
      rel.evidence_levels (coalesce to []), rel.evidence_count (integer), rel.avg_rating (float, nullable),
      rel.max_rating (integer, nullable). These are pre-aggregated summary metrics on each relationship.
    - For gene-only AFFECTS, aggregate pmids across all relationships for each gene–therapy–disease tuple.
      For evidence metrics, collect relationships per tuple and compute summaries: best best_evidence_level
      (minimum A-E order), sum evidence_count, average avg_rating, maximum max_rating, and deduplicate evidence_levels.
    - For TARGETS queries, include r.moa AS targets_moa and the reference arrays
      (r.ref_sources, r.ref_ids, r.ref_urls); do not derive pmids for TARGETS from other sources.

    Canonical example (AFFECTS; gene-only aggregation; adapt values):
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
        rel
      WHERE gene_symbol IS NOT NULL
      WITH gene_symbol, therapy_name, disease_name,
           collect(coalesce(rel.pmids, [])) AS pmid_groups,
           collect(coalesce(rel.evidence_levels, [])) AS level_groups,
           collect(rel.best_evidence_level) AS best_levels_raw,
           collect(coalesce(rel.evidence_count, 0)) AS count_values,
           collect(rel.avg_rating) AS avg_values_raw,
           collect(rel.max_rating) AS max_values_raw
      WITH gene_symbol, therapy_name, disease_name,
           pmid_groups,
           level_groups,
           [lvl IN best_levels_raw
              WHERE lvl IS NOT NULL AND lvl <> ''
              | lvl] AS best_levels,
           count_values,
           [value IN avg_values_raw
              WHERE value IS NOT NULL
              | value] AS avg_values,
           [value IN max_values_raw
              WHERE value IS NOT NULL
              | value] AS max_values
      WITH gene_symbol, therapy_name, disease_name,
           reduce(pmid_flat = [], group IN pmid_groups | pmid_flat + group) AS pmids_flat,
           reduce(level_flat = [], group IN level_groups | level_flat + group) AS levels_flat,
           best_levels,
           count_values,
           avg_values,
           max_values
      WITH gene_symbol, therapy_name, disease_name,
           reduce(unique_pmids = [], p IN pmids_flat
             | CASE WHEN p IN unique_pmids THEN unique_pmids ELSE unique_pmids + p END) AS pmids,
           reduce(unique_levels = [], lvl IN levels_flat
             | CASE WHEN lvl IN unique_levels THEN unique_levels ELSE unique_levels + lvl END) AS evidence_levels,
           best_levels,
           count_values,
           avg_values,
           max_values
      WITH gene_symbol, therapy_name, disease_name, pmids, evidence_levels,
           CASE
             WHEN size(best_levels) = 0 THEN ''
             WHEN size(best_levels) = 1 THEN head(best_levels)
             ELSE reduce(best = head(best_levels), lvl IN tail(best_levels)
                    | CASE WHEN lvl < best THEN lvl ELSE best END)
           END AS best_evidence_level,
           reduce(total = 0, value IN count_values | total + value) AS evidence_count,
           CASE
             WHEN size(avg_values) = 0 THEN NULL
             ELSE toFloat(reduce(sum_val = 0.0, value IN avg_values | sum_val + value)) / size(avg_values)
           END AS avg_rating,
           CASE
             WHEN size(max_values) = 0 THEN NULL
             WHEN size(max_values) = 1 THEN head(max_values)
             ELSE reduce(max_val = head(max_values), value IN tail(max_values)
                    | CASE WHEN value > max_val THEN value ELSE max_val END)
           END AS max_rating
      RETURN
        NULL AS variant_name,
        gene_symbol,
        therapy_name,
        'resistance' AS effect,
        disease_name,
        pmids,
        best_evidence_level,
        evidence_levels,
        evidence_count,
        avg_rating,
        max_rating
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
        CASE WHEN b:Variant THEN b.name END AS variant_name,
        CASE WHEN b:Gene THEN b.symbol ELSE g.symbol END AS gene_symbol,
        t.name AS therapy_name,
        rel.effect AS effect,
        rel.disease_name AS disease_name,
        coalesce(rel.pmids, []) AS pmids,
        coalesce(rel.best_evidence_level, '') AS best_evidence_level,
        coalesce(rel.evidence_levels, []) AS evidence_levels,
        coalesce(rel.evidence_count, 0) AS evidence_count,
        rel.avg_rating AS avg_rating,
        rel.max_rating AS max_rating
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
        coalesce(rel.pmids, []) AS pmids,
        coalesce(rel.best_evidence_level, '') AS best_evidence_level,
        coalesce(rel.evidence_levels, []) AS evidence_levels,
        coalesce(rel.evidence_count, 0) AS evidence_count,
        rel.avg_rating AS avg_rating,
        rel.max_rating AS max_rating
      LIMIT 100

    Canonical rules:
    - Case sensitivity: ALWAYS use toLower() for all string comparisons.
    - Granularity:
      • If question asks for "genes", "biomarkers", or "targets" (general):
        Collapse to GENE level. Return variant_name = NULL. Group by gene_symbol, therapy_name,
        disease_name. Aggregate metrics across all variants for that gene.
      • If question asks for "variants", "mutations", "fusions", or specific alterations:
        Keep VARIANT level. Return variant_name from the variant node.
    - Aggregation logic (for Gene-level grouping):
      • best_evidence_level: use min(rel.best_evidence_level) (exploit 'A' < 'B').
      • evidence_count: use sum(rel.evidence_count).
      • avg_rating: use avg(rel.avg_rating).
      • pmids: flatten using reduce(s=[], p IN collect(rel.pmids) | s + p).
    - Sorting (AFFECTS queries only):
      • ALWAYS sort results by quality: ORDER BY best_evidence_level ASC, evidence_count DESC.
      • Apply LIMIT 100 only AFTER sorting.
    - Case sensitivity: ALWAYS use toLower() for all string comparisons (gene symbols,
      synonyms, therapy names, disease names, effects, variant names). Never compare strings directly
      without toLower() as database values may vary in case.
    - Gene-only: match biomarker as the Gene OR any Variant VARIANT_OF that Gene.
      For gene-only questions, collapse to gene-level in the RETURN:
        • return NULL AS variant_name,
        • return gene_symbol (from b:Gene or via VARIANT_OF),
        • de-duplicate by gene_symbol, therapy_name, disease_name,
        • aggregate pmids across relationships: use UNWIND pmids AS p, then
          collect(DISTINCT p) AS pmids to ensure no duplicates.
        • aggregate evidence metrics: collect relationships per tuple, then compute
          best_evidence_level (minimum A-E), sum evidence_count, average avg_rating,
          maximum max_rating. See canonical example for aggregation pattern.
    - Specific variant:
      - Always require VARIANT_OF to the named gene.
      - Prefer equality on Variant.name for full names like 'KRAS G12C' or
        'BCR::ABL1 Fusion'. Fallback to toLower(Variant.name) CONTAINS
        toLower('<TOKEN>') or synonyms equality via
        any(s IN coalesce(v.synonyms, []) WHERE toLower(s) = toLower('<TOKEN>')).
      - For bare amino-acid tokens (e.g., 'G12C') that appear without a full variant
        name, NEVER set Variant.name equal to that token; instead, require VARIANT_OF
        to the gene and use toLower(Variant.name) CONTAINS toLower('<TOKEN>') or
        synonyms equality via any(s IN coalesce(v.synonyms, []) WHERE toLower(s) = toLower('<TOKEN>')).
      - For fusion tokens (e.g., 'EML4-ALK', 'EML4::ALK'), match either orientation in
        Variant.name using the '::' separator only:
        toLower(Variant.name) CONTAINS toLower('EML4::ALK') OR
        toLower(Variant.name) CONTAINS toLower('ALK::EML4').
      - For alteration-class tokens ('Amplification', 'Overexpression',
        'Deletion', 'Loss-of-function', 'Fusion', 'Wildtype'), use
        toLower(Variant.name) CONTAINS toLower('<TOKEN>') together with VARIANT_OF.
      - Ignore Variant.hgvs_p entirely for matching; do not use it in WHERE clauses.
    - Gene synonyms: ALWAYS use case-insensitive matching with toLower():
      toLower(g.symbol) = toLower('<SYMBOL>') OR
      any(s IN coalesce(g.synonyms, []) WHERE toLower(s) = toLower('<SYMBOL>')).
    - Therapy class: match via tags (case-insensitive contains) OR via TARGETS to the gene.
    - Therapy name: when a specific therapy is named, ALWAYS use case-insensitive equality
      with toLower(t.name); allow fallbacks to synonyms equality (case-insensitive) or
      toLower(t.name) CONTAINS when needed.
    - Disease filters: CRITICAL - Extract individual tokens from disease names and match
      each token separately using separate CONTAINS clauses combined with AND.
      For "Non-small Cell Lung Carcinoma", use:
        toLower(rel.disease_name) CONTAINS toLower('lung') AND
        toLower(rel.disease_name) CONTAINS toLower('non-small') AND
        toLower(rel.disease_name) CONTAINS toLower('cell')
      and you may optionally include toLower(rel.disease_name) CONTAINS toLower('carcinoma')
      as an additional token. NEVER use phrase matching like CONTAINS 'non-small cell lung'
      as this will fail. IMPORTANT: When users mention generic disease type terms like "cancer",
      the database may use alternative terminology (e.g., "carcinoma", "tumor", "neoplasm").
      To maximize recall, typically EXCLUDE generic disease type terms ("cancer", "carcinoma",
      "tumor", "neoplasm") from token extraction when more specific anatomical/organ tokens
      or disease-specific modifiers are available. For example, for "Non-small cell lung cancer",
      extract only: 'lung', 'non-small', 'cell' (exclude 'cancer' since the database may use
      "Lung Non-small Cell Carcinoma"). For umbrella terms (e.g., "lung cancer"), prefer a
      minimal anchor token match on rel.disease_name (case-insensitive), e.g.,
      toLower(rel.disease_name) CONTAINS toLower('lung').
    - Exclusion patterns: When query asks for "therapies targeting G1 excluding G2", use:
      MATCH (t:Therapy)-[:TARGETS]->(gi:Gene) WHERE gi matches G1,
      OPTIONAL MATCH (t)-[:TARGETS]->(gx:Gene) WHERE gx matches G2,
      WITH t, gi, gx WHERE gx IS NULL (therapy does NOT target excluded gene).
      Then continue with biomarker matching. Never use NOT t.name = 'G2' as G2 is a gene,
      not a therapy name.
    - Return columns: Always match return columns to the query type's standard schema.
      For AFFECTS queries, ALWAYS return the complete schema: variant_name (set to NULL for
      gene-only queries), gene_symbol, therapy_name, effect, disease_name, pmids,
      best_evidence_level, evidence_levels, evidence_count, avg_rating, max_rating.
      For TARGETS queries, return: gene_symbol, therapy_name, targets_moa, ref_sources/ref_ids/ref_urls.
      For simple variant lookups, return only variant_name and gene_symbol.
      IMPORTANT: Include all standard schema fields for the query type, even if some are NULL.
      Do NOT add NULL columns from other query types (e.g., don't add targets_moa to AFFECTS queries).
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
    Produce concise guidance for a Cypher generator using the schema and canonical rules below.
    {schema}

    Task:
    - Rewrite the user's question as 3–6 short bullet points that reference the schema labels,
      relationships, and property names.
    - Keep guidance tumor-agnostic unless a disease is explicitly named.
    - Output only bullets starting with "- "; no Cypher and no JSON.

    Use the canonical rules from the schema rather than redefining them:
    - Indicate whether the query is about predictive biomarkers (AFFECTS), therapeutic targets or
      mechanisms of action (TARGETS), or simple variant lookup, and rely on the corresponding
      result schemas and evidence fields already defined.
    - Respect the gene-versus-variant granularity rules (when to collapse to gene level vs keep
      variant detail), and make clear when aggregation of pmids and evidence metrics is expected.
    - When diseases, therapies, variants, or fusions are mentioned, rely on the schema's matching
      and tokenization patterns (including handling of bare amino-acid tokens and fusions) instead
      of inventing new ones.
    - When evidence strength or ranking matters, point to the evidence metrics and sorting behavior
      from the schema (best_evidence_level, evidence_count, avg_rating, max_rating) without restating
      the full logic.

    User question: {question}
    """
).strip()

CYPHER_PROMPT_TEMPLATE = dedent(
    """
    You are generating a single Cypher query for the oncology knowledge graph
    described below.
    {schema}

    You will receive high-level instruction text that already encodes the user's intent
    in terms of this schema.

    Requirements:
    - Use the instruction text exactly once; do not reinterpret the original user question directly.
    - Implement the instruction text by applying the canonical rules from the schema for:
      • choosing between AFFECTS, TARGETS, or simple variant lookup and their standard result schemas,
      • evidence fields and aggregation behavior (including gene-level collapsing),
      • gene-versus-variant granularity,
      • disease tokenization and filtering,
      • matching of genes, variants, therapies, and fusions,
      • sorting and LIMIT behavior.
    - Use inline single-quoted literals only (no Cypher parameters like $var).
    - Use case-insensitive string comparisons with toLower(), and wrap array properties
      (e.g., synonyms, tags, reference arrays) with coalesce(..., []) before any()/all() checks.
    - Keep the query pattern simple: prefer MATCH / OPTIONAL MATCH, WHERE, UNWIND, WITH, RETURN,
      and always include a RETURN clause and LIMIT 100.

    Output:
    - Output a single Cypher query only, with no commentary, explanation, or code fences.
    - The projected columns must match the standard schema for the detected query type
      (AFFECTS, gene-level AFFECTS, TARGETS, or simple variant lookup) as defined in the schema,
      and the query must include LIMIT 100.

    Instruction text:
    {instructions}
    """
).strip()


SUMMARY_PROMPT_TEMPLATE = dedent(
    """
    You are an expert oncology research assistant summarizing results from a clinical knowledge graph. Your goal is to provide a concise, ranked, and scannable answer based strictly on the provided data rows.

    Original Question:
    {question}

    Data Rows:
    {rows}

    ### Instructions for Summarization:

    1.  **Direct Answer First:** Start with a 1-2 sentence direct answer to the user's question.
    2.  **Rank by Evidence Strength:**
        *   If rows contain `best_evidence_level`, **prioritize Level A/B** items. Group lower-confidence items (C/D/E) at the bottom or summarized together.
        *   Mention evidence metrics concisely in parentheses, e.g., "**KRAS** (Level A, 40 items)".
        *   Do NOT list every single PMID. Include only the top 2-3 distinct PMIDs per item to support the claim.
    3.  **Consolidate & Group:**
        *   If a gene/variant affects multiple therapies similarly (e.g., "Resistant to Cetuximab and Panitumumab"), combine them into one bullet point rather than repeating the gene.
        *   If listing targets (`TARGETS` relationship), group by Mechanism of Action (MOA) if available.
    4.  **Format:**
        *   Use **bold** for key entities (Genes, Therapies, Diseases).
        *   Use bullet points for readability.
        *   Avoid large blocks of text.
    5.  **Constraints:**
        *   If no rows are returned, state: "No evidence found in the current knowledge graph."
        *   Do not invent data or external knowledge not present in rows.
        *   If there are too many rows, focus on the most important ones and omit the rest with a comment.

    ### Example Output Style:

    *   **KRAS** (Level A, 40 items): Strongest predictor of resistance to **Cetuximab** and **Panitumumab**. [PMID:20619739, PMID:19603018]
    *   **NRAS** (Level A, 14 items): Validated resistance marker. [PMID:20619739]
    *   **BRAF**, **PIK3CA**, **PTEN** (Level B): Clinical evidence suggests resistance.
    *   **EGFR**, **ERBB3** (Level C/D): Weaker or preclinical evidence found.
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
      - (Biomarker)-[:AFFECTS_RESPONSE_TO {{effect, disease_name, pmids,
        best_evidence_level, evidence_levels, evidence_count, avg_rating, max_rating}}]->(Therapy)
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
