# Supply Chain Resilience Agent

Autonomous multi-agent system for supply chain disruption monitoring and risk analysis, built with Google ADK. Implements the methodology from [AlMahri, Xu, Brintrup (2025)](https://arxiv.org/html/2601.09680v1).

## Quick Setup

### 1. Clone & Install

```bash
git clone https://github.com/1henryy/supply-chain-analysis.git
cd supply-chain-analysis/htf/app
pip install -r requirements.txt
```

### 2. Configure Environment

Create a `.env` file in the `htf/app/` directory:

```env
GOOGLE_GENAI_USE_VERTEXAI=TRUE
GOOGLE_CLOUD_PROJECT=<your-gcp-project-id>
GOOGLE_CLOUD_LOCATION=us-central1
```

Then authenticate with GCP:

```bash
gcloud auth application-default login
```

> **Note:** You need a GCP project with the Vertex AI API enabled and billing configured.
> Enable it with: `gcloud services enable aiplatform.googleapis.com --project=<your-project-id>`

### 3. Seed the Demo Database

```bash
python main.py --init
```

This creates a sample supply chain network (TechDrive Motors) with 16 suppliers across 3 tiers and 4 products.

### 4. Run

**Dashboard (no LLM needed):**
```bash
streamlit run ui/app.py
```

**AI Agent Pipeline (requires Vertex AI):**
```bash
python main.py
```

## Data Ingestion

To use your own supply chain data, upload CSV/JSON files via the Streamlit UI (**Data Ingestion** mode) or use `src/ingest.py` programmatically. Templates are in `data/templates/`.

## Risk Formula

```
RISK = 0.35×Breadth + 0.25×Dependency + 0.20×Criticality + 0.10×Centrality + 0.10×Depth
```

- **HIGH** (≥ 0.6): VP/CFO approval required
- **MEDIUM** (0.45–0.59): Auto-execute with notification
- **LOW** (< 0.45): Auto-execute silently
