# OncoGraph Agent

OncoGraph Agent is a sophisticated Q&A system that answers complex questions about cancer genomics by leveraging a knowledge graph. It translates natural language queries into cypher queries, extracts precise information, and presents it with citations, providing a reliable tool for researchers and clinicians.

## Example Query and Answer
```
Question: Do KRAS G12C mutations affect response to Sotorasib in Lung Cancer?
Answer: Yes, KRAS G12C mutations are associated with sensitivity to Sotorasib in Lung Cancer. 
This indicates that patients with KRAS G12C-mutated lung cancer may respond favorably to Sotorasib treatment (PMID: 33857313).
```

### More Example Questions

- What biomarkers predict resistance to anti-EGFR therapies in Colorectal Cancer?
- Find me the PubMed citations related to Sotorasib and KRAS G12C.
- Do KRAS G12C mutations affect response to Sotorasib in Lung Cancer?
- What is the predicted response of EGFR L858R to Gefitinib in Lung Cancer?
- Does EGFR T790M confer resistance to Gefitinib, and which therapy may overcome it in Lung Cancer?
- Which therapies target EGFR?

## Key Features

- **Natural Language to Cypher:** Translates complex biomedical questions into precise Cypher queries for the Neo4j graph database.
- **Grounded Answers:** Provides concise, accurate answers backed by data from the knowledge graph.
- **Data Visualization:** Generates a mini-graph visualization for each query to illustrate the relationships between relevant entities (genes, variants, therapies, diseases).
- **Cited Evidence:** Includes PubMed citations to support the provided answers.
- **Full-Stack Application:** Features a Python backend with a Q&A pipeline, a FastAPI web server, and a Next.js user interface.

## Technology Stack

- **Backend:** Python, FastAPI
- **Database:** Neo4j
- **LLM Integration:** Gemini
- **Frontend:** Next.js, React, TypeScript
- **Deployment:** Vercel (UI), Render (API)

## How It Works

The agent follows a multi-step pipeline to answer questions:

1.  **Question Analysis:** An LLM analyzes the user's question to identify key entities and relationships.
2.  **Cypher Generation:** The LLM generates a Cypher query to retrieve relevant information from the Neo4j knowledge graph.
3.  **Query Validation:** A validator checks the generated Cypher for safety and correctness against the graph schema.
4.  **Database Execution:** The validated query is executed against the Neo4j database.
5.  **Summarization:** The results are summarized by an LLM into a natural language answer, complete with citations.

For a deeper dive into the architecture, schema, and query patterns, see [Technical Details](./docs/TECHNICAL_DETAILS.md).

## Getting Started

### Prerequisites

- Python 3.10+
- Neo4j Desktop or Server
- Node.js and npm

### 1. Configure Environment

Create a `.env` file in the root directory with the following variables:

```
GOOGLE_API_KEY="your_gemini_api_key"
NEO4J_URI="bolt://localhost:7687"
NEO4J_USER="neo4j"
NEO4J_PASSWORD="your_password"
```

### 2. Setup Backend

Create a virtual environment, install dependencies, and register the package:

```powershell
# Create and activate virtual environment
python -m venv venv
.\venv\Scripts\activate

# Install dependencies
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
```

### 3. Seed the Database

Run the graph builder script once to populate Neo4j with the seed data from the `data/manual/` directory:

```powershell
python -m src.graph.builder
```

## Running the Application

### CLI

You can interact with the agent directly through the command-line interface:

```powershell
python run.py "Do KRAS mutations affect anti-EGFR therapy in colorectal cancer?"
```

**CLI Flags:**
- `--trace`: Stream each step of the pipeline to the console.
- `--debug`: Print full stack traces on errors.
- `--no-log`: Disable writing logs to a file.

### Web Interface

The project includes a Next.js frontend to interact with the agent through a web browser.

```powershell
# Navigate to the web directory
cd web

# Install dependencies
npm install

# Set the API URL and run the development server
$env:NEXT_PUBLIC_API_URL="http://localhost:8000"
npm run dev
```
Before running the UI, you need to start the FastAPI server:
```powershell
uvicorn api.main:app --reload
```
The UI will be available at `http://localhost:3000`.

## Testing

To run the full suite of tests for the backend, use pytest:

```powershell
python -m pytest
```

---

*For more detailed technical documentation, please see [Technical Details](./docs/TECHNICAL_DETAILS.md).*