# Quickstart — for the demoer

A one-page guide to install and run the EU Custom Data Hub demo on a fresh
machine. For deeper documentation see `README.md`. This file assumes you only
want to **install, run, and showcase** — not develop.

---

## 1. Prerequisites

| Requirement | Why | How to get it |
|---|---|---|
| Git | clone the repo | https://git-scm.com/downloads (Windows: includes Git Bash) |
| LM Studio | runs the local LLM the fraud-detection agent calls | https://lmstudio.ai |
| Internet (first install only) | downloads Python, Node, npm packages, embedder weights | — |

Python and Node are auto-installed by the installer if missing (`brew` on
macOS, `winget` on Windows, `apt`/`dnf` on Linux). You don't need to install
them by hand.

---

## 2. Install (3 commands)

```powershell
# Windows (PowerShell 5.1+)
git clone https://github.com/jcvdschrieck/EU_custom_data_hub_RTDemo.git
cd EU_custom_data_hub_RTDemo
.\install.ps1
```

```bash
# macOS / Linux
git clone https://github.com/jcvdschrieck/EU_custom_data_hub_RTDemo.git
cd EU_custom_data_hub_RTDemo
./install.sh
```

The installer:

1. Auto-installs Python 3.11+ and Node.js 18+ (if missing).
2. Creates a venv, installs Python dependencies.
3. Builds the internal frontend (Vite → `frontend/dist/`).
4. Installs the C&T dashboard's npm dependencies.
5. Pre-downloads the embedder model (`all-MiniLM-L6-v2`, ~90 MB) so the
   fraud-detection agent runs offline at runtime.
6. Generates `customsandtaxriskmanagemensystem/.env` and
   `vat_fraud_detection/.env` from `config.env`.
7. Seeds the four SQLite databases.

Re-run the installer anytime — it's idempotent.

---

## 3. LM Studio (one-time setup)

1. Open LM Studio → search and download **`mistralai/mistral-7b-instruct-v0.3`**.
2. Load the model in the **Developer** tab.
3. **Important:** open the model's settings panel and slide
   **Context Length** from the default 4096 to **8192**. The default
   4K window is too small for the demo's RAG prompts and will surface
   as a "Context overflow" error.
4. Click **Start Server** (default port 1234, leave as-is).

The fraud-detection agent runs entirely local against this. No API keys, no
internet at runtime.

> **Note:** if LM Studio isn't running, the agent returns `uncertain` with no
> legislation references. Everything else still works.

---

## 4. Run the demo

```powershell
# Windows
.\run.ps1
```

```bash
# macOS / Linux
./run.sh
```

> **Don't launch from inside PyCharm or any IDE.** Running uvicorn through
> PyCharm's Run config wraps the Python process with the IDE's
> debugger / inspector, doubling memory use (≈ 2 GB for PyCharm + the
> Python process combined). Plain PowerShell / Terminal keeps the backend
> at ~ 300 MB.

Two services come up:

| Service | URL | Role |
|---|---|---|
| FastAPI backend + internal pipeline UI | http://localhost:8505/simulation | The control deck — click ▶ Start to begin the simulation |
| C&T operator dashboard | http://localhost:8080/customs-authority | The Irish customs/tax officer view — where cases land |

Open both. Click **▶ Start** on the simulation page.

---

## 5. What to demo (the two showcase cases)

Both arrive on the Customs Authority page in the first ~2 sim-minutes:

### Case 1 — ShenZhen TechGlobal × Bone-conduction headset (IE)

- **Risk score**: ~71 / High
- **AI Suggested Action**: *Submit for Tax Review* (50% retention pattern in past closed cases)
- **Click into the case** → notice the 25 orders, all declared at 0% VAT under EL-08 ("Hearing aid / medical audio device")
- **Click "Submit for Tax Review"** → fires the demo-mode fraud-agent override
- **Result in 5 seconds** (vs ~30 s for the real agent):
  - Verdict: `incorrect`
  - Rationale cites VAT Consolidation Act 2010 §46(1)(a) (residual 23%) and Schedule 2 §11(3)(b) (deaf-aid carve-out fails — no medical certification)
  - VAT gap: ~€489
- **Switch to Tax Authority page** → case is now there
- **Click into it** → AI Suggestion is "AI Uncertain" (because the rule's retention threshold is 75%, history is 50%) — but the fraud agent's verdict is visible
- **Open the conversational agent** on the right → ask *"Apply Confirm Risk on this case"* → the action agent proposes with the actual VAT gap, fraud-verdict citations, and historical context, in priority order

### Case 2 — Delhi PharmaExport × "Capsules for daily health support" (IE)

- **Risk score**: ~62 / Medium
- **Stronger signal**: vague description (engine_vagueness = 0.65)
- **AI Suggested Action**: *Request Input from Deemed Importer* (vagueness rule fires — 0.60 ≥ 0.50 trigger)
- **Click into the case** → 25 orders, all at €110–130, declared at the (correct) IE 0% rate for CO-06 "Pharmaceutical / medicinal product"
- **The vagueness signal is the demo point**: the seller's invoice description is too generic to verify whether the product genuinely qualifies as a medicine — hence the request for clarification

---

## 6. Customising the demo

| File | What it controls | Apply changes |
|---|---|---|
| `config.env` | Backend port, C&T dashboard port, LM Studio URL, LM Studio model identifier | Edit, then re-run `.\install.ps1` to regenerate the `.env` files |
| `data/demo_fraud_overrides.json` | The 5-second canned response on the ShenZhen case (delay, verdict, rationale, source). Set `"enabled": false` to fall through to the real ~30s LLM run. | Save the file. Picked up on next agent invocation — no restart |
| `scripts/inject_demo_cases.py` | The two demo cases themselves: seller, descriptions, prices, engine signals, historical retention pattern | Edit, run `python scripts/inject_demo_cases.py` to refresh, then reset the simulation |

You **don't** need to touch any other files for a normal demo.

---

## 7. Stopping / restarting

- Pause / resume from the Simulation page header.
- **Reset** button on the Simulation page wipes `investigation.db` and replays from t=0.
- Close the two PowerShell / terminal windows that `run.ps1` / `run.sh` opened to fully stop.

---

## 8. Troubleshooting cheat sheet

| Symptom | Likely cause | Fix |
|---|---|---|
| `git pull` says "remote error: upload-pack: not our ref" | A stale submodule pointer from before the vendoring | `git fetch origin && git reset --hard origin/main` |
| `install.ps1` parser errors on `%` operator | You're in cmd.exe instead of PowerShell, or the script is older than the May 2026 quote-fix | Check `git log --oneline install.ps1` is at `4452eb1` or later. `git pull` to update. |
| Long delete commands (`Remove-Item`) hang for hours on Windows | NTFS + AV is slow on `node_modules` / `.venv` | Cancel and use `cmd /c rmdir /s /q <path>` instead |
| Fraud-detection agent returns `uncertain` with no rationale | LM Studio not running, or wrong model loaded | Check LM Studio Developer tab. Verify `LM_STUDIO_MODEL` in `config.env` matches what's loaded. |
| Fraud agent runs but errors with "Cannot send a request, as the client has been closed" | Older code without the offline-mode fix | `git pull` — fix is at commit `41a4e0b` or later |
| Fraud agent errors with "Context overflow" / "n_keep ≥ n_ctx" | LM Studio context length still at default 4096 | Step 3 above — bump to 8192 |
| Customs dashboard shows cases that don't disappear after a sim reset | Frontend localStorage cache is stale | Hard refresh the dashboard tab (Ctrl-Shift-R) |
| Two demo cases don't appear after first install | Old `seed_databases.py` didn't auto-inject them (fixed in commit `a36e772`+) | `git pull` to update + re-run `.\install.ps1` (or run `.venv\Scripts\python seed_databases.py` directly) |
| Memory ≈ 2 GB on PyCharm | Backend launched through PyCharm's Run config (debugger overhead) | Launch via `.\run.ps1` from a plain PowerShell window; close PyCharm during demos |

---

## 9. Self-test checklist before a real demo

- [ ] Sim ▶ Start → ShenZhen and Delhi cases visible on Customs page within 2 real minutes (×1 speed).
- [ ] Submit ShenZhen for Tax Review → 5-second response, verdict `incorrect`, citation visible.
- [ ] Tax-side conversational agent → "apply Confirm Risk" → proposal cites the **real** VAT gap (€~489) and **50%** retention.
- [ ] Customs-side conversational agent → ask "what's the main risk on this case?" → returns substantive analysis without any "I cannot recommend actions" disclaimer leakage.
- [ ] Reset button works — both demo cases re-form from t=0 cleanly.

If all five tick, you're ready.
