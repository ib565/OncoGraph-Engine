# OncoGraph Agent

**[Try the Live Demo Here](https://onco-graph-agent.vercel.app/)**

OncoGraph Agent is a sophisticated Q&A system that answers complex questions about cancer genomics by leveraging a knowledge graph. It translates natural language queries into Cypher, extracts precise information from the graph, and presents it with citations, providing a reliable tool for researchers and clinicians.

## Example

**Question:**
> Which therapies target KRAS and what are their mechanisms of action?

**Answer:**
> Here are therapies that target KRAS and their mechanisms of action:
>*   **Adagrasib**: functions as a GTPase KRas inhibitor (PMID: 31658955)
>*   **Salirasib**: acts as a RAS inhibitor (PMID: 22547163)
>*   **Sotorasib**: functions as a GTPase KRas inhibitor (PMIDs: 31189530, 31666701, 31820981, 32568546)


![Mini-graph Visualization](docs\example.png)

### More Example Questions

- Which therapies target KRAS and what are their mechanisms of action?
- What biomarkers predict resistance to anti-EGFR therapies in colorectal cancer?
- Find PubMed citations related to Sotorasib’s mechanism of action on KRAS.
- What is the predicted response of EGFR L858R to Gefitinib in lung cancer?

## Key Features

- **Natural Language to Graph Query:** Translates complex biomedical questions into precise queries for our knowledge graph.
- **Evidence-Based Answers:** Provides concise, accurate answers grounded in the underlying data.
- **Interactive Visualization:** Generates a mini-graph for each query to visually explain the relationships between genes, therapies, and diseases.
- **Verifiable Citations:** Includes PubMed IDs to support its conclusions, linking back to the original research.

## How It Works

The agent follows a multi-step pipeline to answer a question:

1.  **Question Analysis:** An LLM identifies the key entities (e.g., genes, drugs) and relationships in the user's question.
2.  **Cypher Generation:** The LLM generates a Cypher query to retrieve the relevant information from the Neo4j knowledge graph.
3.  **Query Validation:** The query is checked for safety and correctness against the graph schema.
4.  **Database Execution:** The validated query is run against the Neo4j database.
5.  **Summarization:** The results are synthesized by an LLM into a clear, natural language answer, complete with citations.

## Technology & Data

- **Backend:** Python, FastAPI, Gemini
- **Database:** Neo4j
- **Frontend:** Next.js, React, TypeScript
- **Data Sources:** [CIViC](https://civicdb.org/welcome) and [OpenTargets](https://www.opentargets.org/)
- **Deployment:** Vercel (UI) & Render (API)

---

<details>
<summary><strong>Local Development & Contribution</strong></summary>

### Prerequisites

- Python 3.10+
- Neo4j Desktop or Server
- Node.js and npm

### 1. Configure Environment

Create a `.env` file in the project root with the following variables:

```
GOOGLE_API_KEY="your_gemini_api_key"
NEO4J_URI="bolt://localhost:7687"
NEO4J_USER="neo4j"
NEO4J_PASSWORD="your_password"
```

### 2. Setup Backend

Create a virtual environment and install dependencies:

```bash
# Create and activate virtual environment
python -m venv venv
.\venv\Scripts\activate

# Install dependencies and the local package
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

### 3. Seed the Database

You can use the small, included dataset or generate a fresh one from the source APIs.

**Option A: Use the included seed data (Recommended for quick start)**
```bash
python -m src.graph.builder
```

**Option B: Generate data from CIViC + OpenTargets**
```bash
# Generate CSVs under data/civic/latest
python -m src.pipeline.civic_ingest --out-dir data/civic/latest --enrich-tags

# Point the builder to the generated dataset and ingest
$env:DATA_DIR="data/civic/latest"
python -m src.graph.builder
```

### 4. Run the Application

**Start the Backend API:**
```bash
uvicorn api.main:app --reload
```

**Run the Web Interface:**
```bash
# Navigate to the web directory
cd web

# Install dependencies
npm install

# Set the API URL and run the development server
$env:NEXT_PUBLIC_API_URL="http://localhost:8000"
npm run dev
```
The UI will be available at `http://localhost:3000`.

### 5. Run Tests

To run the backend test suite:

```bash
python -m pytest
```

</details>

---
*For a deeper dive into the architecture and schema, see [Technical Details](./docs/TECHNICAL_DETAILS.md).*