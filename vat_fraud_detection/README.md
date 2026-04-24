# EU VAT Audit System

A two-application system simulating a European VAT compliance audit workflow:

- **Ireland VAT App** (`/`) — country-level tool for auditors. Queries the EU Hub for invoice data, pre-classifies records by risk, runs LLM-backed VAT compliance analysis, and maintains a local audit database.
- **EU VAT Hub** (`eu_vat_hub/`) — central multi-country invoice repository hosted by a European institution. Stores factual invoice data only — no risk scoring, no verdicts.

All LLM calls are made locally via **LM Studio**. No external API key is required.

---

## Architecture

```
┌─────────────────────────────────────┐     HTTP / REST
│  Ireland VAT App  (port 8501)       │ ──────────────────► EU VAT Hub API (port 8503)
│  Streamlit dashboard                │ ◄────────────────── FastAPI
└─────────────────────────────────────┘
         │
         │ local LLM calls
         ▼
  LM Studio  (port 1234)

EU VAT Hub Dashboard  (port 8502)  — read-only view of the central DB
```

Ireland fetches invoice data from the EU Hub via `X-Client-Country: IE` authenticated HTTP requests. The EU Hub logs all inbound requests. Ireland logs all outgoing requests and all LLM analysis calls locally.

---

## Prerequisites

| Requirement | Version |
|-------------|---------|
| Python | 3.10+ |
| LM Studio | 0.3+ |

---

## Setup

### 1. Clone the repository

```bash
git clone git@github.com:jcvdschrieck/vat-fraud-detection.git
cd vat-fraud-detection
```

### 2. Install Python dependencies

```bash
# Ireland app
pip install -r requirements.txt

# EU VAT Hub (if it has additional deps, install from the same requirements.txt
# as both apps share the same Python environment)
pip install fastapi uvicorn httpx
```

### 3. Configure LM Studio

1. Download and install [LM Studio](https://lmstudio.ai).
2. In LM Studio, go to **Models** and download a chat model. A model with at least **7B parameters** is recommended (e.g. *Mistral 7B Instruct*). Smaller models (3B) work but may return more "uncertain" verdicts.
3. Also download an embedding model: `nomic-ai/nomic-embed-text-v1.5`.
4. Go to **Local Server** and click **Start Server** (default: `http://localhost:1234`).
5. Load your chosen chat model.

Set environment variables if your LM Studio runs on a non-default address:

```bash
export LM_STUDIO_BASE_URL=http://localhost:1234/v1
export LM_STUDIO_MODEL=mistralai/mistral-7b-instruct-v0.3        # or your model ID
export LM_STUDIO_ANALYSIS_MODEL=mistralai/mistral-7b-instruct-v0.3
```

### 4. Build the knowledge base (Ireland app only)

Run once to index Irish VAT legislation into ChromaDB:

```bash
python build_knowledge_base.py
```

---

## Launching the full setup

Open **three terminals** and run each command from the repository root:

### Terminal 1 — EU VAT Hub API

```bash
cd eu_vat_hub
uvicorn api:app --port 8503
```

The API seeds the database automatically on first run (~2,800 synthetic EU invoices across 10 member states, including an Irish increment block dated March 26–30 2026).

### Terminal 2 — EU VAT Hub Dashboard

```bash
cd eu_vat_hub
streamlit run app.py --server.port 8502
```

Open [http://localhost:8502](http://localhost:8502) — read-only view of the central invoice database with analytics and the inbound API activity log.

### Terminal 3 — Ireland VAT App

```bash
streamlit run app.py --server.port 8501
```

Open [http://localhost:8501](http://localhost:8501) — the main audit tool.

---

## Ireland app — workflow

1. **EU Query → Increment tab** — fetch Irish invoices recorded in the EU Hub after the Irish DB cutoff (2026-03-25). Each invoice is pre-classified HIGH / MEDIUM / LOW based on the supplier's error history in the local Irish database.
2. **Tick** the invoices you want to analyse and click **Launch VAT Analysis**.
3. **Invoice Analyzer** runs LLM compliance analysis on each queued invoice: retrieves relevant legislation via RAG (ChromaDB), then queries LM Studio for a verdict (correct / incorrect / uncertain) per line item.
4. **Prioritization Dashboard** ranks all analysed invoices by risk score for follow-up.
5. **History** — re-queue any past invoice for re-analysis.
6. **Activity Log** — timestamped record of every LLM analysis call.

---

## Project structure

```
vat-fraud-detection/           ← repo root = Ireland VAT App
├── README.md
├── app.py                     ← Ireland app entry point (port 8501)
├── build_knowledge_base.py    ← one-time legislation indexer
├── requirements.txt
│
├── pages/
│   ├── 1_Invoice_Analyzer.py
│   ├── 2_Prioritization_Dashboard.py
│   ├── 3_Case_View.py
│   ├── 4_History.py
│   ├── 5_EU_Query.py          ← queries EU Hub, increment fetch, analysis queue
│   └── 6_Activity_Log.py      ← LLM analysis call log (timestamped)
│
├── lib/
│   ├── models.py              ← Invoice, LineItem, AnalysisResult, …
│   ├── analyser.py            ← RAG + LLM compliance analysis
│   ├── analysis_log.py        ← SQLite log of LLM calls
│   ├── eu_client.py           ← HTTP client for EU Hub API
│   ├── database.py            ← Irish invoice SQLite DB
│   ├── db_seeder.py           ← seeds Irish DB (cutoff: 2026-03-25)
│   ├── persistence.py         ← analysis history (history.json + vat_audit.db)
│   ├── rag.py                 ← ChromaDB retrieval helpers
│   └── …
│
├── prompts/
│   ├── analysis_system.txt
│   └── …
│
├── data/                      ← runtime data (git-ignored)
│   ├── chroma_db/             ← vector store
│   ├── vat_audit.db           ← Irish invoice + analysis DB
│   ├── analysis_log.db        ← LLM activity log
│   └── eu_query_log.db        ← outgoing EU Hub request log
│
├── ireland_vat_demo_dataset/  ← 30 synthetic UBL 2.1 XML invoices
│
└── eu_vat_hub/                ← EU Institution central hub
    ├── api.py                 ← FastAPI REST API (port 8503)
    ├── app.py                 ← Streamlit dashboard (port 8502)
    ├── pages/
    │   ├── 1_Overview.py
    │   ├── 2_Invoice_Browser.py
    │   ├── 3_Analytics.py
    │   └── 4_Activity_Log.py  ← inbound API request log (timestamped)
    ├── lib/
    │   ├── database.py        ← EU Hub SQLite DB (~2,800 records)
    │   ├── seeder.py          ← seeds EU Hub DB
    │   ├── models.py          ← Pydantic API models (no risk fields)
    │   └── logging_middleware.py
    └── data/                  ← runtime data (git-ignored)
        └── eu_vat.db
```

---

## Data model

The EU Hub stores **factual invoice data only** — amounts, parties, VAT rates applied, transaction classification. No risk scores, no verdicts.

Risk assessment is the responsibility of each member state's own system. Ireland's app derives HIGH / MEDIUM / LOW pre-classification from its local supplier error-rate history.

---

## Irish DB cutoff

The Irish database contains invoices up to **2026-03-25**. The EU Hub holds 25 additional Irish invoices dated **2026-03-26 to 2026-03-30** — the "increment" not yet processed by Ireland. These are surfaced via the **EU Query → Increment** tab.
