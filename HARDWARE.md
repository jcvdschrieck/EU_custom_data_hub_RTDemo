# Hardware & software requirements

The EU Custom Data Hub demo runs a multi-component stack: a FastAPI
backend with an in-memory pub/sub pipeline, two Vite/React frontends,
four SQLite databases, and an optional locally-hosted LLM. How much
machine you need depends primarily on **how you run the LLM**.

---

## At a glance

| Tier | RAM | Disk free | CPU | Use case |
|---|---:|---:|---|---|
| **A. No LLM** | 4 GB | 4 GB | dual-core | Pipeline + dashboards work; the fraud agent always returns "uncertain" |
| **B. Cloud LLM** (API key) | 8 GB | 4 GB | dual-core | OpenAI / Anthropic / Azure — full demo, network required |
| **C. Local LLM 7B** (LM Studio) | **16 GB** | 10 GB | quad-core, AVX2 | Full demo, fully local, no network |
| **D. Local LLM 13B** (LM Studio) | 32 GB | 18 GB | quad-core, AVX2 | Higher-quality verdicts, more cost |

Pick the tier that matches your laptop. **Tier B (Cloud LLM)** is the
easiest first run — any 8 GB machine can demo with an OpenAI or
Anthropic API key.

---

## Operating systems

| OS | Status | Notes |
|---|---|---|
| **Windows 10** (build 19041+) | Supported | PowerShell 5.1 ships in-box; install scripts handle winget |
| **Windows 11** | Supported | Recommended on Windows |
| **macOS 12 Monterey** | Supported | Apple Silicon **and** Intel; `brew` used for prereqs |
| **macOS 13 / 14 / 15** | Supported | Apple Silicon faster on local LLMs (Metal acceleration) |
| **Ubuntu 22.04 LTS** | Supported | `apt` used for prereqs |
| **Ubuntu 24.04 LTS** | Supported | |
| **Debian 12** | Supported | |
| **Fedora 40+ / RHEL 9** | Best-effort | `dnf` path exists but lightly tested |
| **Older Windows / macOS / Linux** | Not supported | Python 3.11+ unavailable |

---

## Detailed resource breakdown

### Tier A — No LLM (any modern machine)

The simulation, both dashboards, the four risk engines, and the case
flow all work without an LLM. The fraud-detection agent simply
returns `verdict="uncertain"` with no legislation citations whenever
the Tax officer triggers it.

- **CPU:** dual-core 2.0 GHz+ (~10 years old still works)
- **RAM:** 4 GB (1 GB Python + 0.5 GB Node + 1 GB browser + 1.5 GB OS overhead)
- **Disk:** 4 GB free (project + venv + node_modules + databases)
- **GPU:** none required
- **Network:** required at install; offline at runtime

### Tier B — Cloud LLM (recommended for first install)

You set `LLM_PROVIDER=openai` (or `anthropic` / `azure`) in
`config.env` and paste an API key. All LLM compute happens in the
cloud — your laptop is just running the demo shell.

- **CPU:** dual-core 2.0 GHz+
- **RAM:** 8 GB (same as Tier A + a small request-buffer overhead)
- **Disk:** 4 GB free
- **Network:** **required at runtime** for every agent run (~3 kB
  request, ~20 kB response, < 1 s typical latency)
- **Cost:** per-request — typically $0.001–0.05 per case depending on
  the chosen model. Mistral 7B-Instruct via Together / Groq is the
  cheapest cloud option; Claude Sonnet 4.6 / GPT-4o the most capable.

### Tier C — Local 7B model (LM Studio)

You run a 7B-parameter quantised model (e.g.
`mistralai/mistral-7b-instruct-v0.3` Q4_K_M) inside LM Studio on the
same machine. The demo's default. No internet at runtime, no
per-request cost, but the laptop has to host the model.

- **CPU:** quad-core with **AVX2** instruction set (Intel Haswell 2013+
  or AMD Excavator 2015+; check with `cat /proc/cpuinfo | grep avx2`
  on Linux, `sysctl -a | grep machdep.cpu.features` on macOS)
- **RAM:** **16 GB** total. The 7B model itself wants ~6 GB at
  Q4_K_M quantisation, plus ~3 GB for KV cache at 8 K context, plus
  the 4 GB of pipeline overhead from Tier A.
- **Disk:** 10 GB free (4 GB project + ~4–5 GB for the .gguf model +
  embedder weights ~90 MB + RAG index ~18 MB)
- **GPU:** optional but **recommended**. Apple Silicon uses Metal
  automatically. On Windows / Linux, an NVIDIA GPU with ≥ 8 GB VRAM
  speeds inference ~5×. CPU-only is workable but each agent run takes
  ~30 s instead of ~5 s.
- **Network:** none required at runtime

### Tier D — Local 13B model (LM Studio)

Same setup as Tier C but with a larger model (e.g.
`meta-llama/llama-3.1-8b-instruct` or
`microsoft/phi-3.5-medium-instruct`). Higher-quality reasoning, longer
inference time. Mostly useful when you want to evaluate verdicts
against a stronger model.

- **CPU:** quad-core with AVX2 (same)
- **RAM:** **32 GB** total. The 13B model wants ~10 GB at Q4_K_M,
  plus ~5 GB KV cache at 8 K context, plus 4 GB pipeline overhead.
- **Disk:** 18 GB free (project + ~12–14 GB for the .gguf model)
- **GPU:** strongly recommended. NVIDIA ≥ 12 GB VRAM ideal.

---

## What each component costs at runtime

| Component | RAM | CPU | Notes |
|---|---:|---|---|
| FastAPI backend (`api.py`) | ~300 MB | low (event-driven) | Pub/sub pipeline + simulation loop |
| Internal frontend (built, served by FastAPI) | 0 | 0 | Pre-built static files; no extra process |
| C&T dashboard (`npm run dev`) | ~250 MB | low | Vite dev server. Could be replaced by `npm run build` for production |
| LM Studio + 7B model (Tier C) | ~9 GB | high during inference | Idle consumption is small; spikes during agent runs |
| LM Studio + 13B model (Tier D) | ~15 GB | high during inference | |
| Embedder (`all-MiniLM-L6-v2`, in-process) | ~120 MB | low | Cached on first install |
| ChromaDB RAG index | ~50 MB | low | Read-only at runtime |
| SQLite databases (4 files) | minimal | minimal | Open-on-demand by uvicorn workers |

**Browser tabs**: each Chrome / Edge tab on the C&T dashboard takes
~200–400 MB. Plan for ~600 MB of browser memory if you keep the
Customs and Tax tabs open simultaneously.

---

## Network requirements

| When | What | Why |
|---|---|---|
| First install | Up to ~2 GB download | Python + Node + pip wheels + npm packages + embedder weights + (optional) LM Studio model |
| Subsequent installs | None | Everything cached locally |
| Tier A or C runtime | None | Fully offline once installed |
| Tier B runtime | LLM provider API | One outbound HTTPS call per agent run, ~30 KB / call |
| Tier D runtime | None | Fully offline |

For air-gapped environments, **Tier C (local LM Studio)** is the only
option that works fully offline at both install and runtime — but the
install itself still needs internet once to fetch dependencies and the
model. Plan a one-time online install on a staging machine, then
ship the resulting tree (or our packaged installer) to the air-gapped
target.

---

## Choosing a tier

```
                ┌──────────────────────────────────────┐
                │ Do you have an OpenAI / Anthropic /  │
                │ Azure API key you can use?           │
                └──────────┬─────────────────┬─────────┘
                           │ yes             │ no
                           ▼                 ▼
                ┌──────────────────┐  ┌──────────────────┐
                │ ≥ 8 GB RAM?      │  │ ≥ 16 GB RAM      │
                │                  │  │ + AVX2 CPU?      │
                └──┬─────────────┬─┘  └──┬─────────────┬─┘
                   │ yes         │ no    │ yes         │ no
                   ▼             │       ▼             ▼
              ┌─────────┐        │  ┌─────────┐  ┌──────────────┐
              │ TIER B  │        │  │ TIER C  │  │ TIER A       │
              │ Cloud   │        │  │ Local   │  │ No LLM       │
              │ LLM     │        │  │ 7B      │  │ ("uncertain")│
              └─────────┘        │  └─────────┘  └──────────────┘
                                 └─→ same as no-key path above
```

**TL;DR:** any 8 GB laptop with an API key works. For local LLM you
need 16 GB + a modern CPU.

---

## Self-test after install

After running `setup.sh` / `setup.ps1`, the installer prints an
**Active LLM configuration** block. Verify:

- The provider line matches what you set in `config.env`.
- For cloud providers, the API key shows as `****<last-4>` (proving
  it's stored).
- For LM Studio, the URL is reachable (`curl http://localhost:1234/v1/models`
  should return a JSON model list once LM Studio is started).

If the demo's fraud-detection agent returns `uncertain` despite a
cloud key being configured, the most common causes are listed in
`INSTALL.md` § Troubleshooting.
