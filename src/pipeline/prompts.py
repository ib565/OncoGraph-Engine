from textwrap import dedent

SCHEMA_SNIPPET = dedent(
    """
    Graph schema:
    - Node labels:
      Gene(symbol, hgnc_id, synonyms),
      Variant(name, hgvs_p, consequence, synonyms),
      Therapy(name, modality, tags, chembl_id, synonyms),
      Disease(name, doid, synonyms)
    - Helper label: Biomarker is applied to Gene and Variant nodes
    - Relationships:
      (Variant)-[:VARIANT_OF]->(Gene)
      (Therapy)-[:TARGETS {source}]->(Gene)
      (Biomarker)-[:AFFECTS_RESPONSE_TO {
        effect, disease_name, disease_id?, pmids, source, notes?
      }]->(Therapy)
    - Array properties: pmids, tags
    - Do NOT use Cypher parameters (no $variables). Inline single-quoted
      literal values derived from the user's question/instructions.
    Canonical row return contract:
    RETURN
      CASE WHEN biomarker:Variant
           THEN coalesce(biomarker.name, biomarker.hgvs_p)
      END AS variant_name,
      CASE WHEN biomarker:Gene
           THEN biomarker.symbol ELSE gene.symbol
      END AS gene_symbol,
      therapy.name                 AS therapy_name,
      rel.effect                   AS effect,
      rel.disease_name             AS disease_name,
      coalesce(rel.pmids, [])      AS pmids
    LIMIT …

    When writing Cypher, ensure the aliases
    variant_name, gene_symbol, therapy_name, effect, disease_name, pmids
    are always returned
    (use CASE/COALESCE so absent values become NULL or []).

    Query patterns (use when applicable):
    - Gene matching can use symbol OR synonyms (case-insensitive equality):
      MATCH (g:Gene)
      WHERE toLower(g.symbol) = toLower('KRAS')
         OR any(s IN g.synonyms WHERE toLower(s) = toLower('KRAS'))
    - Gene-or-Variant biomarker for generic "<gene> mutations"
      (prefer this simpler OR form):
      MATCH (b:Biomarker)-[r:AFFECTS_RESPONSE_TO]->(t:Therapy)
      WHERE (b:Gene AND toLower(b.symbol) = toLower('KRAS'))
         OR ((b:Variant)-[:VARIANT_OF]->(:Gene {symbol: 'KRAS'}))
      // If you still need to expand nodes, use this UNWIND form
      // (note the list-comprehension filter):
      MATCH (g:Gene {symbol: 'KRAS'})
      OPTIONAL MATCH (v:Variant)-[:VARIANT_OF]->(g)
      WITH g, v
      UNWIND [x IN [g, v] WHERE x IS NOT NULL] AS biomarker_node
      MATCH (biomarker_node:Biomarker)-[r:AFFECTS_RESPONSE_TO]->(t:Therapy)
    - Specific variant provided (e.g., "KRAS G12C", "BRAF V600E"):
      // Prefer exact full Variant.name when available, and always enforce
      // the gene via VARIANT_OF.
      MATCH (g:Gene {symbol: 'KRAS'})
      MATCH (v:Variant)-[:VARIANT_OF]->(g)
      WHERE toLower(v.name) = toLower('KRAS G12C')
         OR toLower(v.name) CONTAINS toLower('G12C')
         OR toLower(v.hgvs_p) = toLower('p.G12C')
         OR any(s IN v.synonyms WHERE toLower(s) CONTAINS toLower('G12C'))
      // Never match a bare amino-acid token like "G12C" using equality on
      // v.name or v.hgvs_p without the gene constraint; use the
      // VARIANT_OF guard + contains/hgvs/synonyms instead.
    - Therapy class by tags OR TARGETS (case-insensitive for tags):
      MATCH (t:Therapy)
      WHERE any(tag IN t.tags WHERE toLower(tag) CONTAINS toLower('anti-EGFR'))
         OR (t)-[:TARGETS]->(:Gene {symbol: 'EGFR'})
    - Disease comparisons should be case-insensitive equality; validator will normalize if needed.
    """
).strip()

INSTRUCTION_PROMPT_TEMPLATE = dedent(
    """
    You are an oncology knowledge graph assistant. 
    You provide clear instructions to guide the downstream Cypher generator
    in forming a valid Cypher query.
    {schema}

    Task: Rewrite the user's question as 3-6 short bullet points that reference
    the schema labels, relationships, and property names. Keep the guidance
    tumor-agnostic unless a disease is explicitly named. Do not produce Cypher
    or JSON—only plain-text bullet points starting with "- ".

    Guidance:
    - If the question mentions "<gene> mutations" without a specific variant,
      match the biomarker as the Gene OR any Variant VARIANT_OF that Gene.
    - If a specific variant is named (e.g., "KRAS G12C", "BRAF V600E"),
      constrain to the gene via VARIANT_OF and prefer exact full Variant.name
      matching when possible; otherwise, combine the gene constraint with
      case-insensitive matching across Variant.name, Variant.hgvs_p, and
      Variant.synonyms for the amino-acid change (e.g., "G12C").
    - Never match a bare amino-acid token (e.g., "G12C") using equality on
      Variant.name or Variant.hgvs_p without the gene constraint; use the
      robust pattern above.
    - For therapy classes like "anti-EGFR", match by tags OR by TARGETS to the target Gene.
    - Treat disease matching as case-insensitive equality.

    User question: {question}
    """
).strip()

CYPHER_PROMPT_TEMPLATE = dedent(
    """
    You are generating a single Cypher query for the oncology knowledge graph
    described below.
    {schema}

    Follow these requirements:
    - Use the provided instruction text exactly once to decide filters, MATCH
      clauses, and RETURN columns.
    - Produce a single Cypher query with no commentary or markdown fences.
    - Ensure the query includes a RETURN clause with readable column aliases
      and a LIMIT.
    - If the question names a gene without a specific variant, include
      biomarker matching for the Gene OR any Variant VARIANT_OF that Gene
      (prefer the OR form shown in the schema patterns; avoid placing WHERE
      immediately after UNWIND).
    - For therapy classes (e.g., "anti-EGFR"), allow matching via tags OR via
      TARGETS to the corresponding Gene.
    - Do NOT use Cypher parameters (no $variables). Inline single-quoted
      literal values taken from the instruction text.
    - The RETURN clause MUST project exactly these aliases in order:
      variant_name, gene_symbol, therapy_name, effect, disease_name, pmids.
      Use CASE expressions and COALESCE so the columns exist even when values
      are missing (pmids must always be an array, default to []).

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
