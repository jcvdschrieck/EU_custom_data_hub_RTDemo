# EU Custom Data Hub — Real-Time Demo

A real-time simulation of the European Commission's **Taxation and Customs Union** transaction monitoring system.
The application streams B2C cross-border e-commerce transactions across 27 EU member states, detects VAT rate anomalies, routes suspicious cases through a configurable investigation pipeline, and lets a tax officer review them in a companion **Revenue Guardian** UI before deciding to release or retain.

---

## Architecture overview

```
┌─────────────────────────────────────────────────────────────────┐
│  FastAPI backend (port 8505)                                    │
│  ├─ Simulation engine  — continuous-clock replay of a 15-min    │
│  │                       compressed March 2026 window           │
│  ├─ Pub/sub pipeline   — brokers + factory workers              │
│  │   ├─ RT Risk 1      — VAT ratio deviation alarm              │
│  │   ├─ RT Risk 2      — watchlist lookup                       │
│  │   ├─ Consolidation  — GREEN / AMBER / RED scoring            │
│  │   ├─ Order Validation — field completeness                   │
│  │   ├─ Arrival Notification — exponential-delay arrival event  │
│  │   ├─ Release Factory  — three-way routing by score           │
│  │   └─ Holding Worker   — drains INVESTIGATE_EVENT into the    │
│  │                         in-memory pending dict (manual mode) │
│  ├─ Manual investigation API  — pending list, SSE stream,       │
│  │                              run-agent, decide, timeline     │
│  ├─ Agent worker       — local LLM analysis via LM Studio       │
│  └─ SSE streams        — live queue push + sim-state push       │
└────────────────┬───────────────────────────┬────────────────────┘
                 │ HTTP / SSE / static       │ HTTP + SSE + CORS
┌────────────────▼─────────────────┐ ┌───────▼────────────────────┐
│  Internal React + Vite frontend  │ │  Revenue Guardian (sibling │
│  served at port 8505             │ │  repo, port 8080 in dev)   │
│  ├─ Simulation diagram & ctrl    │ │  Vite + React + shadcn/ui  │
│  ├─ Main / Dashboard / Suspicious│ │  ├─ Customs Authority      │
│  └─ Agent Log                    │ │  ├─ Tax Authority (live    │
│                                  │ │     SSE-driven human-in-   │
│                                  │ │     the-loop investigation │
│                                  │ │     review queue)          │
│                                  │ │  └─ Investigation case     │
│                                  │ │     detail (timeline)      │
└────────────────┬─────────────────┘ └────────────────────────────┘
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

### Investigation flow modes

The investigation pipeline runs in **one of two modes**, gated by the
`AUTO_INVESTIGATION_AGENT` constant in `api.py`:

| Mode | Constant | Behavior |
|---|---|---|
| **Manual** (default) | `False` | `INVESTIGATE_EVENT` items land in the in-memory `_pending_investigations` dict via the holding worker. The Revenue Guardian operator on `:8080` reviews each one, manually triggers the VAT fraud detection agent, and publishes the final release/retain decision. |
| **Auto** (legacy) | `True` | The original `_investigator_factory` + `_investigation_agent_worker` auto-route IE-bound items through the agent and emit terminal events without human input. Code is preserved for one-line reactivation when demoing without the UI. |

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

### Running alongside Revenue Guardian (UI integration)

The companion **revenue-guardian** UI (sibling repo) consumes this backend's
investigation API to drive the human-in-the-loop VAT fraud review flow. To run
both apps together:

```bash
# Terminal 1 — this repo
python -m uvicorn api:app --host 0.0.0.0 --port 8505

# Terminal 2 — sibling repo
cd ../revenue-guardian
npm install   # first time only
npm run dev   # serves on http://localhost:8080
```

Open the EU Customs Data Hub at `:8505` (start the simulation), then the
Revenue Guardian dashboard at `:8080`. Investigations routed by the simulation
pipeline (`INVESTIGATE_EVENT`) will appear in the Revenue Guardian **Tax
Authority** page, where they wait for the operator to trigger the agent and
make a release / retain decision. See the integration endpoints under
`GET /api/investigations/pending`, `GET /api/investigations/stream`,
`POST /api/investigations/{tx_id}/run-agent`,
`POST /api/investigations/{tx_id}/decide`, and
`GET /api/transactions/{tx_id}/timeline`.

When `AUTO_INVESTIGATION_AGENT = False` (default in `api.py`), the legacy
auto-driven `_investigation_agent_worker` is disabled and Revenue Guardian
becomes the only entry point to the agent. Flip the constant to re-enable the
auto pipeline if you need to demo without the UI.

---

## Application pages

| Page | URL | Description |
|------|-----|-------------|
| Simulation | `/simulation` | Pipeline diagram (with the human-in-the-loop investigation band), controls, event counts — **start here** |
| Main | `/main` | Live transaction stream (SSE), KPI tiles, active alarms |
| Dashboard | `/dashboard` | VAT metrics, charts by country & category |
| Suspicious | `/suspicious` | Transactions flagged by the alarm system. The per-row Analyse button is disabled in manual mode — agent control has moved to the Revenue Guardian Tax Authority page on `:8080` |
| Agent Log | `/agent-log` | AI analysis console with legislation references |
| Country Queue | Nav dropdown | Per-country investigation queue (Ireland live, others placeholder) |

---

## Simulation scenario

All March-2026 source transactions are rescaled at seed time so their
timestamps fall inside a **15-sim-minute window** starting at March 1st 00:00:00.
The continuous-clock simulation loop advances `sim_time` smoothly between events
(no freezing during quiet periods) at one of three user-facing multipliers
(sim-seconds per real-second):

| Multiplier | sim-sec / real-sec | Wall-clock playback |
|------------|--------------------|---------------------|
| **×1** (default) | 1 | 15 sim-min in 15 real-min — real-time |
| **×10** | 10 | 15 sim-min in ~1.5 real-min |
| **×100** | 100 | 15 sim-min in ~9 real-sec |

A fraud scenario is embedded:
- **Supplier**: TechZone GmbH (Germany) — sells electronics B2C to Irish consumers
- **Fraud**: applies 0% VAT (food/zero-rated rate) instead of the correct 23% Irish standard rate
- **Detection**: the alarm engine detects the VAT/value ratio deviation early in the run
- **Investigation (manual mode, default)**: flagged AMBER-path transactions land in the
  in-memory holding dict and appear in the Revenue Guardian Tax Authority page
  on `:8080`. The operator clicks **Run Agent** to invoke the local LLM, then
  picks **Release** or **Retain** based on the verdict + reasoning.
- **Investigation (auto mode)**: when `AUTO_INVESTIGATION_AGENT = True`, IE-bound
  items are auto-routed through the agent and forwarded to the Ireland Revenue
  queue with legislation references — no UI required.

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

### Core endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/api/queue` | Latest 30 transactions (REST snapshot) |
| GET | `/api/queue/stream` | SSE stream — one transaction per event |
| GET | `/api/transactions` | Paginated historical query |
| GET | `/api/transactions/{id}/timeline` | Full chronological broker-event history for a single transaction (used by the Revenue Guardian case-detail page) |
| GET | `/api/metrics` | VAT aggregates with filters |
| GET | `/api/alarms` | Alarm list |
| GET | `/api/suspicious` | Last 50 suspicious transactions (used by the Revenue Guardian Customs Authority dashboard) |
| GET | `/api/agent-log` | AI analysis history with legislation refs |
| GET | `/api/agent-processing` | Transactions currently being analysed |
| POST | `/api/agent/analyse/{id}` | Trigger AI agent on a transaction (legacy entry point — disabled in the internal Suspicious page UI) |
| GET | `/api/ireland-queue` | Cases forwarded to Ireland investigation |
| GET | `/api/ireland-case/{id}` | Full case detail |
| GET | `/api/catalog/suppliers` | Supplier catalogue |
| GET | `/api/catalog/countries` | Country list |

### Simulation control

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/simulation/status` | Simulation state + progress |
| GET | `/api/simulation/pipeline` | Per-topic event counts, queue sizes, `pending_investigations`, `pending_investigations_running` |
| GET | `/api/simulation/stream` | SSE stream pushing consolidated `{status, pipeline}` snapshots at ~5 Hz |
| POST | `/api/simulation/start` | Start simulation |
| POST | `/api/simulation/pause` | Pause |
| POST | `/api/simulation/resume` | Resume |
| POST | `/api/simulation/speed` | Set speed `{"speed": <float>}` (sim-sec per real-sec) |
| POST | `/api/simulation/reset` | Reset to start (preserves historical data) |

### Manual investigation API (consumed by Revenue Guardian)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/investigations/pending` | Snapshot of every investigation parked in the manual-review holding dict, newest first |
| GET | `/api/investigations/stream` | SSE stream pushing the full pending list whenever it changes (new item, agent run, decision) |
| POST | `/api/investigations/{id}/run-agent` | Trigger the VAT fraud detection agent on a pending entry. Returns 202 immediately; the verdict lands via the SSE stream when ready. Idempotent (409 if already running or decided). |
| POST | `/api/investigations/{id}/decide` | Body `{action: "release"\|"retain"}`. Publishes `AGENT_RELEASE_EVENT` (release path: feeds the Post-Inv Release factory) or `AGENT_RETAIN_EVENT` (retain path: terminal + writes to the Ireland queue). Removes the entry from pending and broadcasts an SSE update. |

---

## License

Demo project — European Commission Taxation and Customs Union simulation.
