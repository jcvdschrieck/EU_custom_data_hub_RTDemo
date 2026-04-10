# EU Custom Data Hub — Real-Time Demo

A real-time simulation of the European Commission's **Taxation and Customs Union** transaction monitoring system. The application streams B2C cross-border e-commerce transactions across 27 EU member states, scores them in real time for VAT fraud risk, routes RED and AMBER cases through two independent operator queues (Customs and Tax), and persists the full lifecycle into a normalised data hub.

The Customs and Tax operator dashboards live in a companion repository: **[revenue-guardian](https://github.com/jcvdschrieck/revenue-guardian)**.

---

## Architecture overview

```
┌──────────────────────────────────────────────────────────────────────┐
│  FastAPI backend (port 8000)                                         │
│                                                                      │
│  Simulation engine                                                   │
│    └─ Continuous-clock replay of a 15-min compressed March-2026      │
│       window. One Sales Order Event published per sim-clock tick.    │
│                                                                      │
│  Pub/sub pipeline (lib/broker.py — in-memory MessageBroker)          │
│    ├─ RT Risk Assessment 1   — VAT-ratio deviation alarm             │
│    ├─ RT Risk Assessment 2   — supplier/origin watchlist             │
│    ├─ Risk Score Consolidation — GREEN / AMBER / RED                 │
│    ├─ Sales Order Validation — field-completeness check              │
│    ├─ Goods Transport         — exponential-delay arrival event      │
│    ├─ Release Factory         — joins all signals, routes by colour  │
│    ├─ Customs Listener        — drains RED  → _customs_queue         │
│    ├─ Tax Listener            — drains AMBER → _tax_queue            │
│    ├─ DB Store Worker         — terminal events → european_custom.db │
│    └─ Data Hub Writer         — 30-s polling tick → 3 normalised     │
│                                  tables (Sales Order + Line Item,    │
│                                  Risk, AI Analysis)                  │
│                                                                      │
│  Two-entity workflow API                                             │
│    /api/customs/*  — Customs Office (master, terminal decision)      │
│    /api/tax/*      — Tax Office (advisory, runs the AI agent)        │
│                                                                      │
│  SSE streams                                                         │
│    /api/queue/stream            — live transaction feed              │
│    /api/customs/queue/stream    — Customs queue updates              │
│    /api/tax/queue/stream        — Tax queue updates                  │
│    /api/simulation/stream       — consolidated {status, pipeline}    │
└──────────────┬──────────────────────────────────┬────────────────────┘
               │ HTTP / SSE / static              │ HTTP + SSE + CORS
               ▼                                  ▼
┌──────────────────────────────────┐  ┌──────────────────────────────┐
│  Internal React + Vite frontend  │  │  Revenue Guardian            │
│  served by FastAPI on :8000      │  │  (sibling repo, :8080 in dev)│
│  ├─ Simulation diagram & ctrl    │  │  Vite + React + shadcn/ui    │
│  ├─ Live queue / Dashboard       │  │  ├─ Customs Authority page   │
│  ├─ Suspicious transactions      │  │  ├─ Tax Authority page       │
│  ├─ Agent Log (audit history)    │  │  └─ Investigation case detail│
│  └─ Ireland investigation queue  │  │     (timeline)               │
└──────────────────────────────────┘  └──────────────────────────────┘
                                                  │ subprocess
                                                  ▼
                              ┌──────────────────────────────────────┐
                              │  vat_fraud_detection/ (git submodule)│
                              │  Local-LLM VAT compliance analyser   │
                              │  with RAG over EU VAT legislation    │
                              │  (LM Studio on :1234)                │
                              └──────────────────────────────────────┘
```

### Two-entity workflow

Customs and Tax are modelled as two **completely separate offices**, each with its own broker listener, in-memory queue, SSE stream, and Revenue Guardian dashboard page. Routing on the Release Factory:

| Risk Score | Topic | Lands in | Operator action |
|---|---|---|---|
| GREEN | `release_event` | DB store (terminal) | none — auto-released |
| RED   | `retain_event`     | `_customs_queue` | Customs Officer reviews and decides release / retain (or escalates to Tax for advice) |
| AMBER | `investigate_event`| `_tax_queue`     | Tax Officer optionally runs the VAT Fraud Detection Agent, then issues a non-binding **recommendation** that returns the case to the Customs queue |

The **Customs Officer is master**: their final decision is the only terminal event. When the Customs decision differs from a Tax recommendation, an audit `custom_override = true` flag is set on the published event.

### Data hub

Three normalised tables in `european_custom.db`, populated by `_data_hub_writer` on a **30-second polling tick** (subscribes to `SALES_ORDER_EVENT`, `RT_SCORE`, and `AI_ANALYSIS_EVENT`):

| Table | Source | Cardinality |
|---|---|---|
| `sales_order_line_item` | `SALES_ORDER_EVENT` | every transaction (one synthetic line per order today) |
| `line_item_risk` | `RT_SCORE` | every transaction (RT_SCORE fires for all of them) |
| `line_item_ai_analysis` | `AI_ANALYSIS_EVENT` (published by `/api/tax/{id}/run-agent`) | only Tax-officer-triggered runs |

Keyed by `sales_order_line_item_SKU = f"{order_id}-{line_number:03d}"`. The legacy flat `transactions` table is preserved alongside (the alarm checker still uses it for its 7-day VAT-ratio baseline) and is back-filled into `sales_order_line_item` once on first startup.

The **Sales Order + Line Item** table preserves the two-tier party model from `simplified_order.json`:
- `deemed_importer_*` — the EU reseller (order header)
- `seller_*` + `origin_country` — the non-EU producer (per line item)

`dest_country_region` uses the UN geoscheme EU sub-regions (Western / Northern / Southern / Eastern Europe), mapped by `lib/regions.py`.

---

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.11+ | |
| Node.js | 18+ | Required to build the frontend |
| npm | 9+ | Bundled with Node.js |
| LM Studio | Latest | Optional — needed for the VAT Fraud Detection Agent |

### Installing Node.js

`npm` is bundled with Node.js — installing Node.js is all you need.

**Windows** — download the LTS installer from [https://nodejs.org](https://nodejs.org), run it, and open a **new** terminal so the updated PATH is picked up.

**macOS** — `brew install node` (or download the `.pkg` from nodejs.org).

**Linux (Debian/Ubuntu)**
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

### 3. Frontend build

```bash
cd frontend
npm install
npm run build
cd ..
```

This compiles the React app into `frontend/dist/`, which FastAPI serves automatically at `http://localhost:8000`.

### 4. AI agent — LM Studio (optional)

The VAT Fraud Detection Agent calls a **locally hosted LLM via [LM Studio](https://lmstudio.ai)**. No API key, no internet — it runs entirely on your machine.

1. Download and install [LM Studio](https://lmstudio.ai).
2. Download an instruction-tuned model (a 7–8B model is plenty).
3. In LM Studio, open the **Developer** tab and start the local server (default port `1234`).
4. Configure the model identifier:

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

> **Without LM Studio running**, the Tax officer can still run the agent — every analysis just returns an `uncertain` verdict with no legislation references.

> **RAG context** — the vector store (`data/chroma_db/`) and legislation documents are not included in the repository. Without them the agent uses only its base LLM reasoning, no retrieval-augmented citations.

### 5. Seed the databases

```bash
python seed_databases.py
```

This creates two SQLite databases in `data/`:
- `european_custom.db` — ~10 000 historical transactions (Sep 2025 – Feb 2026), back-filled into `sales_order_line_item` on first run
- `simulation.db` — ~1 600 March 2026 transactions ready to replay

---

## Running

```bash
python -m uvicorn api:app --host 0.0.0.0 --port 8000
```

Then open [http://localhost:8000](http://localhost:8000). You will land on the **Simulation** page; click **▶ Start** to begin.

> The frontend is served directly by FastAPI — no separate `npm run dev` needed in production. For frontend hot-reload during development, run `npm run dev` in `frontend/` and point your browser to `http://localhost:5175`.

### Running alongside Revenue Guardian

The companion `revenue-guardian` UI consumes this backend's `/api/customs/*` and `/api/tax/*` endpoints to drive the human-in-the-loop review flow:

```bash
# Terminal 1 — this repo
python -m uvicorn api:app --host 0.0.0.0 --port 8000

# Terminal 2 — sibling repo
cd ../revenue-guardian
npm install   # first time only
npm run dev   # serves on http://localhost:8080
```

Open the EU Custom Data Hub at `:8000` (start the simulation), then the Revenue Guardian dashboard at `:8080`. RED-routed transactions land in the **Customs Authority** page; AMBER-routed ones land in the **Tax Authority** page.

---

## Application pages

Internal React frontend served at `:8000`:

| Page | URL | Description |
|---|---|---|
| Simulation | `/simulation` | Pipeline diagram (with side-by-side Customs / Tax bottom band), controls, event counts — **start here** |
| Main | `/main` | Live transaction stream (SSE), KPI tiles, active alarms |
| Dashboard | `/dashboard` | VAT metrics, charts by country & category |
| Suspicious | `/suspicious` | Historical transactions flagged by the alarm system |
| Agent Log | `/agent-log` | Audit history of every Tax officer agent run with legislation references |
| Ireland Queue | nav dropdown | Per-country investigation queue (Ireland live, others placeholder) |

Revenue Guardian frontend (sibling repo, served at `:8080`):

| Page | URL | Description |
|---|---|---|
| Customs Authority | `/customs-authority` | Live Customs queue overlay on top of historical suspicious transactions; release / retain / escalate-to-Tax actions |
| Tax Authority | `/tax-authority` | Live Tax queue; Run Agent + Recommend (release / retain) actions |
| Investigation | `/investigation/:id` | Case detail with full timeline, agent verdict, recommendation history |

---

## Simulation scenario

All March-2026 source transactions are rescaled at seed time so their timestamps fall inside a **15-sim-minute window** starting at March 1st 00:00:00. The continuous-clock simulation loop advances `sim_time` smoothly between events at one of three multipliers:

| Multiplier | sim-sec / real-sec | Wall-clock playback |
|---|---|---|
| **×1** (default) | 1 | 15 sim-min in 15 real-min |
| **×10** | 10 | 15 sim-min in ~1.5 real-min |
| **×100** | 100 | 15 sim-min in ~9 real-sec |

### Embedded fraud scenario

- **Supplier**: TechZone GmbH (Germany) — sells electronics B2C to Irish consumers
- **Fraud**: applies 0% VAT (zero-rated rate) instead of the correct 23% Irish standard rate
- **Detection**: the alarm engine spots the VAT/value ratio deviation early in the run
- **Routing**: flagged orders are RED-scored by `RT Risk Assessment 1`, routed to the **Customs queue**
- **Review**: the Customs Officer can decide directly OR escalate the case to the **Tax queue**, where the Tax Officer can run the VAT Fraud Detection Agent for a legislation-grounded verdict before issuing a non-binding recommendation back to Customs

---

## Project structure

```
EU_custom_data_hub_RTDemo/
├── api.py                       # FastAPI app — endpoints, pub/sub pipeline, SSE, lifespan
├── seed_databases.py            # One-time DB seeder
├── requirements.txt
├── lib/
│   ├── broker.py                # Pub/sub MessageBroker + topic constants
│   ├── config.py                # Ports, paths, simulation time window
│   ├── catalog.py               # Suppliers, countries, VAT rates
│   ├── database.py              # SQLite schema (legacy + 3-table data hub) + helpers
│   ├── regions.py               # Country → UN geoscheme sub-region map
│   ├── event_store.py           # JSON event persistence (data/events/)
│   ├── seeder.py                # Historical + simulation data generator
│   ├── simulator.py             # Async event-driven simulation loop
│   ├── alarm_checker.py         # VAT-ratio deviation alarm engine
│   ├── watchlist.py             # Seller / origin-country watchlist
│   ├── message_factory.py       # Builds schema-conforming broker messages
│   └── agent_bridge.py          # Subprocess bridge → vat_fraud_detection
├── frontend/                    # React + Vite (built output served by FastAPI)
│   └── src/
│       ├── pages/               # Simulation, Main, Dashboard, Suspicious, Agent Log, Ireland
│       └── components/          # EclLayout, charts, helpers
├── ireland_app/
│   └── index.html               # Standalone Irish Revenue investigation app
├── pages/                       # Streamlit dashboards (legacy alt UI)
├── vat_fraud_detection/         # Git submodule — local LLM VAT compliance agent
│   ├── _analyse_tx.py           # Subprocess entry point (called by agent_bridge)
│   ├── lib/analyser.py          # Core AI analysis engine
│   └── prompts/                 # LLM system prompts
└── data/                        # SQLite databases + event files (git-ignored)
    ├── european_custom.db       # Historical + data hub tables
    ├── simulation.db            # March-2026 transactions to replay
    └── events/                  # Per-topic JSON event files (flushed on reset)
```

---

## API reference

### Health & live data

| Method | Endpoint | Description |
|---|---|---|
| GET  | `/health` | Health check + total record count |
| GET  | `/api/queue` | Latest 30 transactions (REST snapshot) |
| GET  | `/api/queue/stream` | SSE — one transaction per event |
| GET  | `/api/transactions` | Paginated historical query |
| GET  | `/api/transactions/{id}/timeline` | Full chronological broker-event history for a single transaction (used by the Revenue Guardian case-detail page) |
| GET  | `/api/metrics` | VAT aggregates with filters |
| GET  | `/api/alarms` | Alarm list (`?active_only=true` optional) |
| GET  | `/api/suspicious` | Last 50 suspicious transactions (used by the Revenue Guardian Customs Authority dashboard) |
| GET  | `/api/agent-log` | Audit history of every Tax officer agent run with legislation refs |
| GET  | `/api/ireland-queue` | Cases queued for Irish Revenue investigation |
| GET  | `/api/ireland-case/{id}` | Full case detail |
| GET  | `/api/catalog/suppliers` | Supplier catalogue |
| GET  | `/api/catalog/countries` | Country list |

### Customs Office (Revenue Guardian Customs Authority page)

| Method | Endpoint | Description |
|---|---|---|
| GET  | `/api/customs/queue` | Snapshot of the live Customs queue |
| GET  | `/api/customs/queue/stream` | SSE — Customs queue updates |
| POST | `/api/customs/{id}/escalate-to-tax` | Move an item from the Customs queue to the Tax queue |
| POST | `/api/customs/{id}/decide` | Body `{action: "release"\|"retain"}`. Terminal decision. Publishes `AGENT_RELEASE_EVENT` or `AGENT_RETAIN_EVENT` and writes the audit trail (with `custom_override = true` if the decision differs from the Tax recommendation). |

### Tax Office (Revenue Guardian Tax Authority page)

| Method | Endpoint | Description |
|---|---|---|
| GET  | `/api/tax/queue` | Snapshot of the live Tax queue |
| GET  | `/api/tax/queue/stream` | SSE — Tax queue updates |
| POST | `/api/tax/{id}/run-agent` | Trigger the VAT Fraud Detection Agent on a Tax queue item. Returns 202; the verdict lands via the SSE stream when ready. Publishes `AI_ANALYSIS_EVENT` so the data hub writer populates `line_item_ai_analysis`. |
| POST | `/api/tax/{id}/recommend` | Body `{recommendation: "release"\|"retain"}`. Non-binding recommendation that transfers the item back to the Customs queue. |

### Simulation control

| Method | Endpoint | Description |
|---|---|---|
| GET  | `/api/simulation/status` | Simulation state + progress |
| GET  | `/api/simulation/pipeline` | Per-topic event counts, queue sizes, Customs/Tax queue depths, risk-score breakdown |
| GET  | `/api/simulation/stream` | SSE pushing consolidated `{status, pipeline}` snapshots at ~5 Hz |
| POST | `/api/simulation/start` | Start simulation |
| POST | `/api/simulation/pause` | Pause |
| POST | `/api/simulation/resume` | Resume |
| POST | `/api/simulation/speed` | Body `{speed: <float>}` (sim-sec per real-sec, capped between MIN_SPEED and MAX_SPEED) |
| POST | `/api/simulation/reset` | Reset to start (preserves historical seed data) |

---

## License

Demo project — European Commission Taxation and Customs Union simulation.
