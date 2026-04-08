# EU Custom Data Hub — Real-Time Demo

A real-time simulation of the European Commission's **Taxation and Customs Union** transaction monitoring system.
The application streams B2C cross-border e-commerce transactions across 27 EU member states, detects VAT rate anomalies, and routes suspicious cases to an AI agent that produces a compliance verdict with legislation references.

---

## Architecture overview

```
┌─────────────────────────────────────────────────────────────────┐
│  FastAPI backend (port 8505)                                    │
│  ├─ Simulation engine  — event-driven replay of March 2026      │
│  ├─ Pub/sub pipeline   — brokers + factory workers              │
│  │   ├─ RT Risk 1      — VAT ratio deviation alarm              │
│  │   ├─ RT Risk 2      — watchlist lookup                       │
│  │   ├─ Consolidation  — GREEN / AMBER / RED scoring            │
│  │   ├─ Order Validation — field completeness                   │
│  │   ├─ Arrival Notification — exponential-delay arrival event  │
│  │   └─ Release Factory — combines all three streams            │
│  ├─ Agent worker       — local LLM analysis via LM Studio       │
│  └─ SSE stream         — live queue push                        │
└────────────────┬────────────────────────────────────────────────┘
                 │ HTTP / SSE / static
┌────────────────▼────────────────────────────────────────────────┐
│  React + Vite frontend  (served at port 8505)                   │
│  ├─ Simulation  — pipeline diagram, controls, event counts      │
│  ├─ Main        — live transaction stream                       │
│  ├─ Dashboard   — VAT metrics & charts                          │
│  ├─ Suspicious  — flagged transactions                          │
│  └─ Agent Log   — AI analysis console                           │
└─────────────────────────────────────────────────────────────────┘
                 │ static mount  /ireland-app/
┌────────────────▼────────────────────────────────────────────────┐
│  Ireland Revenue app                                            │
│  Standalone HTML — investigation queue                          │
└─────────────────────────────────────────────────────────────────┘
                 │ subprocess
┌────────────────▼────────────────────────────────────────────────┐
│  vat_fraud_detection/ (git submodule)                           │
│  Local-LLM-powered VAT compliance analyser                      │
│  with RAG over EU VAT legislation (ChromaDB)                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.11+ | |
| Node.js | 18+ | Required to build the frontend |
| npm | 9+ | Bundled with Node.js |
| LM Studio | Latest | For the AI agent (optional) |

### Installing Node.js and npm

`npm` is bundled with Node.js — installing Node.js is all you need.

**Windows**
1. Go to [https://nodejs.org](https://nodejs.org) and download the **LTS** installer (`.msi`)
2. Run the installer and follow the prompts — leave all defaults selected
3. Open a **new** PowerShell or Command Prompt window (existing windows won't see the updated PATH)
4. Verify: `node --version` and `npm --version`

**macOS**
```bash
# Using Homebrew (recommended)
brew install node

# Or download the .pkg installer from https://nodejs.org
```

**Linux (Debian / Ubuntu)**
```bash
curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
sudo apt-get install -y nodejs
```

---

## Setup

### 1. Clone with submodule

```bash
git clone --recurse-submodules https://github.com/jcvdschrieck/EU_custom_data_hub_RTDemo.git
cd EU_custom_data_hub_RTDemo
```

If you already cloned without `--recurse-submodules`:

```bash
git submodule update --init --recursive
```

### 2. Python dependencies

```bash
pip install -r requirements.txt
```

### 3. AI agent — LM Studio (optional)

The VAT fraud detection agent calls a **locally hosted LLM via [LM Studio](https://lmstudio.ai)**.
No API key or internet connection is needed — it runs entirely on your machine.

**Setup:**
1. Download and install [LM Studio](https://lmstudio.ai)
2. Download a model (any instruction-tuned model works; a 7–8B model is recommended)
3. In LM Studio, go to the **Developer** tab and start the local server (default port: `1234`)
4. Configure the model identifier.

`vat_fraud_detection/` is a git submodule included in this repository (populated by the `--recurse-submodules` clone in step 1). Create its `.env` file from the bundled example:

```bash
cp vat_fraud_detection/.env.example vat_fraud_detection/.env
```

Then edit `vat_fraud_detection/.env`:
```
LM_STUDIO_BASE_URL=http://localhost:1234/v1
LM_STUDIO_MODEL=your-model-identifier-here
```

To find the exact model identifier, query the LM Studio server:
```bash
curl http://localhost:1234/v1/models
```

This `.env` file is read automatically at runtime — no need to export environment variables manually.

> **Without LM Studio running**, the agent will still function — suspicious transactions will receive an `uncertain` verdict instead of a full AI-powered compliance analysis.

> **Note on RAG context:** The vector store (`data/chroma_db/`) and legislation documents are not included in the repository. The agent will still produce verdicts using its base LLM reasoning, but without retrieval-augmented legislation references.

### 4. Frontend dependencies and build

```bash
cd frontend
npm install
npm run build
cd ..
```

This compiles the React app into `frontend/dist/`, which FastAPI then serves automatically.

### 5. Seed the databases

```bash
python seed_databases.py
```

This creates two SQLite databases in `data/`:
- `european_custom.db` — ~9 000 historical transactions (Sep 2025 – Feb 2026)
- `simulation.db`      — ~1 500 March 2026 transactions ready to be replayed

---

## Running

```bash
python -m uvicorn api:app --host 0.0.0.0 --port 8505
```

Then open [http://localhost:8505](http://localhost:8505).

You will land on the **Simulation** page. Click **▶ Start** to begin the simulation.

> The frontend is served directly by FastAPI — no separate `npm run dev` is needed in production mode.
> If you are actively developing the frontend, you can run `npm run dev` in the `frontend/` directory
> and point your browser to `http://localhost:5175` instead.

---

## Application pages

| Page | URL | Description |
|------|-----|-------------|
| Simulation | `/simulation` | Pipeline diagram, controls, event counts — **start here** |
| Main | `/main` | Live transaction stream (SSE), KPI tiles, active alarms |
| Dashboard | `/dashboard` | VAT metrics, charts by country & category |
| Suspicious | `/suspicious` | Transactions flagged by the alarm system |
| Agent Log | `/agent-log` | AI analysis console with legislation references |
| Country Queue | Nav dropdown | Per-country investigation queue (Ireland live, others placeholder) |

---

## Simulation scenario

The simulation replays **March 2026** at configurable speed:

| Speed | Description |
|-------|-------------|
| 1× | Real time — one event fires at its actual inter-arrival gap |
| 30× | 1 sim-day ≈ 48 real-seconds |
| 120× | Full month in ~12 minutes |
| 360× | Full month in ~4 minutes |
| 1440× | Full month in ~1 minute |

A fraud scenario is embedded:
- **Supplier**: TechZone GmbH (Germany) — sells electronics B2C to Irish consumers
- **Fraud**: applies 0% VAT (food/zero-rated rate) instead of the correct 23% Irish standard rate
- **Detection**: the alarm engine detects the VAT/value ratio deviation during week 2 of March
- **Investigation**: flagged transactions are analysed by the local LLM agent and forwarded to the Ireland Revenue queue with full legislation references

---

## Project structure

```
EU_custom_data_hub_RTDemo/
├── api.py                    # FastAPI app — all endpoints, pub/sub pipeline, SSE
├── seed_databases.py         # One-time DB seeder
├── requirements.txt
├── lib/
│   ├── broker.py             # Pub/sub MessageBroker + topic constants
│   ├── config.py             # Ports, paths, simulation time window
│   ├── catalog.py            # Suppliers, countries, VAT rates
│   ├── database.py           # SQLite helpers (upsert, historical seeding)
│   ├── event_store.py        # JSON event persistence (data/events/)
│   ├── seeder.py             # Historical + simulation data generator
│   ├── simulator.py          # Async event-driven simulation loop
│   ├── alarm_checker.py      # VAT ratio deviation alarm engine
│   ├── watchlist.py          # Seller/country watchlist
│   └── agent_bridge.py       # Subprocess bridge → vat_fraud_detection
├── frontend/                 # React + Vite (built output served by FastAPI)
│   └── src/
│       ├── pages/            # Simulation, Main, Dashboard, Suspicious, Agent Log
│       └── components/       # EclLayout, SimulationWidget, charts
├── ireland_app/
│   └── index.html            # Standalone Irish Revenue investigation app
├── vat_fraud_detection/      # Git submodule — local LLM VAT compliance agent
│   ├── _analyse_tx.py        # Subprocess entry point (called by agent_bridge)
│   ├── lib/analyser.py       # Core AI analysis engine (LM Studio / OpenAI-compatible)
│   ├── data/chroma_db/       # RAG vector store (EU VAT legislation)
│   └── prompts/              # LLM system prompts
└── data/                     # SQLite databases + event files (git-ignored)
    ├── european_custom.db
    ├── simulation.db
    └── events/               # Per-topic JSON event files (flushed on reset)
```

---

## API reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/api/queue` | Latest 30 transactions (REST snapshot) |
| GET | `/api/queue/stream` | SSE stream — one transaction per event |
| GET | `/api/transactions` | Paginated historical query |
| GET | `/api/metrics` | VAT aggregates with filters |
| GET | `/api/alarms` | Alarm list |
| GET | `/api/suspicious` | Last 50 suspicious transactions |
| GET | `/api/agent-log` | AI analysis history with legislation refs |
| GET | `/api/agent-processing` | Transactions currently being analysed |
| POST | `/api/agent/analyse/{id}` | Trigger AI agent on a transaction |
| GET | `/api/ireland-queue` | Cases forwarded to Ireland investigation |
| GET | `/api/ireland-case/{id}` | Full case detail |
| GET | `/api/simulation/status` | Simulation state + progress |
| GET | `/api/simulation/pipeline` | Per-topic event counts and queue sizes |
| POST | `/api/simulation/start` | Start simulation |
| POST | `/api/simulation/pause` | Pause |
| POST | `/api/simulation/resume` | Resume |
| POST | `/api/simulation/speed` | Set speed `{"speed": <float>}` |
| POST | `/api/simulation/reset` | Reset to start (preserves historical data) |
| GET | `/api/catalog/suppliers` | Supplier catalogue |
| GET | `/api/catalog/countries` | Country list |

---

## License

Demo project — European Commission Taxation and Customs Union simulation.
