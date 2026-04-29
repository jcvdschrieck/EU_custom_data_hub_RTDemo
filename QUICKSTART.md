# Quickstart — for the demoer

A one-page guide to running and showcasing the EU Custom Data Hub
demo. **For installation, see [INSTALL.md](INSTALL.md).** For
hardware requirements see [HARDWARE.md](HARDWARE.md). This file is
pure runtime + showcase notes for someone who already has the demo
installed.

---

## 1. Launch

Two terminal windows. The launcher script handles both:

```bash
# macOS / Linux
./run.sh
```

```powershell
# Windows
.\run.ps1
```

> **Don't launch from inside PyCharm or any IDE.** Memory use roughly
> doubles (≈ 2 GB instead of ≈ 300 MB) when uvicorn runs under the IDE
> debugger. Plain Terminal / PowerShell only.

Two services come up. Open both:

| Service | URL | Role |
|---|---|---|
| FastAPI backend + simulation control | <http://localhost:8505/simulation> | Click **▶ Start** to begin |
| C&T operator dashboard | <http://localhost:8080/customs-authority> | Where cases land |

If either URL doesn't load, see [INSTALL.md § Troubleshooting](INSTALL.md#8-troubleshooting).

---

## 2. The two showcase cases

Both arrive on the **Customs Authority** page within the first ~2
sim-minutes after you click ▶ Start.

### Case 1 — ShenZhen TechGlobal × bone-conduction headset (IE)

The **fraud-agent** showcase.

- **Risk score**: ~71 / High
- **AI Suggested Action**: *Submit for Tax Review* (50 % retention
  pattern in past closed cases for this seller × subcategory)
- **Click into the case** → 25 orders, all declared at 0 % VAT under
  EL-08 ("Hearing aid / medical audio device")
- **Click "Submit for Tax Review"** → fires the demo-mode fraud-agent
  override
- **Result in ~5 seconds** (vs ~30 s for the real LLM run):
  - Verdict: `incorrect`
  - Rationale cites VAT Consolidation Act 2010 §46(1)(a) (residual
    23 %) and Schedule 2 §11(3)(b) (deaf-aid carve-out fails — no
    medical certification)
  - VAT gap: ~€489
- **Switch to the Tax Authority page** → case is now there
- **Click into it** → AI suggestion is "AI Uncertain" (the rule's
  retention threshold is 75 %, history is 50 %) — but the fraud
  agent's verdict is visible
- **Open the conversational agent on the right** → ask
  *"Apply Confirm Risk on this case"* → the action agent proposes
  with the actual VAT gap, fraud-verdict citations, and historical
  context, in priority order

### Case 2 — Delhi PharmaExport × "Capsules for daily health support" (IE)

The **vagueness-signal** showcase.

- **Risk score**: ~62 / Medium
- **Stronger signal**: vague description (engine_vagueness = 0.65)
- **AI Suggested Action**: *Request Input from Deemed Importer*
  (vagueness rule fires — 0.60 ≥ 0.50 trigger)
- **Click into the case** → 25 orders, all at €110–130, declared at
  the (correct) IE 0 % rate for CO-06 "Pharmaceutical / medicinal
  product"
- **Demo point**: the seller's invoice description is too generic to
  verify whether the product genuinely qualifies as a medicine —
  hence the request for clarification rather than a retention or a
  release

---

## 3. Self-test checklist before a real demo

- [ ] Sim ▶ Start → ShenZhen and Delhi cases visible on the Customs
      page within 2 real minutes (×1 speed)
- [ ] Submit ShenZhen for Tax Review → 5-second response, verdict
      `incorrect`, citation visible
- [ ] Tax-side conversational agent → "apply Confirm Risk" → proposal
      cites the **real** VAT gap (€~489) and **50 %** retention
- [ ] Customs-side conversational agent → ask *"what's the main risk
      on this case?"* → returns substantive analysis without any
      "I cannot recommend actions" disclaimer leakage
- [ ] **Reset** button works — both demo cases re-form from t=0
      cleanly

If all five tick, you're ready.

---

## 4. Customising during a session

| File | What it controls | Apply changes |
|---|---|---|
| `config.env` | LLM provider, model, API key, ports | Edit, then re-run `install.sh` / `install.ps1` to regenerate the `.env` files. Restart the demo. |
| `data/demo_fraud_overrides.json` | The 5-second canned response on the ShenZhen case (delay, verdict, rationale, source). Set `"enabled": false` to fall through to the real ~30 s LLM run. | Save the file. Picked up on next agent invocation — no restart |
| `scripts/inject_demo_cases.py` | The two demo cases themselves: seller, descriptions, prices, engine signals, historical retention pattern | Edit, run `python scripts/inject_demo_cases.py`, then click **Reset** on the Simulation page |

You **don't** need to touch any other files for a normal demo.

---

## 5. Stopping / restarting

- **Pause / resume** from the Simulation page header.
- **Reset** button on the Simulation page wipes `investigation.db`
  and replays from t=0 (cases re-form from scratch).
- Close the two terminal windows that `run.sh` / `run.ps1` opened to
  fully stop.

---

## 6. Switching LLM provider mid-session

If your laptop loses LM Studio (e.g. you ran out of battery, swapped
to a meeting-room machine), you can switch to a cloud provider in
about a minute:

1. Edit `config.env` → set `LLM_PROVIDER=anthropic` (or `openai`),
   paste an API key into `LLM_API_KEY`.
2. Re-run `./install.sh` (or `.\install.ps1`) — it only re-generates
   `.env` files when nothing else changed; takes ~5 seconds.
3. Restart `./run.sh`.

The fraud agent picks up the new provider on its next call. Your
in-flight cases keep their state.

---

## 7. Pitfalls during a live demo

| Problem | Fast fix |
|---|---|
| Cases don't appear at all | Reload both browser tabs — the Customs / Tax dashboards cache via SSE and a stale connection sometimes misses the first burst |
| Reset on the simulation page doesn't clear the dashboard | Hard-refresh (Ctrl-Shift-R) — clears localStorage |
| Tax agent verdict says "uncertain" | Either LM Studio isn't running (LM-Studio mode), or the cloud key is wrong (check the install log for the **Active LLM configuration** block) |
| Demo cases come up but with default risk scores | The seeder ran without `inject_demo_cases.py`. Click the Reset button (this re-injects them on `simulation.db` regeneration) |

For deeper troubleshooting see [INSTALL.md § Troubleshooting](INSTALL.md#8-troubleshooting).
