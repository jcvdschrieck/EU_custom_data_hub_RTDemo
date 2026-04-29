# EU Custom Data Hub — Real-Time Demo

A real-time simulation of the European Commission's **Taxation and Customs Union** transaction monitoring system. Streams B2C cross-border e-commerce transactions across the EU27, scores them in real time for VAT fraud risk, routes cases through two independent operator queues (Customs and Tax), and persists the full lifecycle into a normalised data hub.

The Customs and Tax operator dashboards ship inside this repo under `customsandtaxriskmanagemensystem/` (vendored from the companion project [C&T Risk Management System](https://github.com/jcvdschrieck/customsandtaxriskmanagemensystem)).

> ## 📦 Are you here to install and demo, not develop?
>
> **Use [INSTALL.md](INSTALL.md)** — it's the SharePoint-distributed
> end-user install guide (download ZIP → extract → run setup → done).
> No Git, no GitHub knowledge required. See **[HARDWARE.md](HARDWARE.md)**
> for system requirements and **[QUICKSTART.md](QUICKSTART.md)** for the
> demo-day cheat sheet.
>
> The rest of this README is the **developer reference**: architecture,
> the Git-based development setup, port wiring, full API reference, and
> project structure.

---

## Architecture overview

```
┌──────────────────────────────────────────────────────────────────────┐
│  FastAPI backend (port 8505)                                         │
│                                                                      │
│  Simulation engine                                                   │
│    └─ Continuous-clock replay of a 15-min compressed April-2026      │
│       window. One Sales Order Event per sim-clock tick.              │
│                                                                      │
│  Pub/sub pipeline (lib/broker.py — in-memory MessageBroker)          │
│    ├─ RT Risk Engine 1   — vat_ratio (declared-vs-expected rate)     │
│    ├─ RT Risk Engine 2   — watchlist (ML supplier risk)              │
│    ├─ RT Risk Engine 3   — ireland_watchlist (IE-only, 1–5 s latency)│
│    ├─ RT Risk Engine 4   — description_vagueness                     │
│    ├─ Sales Order Validation  — field-completeness check             │
│    ├─ Release Factory         — weighted-sum consolidation, routes   │
│    │                            Green / Amber / Red                  │
│    ├─ C&T Risk Management Factory — drains AMBER → cases in          │
│    │                            investigation.db → SSE to operator UI│
│    └─ Exit Process Worker     — terminal events                      │
│                                                                      │
│  Reference + case API                                                │
│    /api/reference            — lookup tables (VAT categories,        │
│                                actions, statuses, risk signals, …)   │
│    /api/rg/cases/*           — case list + detail + SSE stream       │
│    /api/rg/cases/{id}/ask    — dual-agent chat (advisor / action)    │
│    /api/simulation/*         — simulation control + progress         │
└──────────────┬──────────────────────────────────┬────────────────────┘
               │ HTTP / SSE / static              │ HTTP + SSE + CORS
               ▼                                  ▼
┌──────────────────────────────────┐  ┌──────────────────────────────┐
│  Internal React + Vite frontend  │  │  C&T Risk Management System  │
│  served by FastAPI on :8505      │  │  (companion repo, :8080 dev) │
│  (dev mode on :5175 with proxy)  │  │  Vite + React + shadcn/ui    │
│  ├─ Simulation pipeline diagram  │  │  ├─ Customs Authority page   │
│  ├─ Live queue / dashboard       │  │  ├─ Tax Authority page       │
│  ├─ Suspicious transactions      │  │  ├─ Case Review (detail)     │
│  ├─ Agent log                    │  │  └─ Closed Cases archive     │
│  └─ Ireland investigation queue  │  │                              │
└──────────────────────────────────┘  └──────────────────────────────┘
                                                  │ subprocess
                                                  ▼
                              ┌──────────────────────────────────────┐
                              │  vat_fraud_detection/ (vendored)     │
                              │  Local-LLM VAT compliance analyser   │
                              │  with RAG over EU VAT legislation    │
                              │  (LM Studio on :1234)                │
                              └──────────────────────────────────────┘
```

### Two-entity workflow

Customs and Tax are modelled as two **separate offices**, each with its own broker listener, queue, SSE stream, and dashboard page. Routing at the Release Factory:

| Risk Score | Route | Lands in | Operator action |
|---|---|---|---|
| `< 33%` | **Green** → release | terminal event, no case | none — auto-released |
| `33% – 80%` | **Amber** → investigate | `investigation.db` case via the C&T Risk Management Factory | Customs Officer reviews; can release, retain, submit to Tax, or request input from the Deemed Importer. Tax Officer optionally runs the VAT Fraud Detection Agent, then issues a non-binding **recommendation** that returns the case to Customs. |
| `≥ 80%` | **Red** → retain | terminal event, **no case** (retain bypasses C&T by design) | none — auto-retained |

The **C&T frontend filters cases to `Country_Destination == "IE"`** at the read boundary (`backendCaseStore.getAllBackendCases`). Non-IE cases are still produced and persisted, but are hidden from the Irish authority's UI. Replace the `AUTHORITY_COUNTRY` constant to target another member state.

Engine details, weights, thresholds and the `vat_ratio` floor are documented in **[docs/risk_monitoring_rules.md](docs/risk_monitoring_rules.md)**.

### Case-detail AI assistants

Each case-review page exposes a chat that switches between **two agents** per turn:

- **Advisor** (default) — pure Q&A. Never proposes or describes an action.
- **Action-taker** — activated only when the officer clearly demands a decision ("apply Confirm Risk", "submit for tax review", …). Proposes the action, posts a rationale, asks for `yes`/`no` in chat.

Drifting off-topic while an action is pending parks the proposal silently and hands the message back to the advisor — users never feel stuck in a confirmation loop.

### Databases

Four SQLite files under `data/` (all git-ignored):

| File | Purpose |
|---|---|
| `european_custom.db` | ~10 000 historical transactions (Sep 2025 – Feb 2026) + the 3-table normalised data hub (`sales_order_line_item`, `line_item_risk`, `line_item_ai_analysis`) |
| `simulation.db` | April-2026 transactions to replay (~2 300 tx, regenerated from `Context/VAT_Cases_Generated_*.xlsx` + `Context/Fake_ML.xlsx`) |
| `investigation.db` | Live open/closed case store — `Sales_Order` + `Sales_Order_Risk` + `Sales_Order_Case` |
| `historical_cases.db` | ~36 past IE closed cases used by the "Previous Cases" panel and the retention-rate-based recommendation rule |

All four are built or rebuilt by a single `python seed_databases.py` run.

---

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.11+ | |
| Node.js | 18+ | Bundled with npm 9+ |
| LM Studio | Latest | Optional — only needed for the VAT Fraud Detection Agent |

### Installing Node.js

**macOS** — `brew install node` (or download the `.pkg` from [nodejs.org](https://nodejs.org)).

**Windows** — download the LTS installer from [nodejs.org](https://nodejs.org), then open a **new** terminal so PATH is picked up.

**Linux (Debian/Ubuntu)**
```bash
curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
sudo apt-get install -y nodejs
```

---

## Development setup

> The Git-based path below is for **developers working on the project
> itself**. End users installing the demo from SharePoint should use
> [INSTALL.md](INSTALL.md) instead.

### Scripted (recommended for a fresh dev machine)

```bash
# macOS / Linux
git clone https://github.com/jcvdschrieck/EU_custom_data_hub_RTDemo.git
cd EU_custom_data_hub_RTDemo
./install.sh
./run.sh
```

```powershell
# Windows (PowerShell 5.1+)
git clone https://github.com/jcvdschrieck/EU_custom_data_hub_RTDemo.git
cd EU_custom_data_hub_RTDemo
.\install.ps1
.\run.ps1
```

The installer is idempotent and produces the same artefacts as the
SharePoint package: a `.venv/`, built `frontend/dist/`, generated
`.env` files, seeded SQLite databases. Re-run after editing
`config.env` to propagate changes.

Both `vat_fraud_detection/` and `customsandtaxriskmanagemensystem/`
are vendored inside this repo — a single `git clone` pulls the whole
stack. No submodules, no sibling-repo clones.

**Recommended after install (~5 min)** — build the RAG knowledge base
so the VAT Fraud Detection Agent can cite Irish legislation:
```bash
cd vat_fraud_detection && python3 build_knowledge_base.py --minilm-only
```

#### Configurable knobs

`config.env` is the single source of truth for install-time settings.
The full list of keys + acceptable values is documented in
[INSTALL.md § Configure](INSTALL.md#3-configure-one-minute), and
covers:

- **Ports** — `BACKEND_PORT`, `CT_FRONTEND_PORT`
- **LLM provider** — `LLM_PROVIDER` (`lmstudio` / `openai` /
  `anthropic` / `azure`), `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL`
- **Azure-specific** — `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`,
  `AZURE_OPENAI_API_VERSION`
- **LM Studio specifics** — `LM_STUDIO_URL` (legacy alias kept for
  back-compat)

The provider abstraction lives in `vat_fraud_detection/lib/llm_client.py`
and adapts a uniform `chat(...)` call to LM Studio / OpenAI /
Anthropic / Azure-OpenAI. Adding a fifth provider is one new adapter
class plus a branch in the `get_llm_client()` factory.

---

### Manual install (if you prefer step-by-step)

#### 1. Clone the repo

```bash
git clone https://github.com/jcvdschrieck/EU_custom_data_hub_RTDemo.git
cd EU_custom_data_hub_RTDemo
```

`vat_fraud_detection/` ships inside the repo as vendored files — no `--recurse-submodules` or `git submodule init` required.

The `customsandtaxriskmanagemensystem/` and `vat_fraud_detection/` projects are vendored inside this repo — no separate clones required.

### 2. Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Build the internal frontend

```bash
cd frontend
npm install
npm run build
cd ..
```

This compiles the pipeline/dashboard UI into `frontend/dist/`, which FastAPI serves automatically at `http://localhost:8505`.

### 4. Install the C&T frontend dependencies

```bash
cd customsandtaxriskmanagemensystem
npm install
cd ..
```

### 5. VAT Fraud Detection Agent — LM Studio (optional)

The Agent calls a **locally hosted LLM via [LM Studio](https://lmstudio.ai)**. No API key, no internet.

1. Install [LM Studio](https://lmstudio.ai).
2. Download an instruction-tuned model (7–8B is plenty, e.g. `mistralai/mistral-7b-instruct-v0.3`).
3. In LM Studio → **Developer** tab → start the local server (default port **`1234`**).
4. Configure the model identifier:

```bash
cp vat_fraud_detection/.env.example vat_fraud_detection/.env
```

Edit `vat_fraud_detection/.env`:
```
LM_STUDIO_BASE_URL=http://localhost:1234/v1
LM_STUDIO_MODEL=mistralai/mistral-7b-instruct-v0.3
```

List the identifiers LM Studio is currently serving:
```bash
curl http://localhost:1234/v1/models
```

> **Without LM Studio**, the Tax officer can still trigger the agent — every analysis just returns `uncertain` with no legislation references.

**Build the RAG knowledge base** (one-off, ~5 min). The ChromaDB index is not committed (~18 MB):
```bash
cd vat_fraud_detection
python build_knowledge_base.py --minilm-only
cd ..
```

This fetches the sources listed in `ireland_vat_demo_dataset/reference_pack_ireland_vat_sources.pdf` (VAT Consolidation Act 2010, Revenue Tax & Duty Manuals, …), chunks and embeds them. Re-runs are idempotent.

### 6. Seed the databases

```bash
python seed_databases.py
```

Creates the four SQLite files described under [Databases](#databases).

---

## Running

### Backend + internal frontend (standalone)

```bash
python -m uvicorn api:app --host 0.0.0.0 --port 8505
```

Open [http://localhost:8505](http://localhost:8505). Land on the **Simulation** page, click **▶ Start** to begin.

### Integrated mode (backend + C&T operator dashboard)

In two terminals:

```bash
# Terminal 1 — backend + internal frontend
cd EU_custom_data_hub_RTDemo
python -m uvicorn api:app --host 0.0.0.0 --port 8505
```

```bash
# Terminal 2 — C&T operator dashboard
cd EU_custom_data_hub_RTDemo/customsandtaxriskmanagemensystem
npm run dev       # serves on http://localhost:8080
```

Open the pipeline at `http://localhost:8505` and the operator dashboard at `http://localhost:8080`. Cases routed to **investigate** appear on the **Customs Authority** page (IE-destined only) within seconds via SSE. Cases forwarded via *Submit for Tax Review* trigger the VAT Fraud Detection Agent, then appear on the **Tax Authority** page.

CORS on the backend is open (`allow_origins=["*"]`). A simulation reset emits `cases_reset` + `reset` SSE events that the C&T dashboard listens for — it clears its in-memory case map and localStorage so both sides stay in sync without a manual refresh.

### Hot-reload the internal frontend

For edits to `frontend/src/**`, run the Vite dev server instead of re-building:
```bash
cd frontend
npm run dev       # serves on http://localhost:5175, proxies /api to :8505
```

---

## Changing ports

Three services have preselected ports. If any collides with something already running, update these files in lockstep.

### Backend (default `8505`)

Single source of truth — every other component reads from it.

1. `lib/config.py` — set `API_PORT = <new-port>`.
2. `frontend/vite.config.js` — update **both** proxy targets (the `/api` and `/health` blocks) to `http://localhost:<new-port>`.
3. `customsandtaxriskmanagemensystem/.env` — set `VITE_API_BASE_URL=http://localhost:<new-port>`.
4. Start the backend on the new port: `python -m uvicorn api:app --port <new-port>`.

### Internal frontend dev server (default `5175`)

Used only when running `npm run dev` inside `frontend/`. The production build served by FastAPI is unaffected.

- `frontend/vite.config.js` — set `server.port = <new-port>`.

### C&T operator dashboard (default `8080`)

- `customsandtaxriskmanagemensystem/vite.config.ts` — set `server.port = <new-port>`.

### LM Studio (default `1234`)

Change inside LM Studio's **Developer** tab, then update the env file:
- `vat_fraud_detection/.env` — `LM_STUDIO_BASE_URL=http://localhost:<new-port>/v1`.

### Quick "is this port free?" check

```bash
lsof -iTCP:8505 -sTCP:LISTEN                  # macOS / Linux
# or
netstat -an | grep -E "LISTEN.*\.8505\b"     # cross-platform
```

---

## Application pages

Internal frontend served at `:8505`:

| Page | URL | Description |
|---|---|---|
| Simulation | `/simulation` | Pipeline diagram, speed controls, event counts — **start here** |
| Main | `/main` | Live transaction stream (SSE), KPI tiles, active alarms |
| Dashboard | `/dashboard` | VAT metrics, charts by country & category |
| Suspicious | `/suspicious` | Historical transactions flagged by the alarm engine |
| Agent Log | `/agent-log` | Audit history of every Tax-officer agent run with legislation references |
| Ireland Queue | nav dropdown | Per-country investigation queue (Ireland live, others placeholder) |

C&T Risk Management frontend (companion repo, served at `:8080`):

| Page | URL | Description |
|---|---|---|
| Access Portal | `/` | Authority + country selection |
| Customs Authority | `/customs-authority` | Open investigation cases (IE). Actions: release / retain / submit for tax review / request input from Deemed Importer |
| Closed Cases | `/customs-authority/closed` | Archive |
| Case Review | `/customs-authority/case/:id` | Detail: risk signals, AI summary, VAT assessment, orders, previous + correlated cases, dual-agent chat |
| Tax Authority | `/tax-authority` | Cases under tax review — status flips from "AI Processing" to "Ready for Review" when the agent completes |
| Tax Case Review | `/tax-authority/case/:id` | VAT assessment editor with per-(country, subcategory) rate lookup, AI rationale, officer overrides |

---

## Simulation scenario

April-2026 source transactions are rescaled at seed time so their timestamps fall inside a **15-sim-minute window** starting `2026-04-01 00:00:00`. The continuous-clock simulation loop advances `sim_time` smoothly between events:

| Multiplier | sim-sec / real-sec | Wall-clock playback |
|---|---|---|
| **×1** (default) | 1 | 15 sim-min in 15 real-min |
| **×10** | 10 | 15 sim-min in ~1.5 real-min |
| **×100** | 100 | 15 sim-min in ~9 real-sec |

### Embedded investigate clusters (IE destination)

The seeder amplifies each IE investigate cluster to **50–100 orders** that share a 6-token Jaccard anchor in their descriptions, so they aggregate into a single open case on the C&T dashboard. Every order in a case is within **25% of every other order's price** (cluster-level base ± ~11%). Notable clusters:

| Seller (non-EU producer) | Category | Pattern |
|---|---|---|
| Mumbai TechTrade Pvt Ltd | Electronics & Accessories | 2 split sub-cases (Jaccard disjoint markers) — demo the Correlated Cases panel |
| Bengaluru ActiveGear Ltd | Clothing & Textiles | 2 split sub-cases — same pattern |
| Delhi PharmaExport Pvt Ltd | Cosmetics & Personal Care | Single case, VAT-ratio flagged |
| Hyderabad KidsEdu Traders | Books, Publications & Digital Content | Single case, high ML + vagueness |

Release/retain rows keep their raw xlsx-derived values and do not cluster.

---

## Project structure

```
EU_custom_data_hub_RTDemo/
├── api.py                       # FastAPI app — endpoints, pub/sub pipeline, SSE, lifespan
├── seed_databases.py            # One-time DB seeder (all four SQLite files)
├── requirements.txt
├── lib/
│   ├── broker.py                # Pub/sub MessageBroker + topic constants
│   ├── config.py                # Ports, paths, simulation time window
│   ├── database.py              # SQLite schema (legacy + data hub + reference) + helpers
│   ├── new_seeder.py            # xlsx → simulation.db seeder (cluster sizing + value clustering)
│   ├── historical_seeder.py     # historical_cases.db seeder
│   ├── seeder.py                # european_custom.db historical seeder
│   ├── vat_dataset.py           # VAT categories, subcategories, per-country rate lookup
│   ├── simulator.py             # Async event-driven simulation loop
│   ├── alarm_checker.py         # VAT-ratio deviation alarm engine
│   ├── regions.py               # Country → UN geoscheme sub-region map
│   └── agent_bridge.py          # Subprocess bridge → vat_fraud_detection
├── frontend/                    # Internal React + Vite UI (built → FastAPI serves dist/)
├── customsandtaxriskmanagemensystem/  # Vendored — C&T operator dashboard (React + Vite)
│   ├── src/pages/               # Customs / Tax Authority pages, Case Review
│   ├── src/lib/                 # apiClient, caseStore, referenceStore, caseEnum
│   └── vite.config.ts           # Dev server port driven by PORT env var
├── vat_fraud_detection/         # Vendored — local LLM VAT compliance agent
│   ├── lib/analyser.py          # Core AI analysis engine
│   ├── build_knowledge_base.py  # RAG index builder
│   └── prompts/                 # LLM system prompts
├── docs/
│   └── risk_monitoring_rules.md # Engine weights, thresholds, pre-baking details
└── data/                        # SQLite + event files (git-ignored)
    ├── european_custom.db
    ├── simulation.db
    ├── investigation.db
    ├── historical_cases.db
    └── events/                  # Per-topic JSON event files (flushed on reset)
```

---

## API reference

### Reference + case endpoints (consumed by the C&T dashboard)

| Method | Endpoint | Description |
|---|---|---|
| GET  | `/api/reference` | Lookup bundle: VAT categories, subcategories, per-country VAT rates, customs/tax actions, statuses, risk signals, thresholds |
| GET  | `/api/rg/cases` | All investigation cases (hydrated with orders + risk scores) |
| GET  | `/api/rg/cases/{id}` | Single case detail |
| GET  | `/api/rg/cases/stream` | SSE — `new_case`, `case_updated`, `cases_reset` |
| GET  | `/api/rg/cases/{id}/previous` | Previous closed cases from the same seller |
| GET  | `/api/rg/cases/{id}/correlated` | Open cases with the same declared category |
| POST | `/api/rg/cases/{id}/customs-action` | Body `{action: "retainment"\|"release"\|"tax_review"\|"input_requested", comment?, officer?}` |
| POST | `/api/rg/cases/{id}/tax-action` | Body `{action: "risk_confirmed"\|"no_limited_risk", comment?, officer?}` |
| POST | `/api/rg/cases/{id}/communication` | Append to the case's communication log |
| POST | `/api/rg/cases/{id}/ask` | Body `{question, role: "customs"\|"tax", mode?: "advisor"\|"action"}`. Returns `{answer, proposal, mode}` — advisor never sets proposal; action sets it when the officer clearly demanded one |
| GET  | `/api/rg/agent/queue` | Live agent queue depth + case currently under analysis |

### Live data

| Method | Endpoint | Description |
|---|---|---|
| GET  | `/health` | Health check + total record count |
| GET  | `/api/queue` | Latest 30 transactions (REST snapshot) |
| GET  | `/api/queue/stream` | SSE — one transaction per event |
| GET  | `/api/transactions` | Paginated historical query |
| GET  | `/api/transactions/{id}/timeline` | Full broker-event history for a transaction |
| GET  | `/api/metrics` | VAT aggregates with filters |
| GET  | `/api/alarms` | Alarm list (`?active_only=true` optional) |
| GET  | `/api/suspicious` | Last 50 suspicious transactions |
| GET  | `/api/agent-log` | Audit history of every Tax-officer agent run |
| GET  | `/api/ireland-queue` | Cases queued for Irish Revenue investigation |
| GET  | `/api/ireland-case/{id}` | Full case detail |

### Simulation control

| Method | Endpoint | Description |
|---|---|---|
| GET  | `/api/simulation/status` | Simulation state + progress |
| GET  | `/api/simulation/pipeline` | Per-topic event counts, queue sizes, Customs/Tax depths, risk-score breakdown |
| GET  | `/api/simulation/stream` | SSE pushing `{status, pipeline}` at ~5 Hz |
| POST | `/api/simulation/start` | Start simulation |
| POST | `/api/simulation/pause` | Pause |
| POST | `/api/simulation/resume` | Resume |
| POST | `/api/simulation/speed` | Body `{speed: <float>}` (between `MIN_SPEED` and `MAX_SPEED`) |
| POST | `/api/simulation/reset` | Reset to start (preserves seed data) |

---

## License

Demo project — European Commission Taxation and Customs Union simulation.
