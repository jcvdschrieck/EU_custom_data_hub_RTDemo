EU CUSTOM DATA HUB — OVERVIEW
==============================

This application is a real-time demonstration of how the European
Commission's Taxation and Customs Union monitors cross-border
e-commerce transactions for VAT fraud risk.

It simulates a 15-minute window of live transaction data flowing
through an automated risk-scoring pipeline, with two separate
operator teams — Customs and Tax — each reviewing cases on their
own dashboard.

To install and launch the application, see INSTALL.txt.
For a step-by-step demo guide, see QUICKSTART.txt (if available)
or continue reading below.


-------------------------------------------------------------------
WHAT THE APPLICATION SHOWS
-------------------------------------------------------------------

B2C e-commerce orders from non-EU sellers (China, India, etc.)
arrive continuously on screen. Each order is automatically scored
for VAT fraud risk based on four signals:

  1. VAT rate declared vs. the expected rate for that product category
  2. Supplier watchlist match (AI-based supplier risk score)
  3. Ireland-specific watchlist (for IE-destination orders)
  4. Description vagueness (how clearly the product is described)

Orders that score above a threshold are grouped into investigation
cases and routed to the operator dashboards.


-------------------------------------------------------------------
THE TWO DASHBOARDS
-------------------------------------------------------------------

CUSTOMS AUTHORITY (http://localhost:8080/customs-authority)
  The first line of review. A Customs officer sees all flagged cases
  for Irish-destination shipments. For each case, the officer can:
    - Release the shipment (no issue found)
    - Retain the shipment (hold it pending review)
    - Submit for Tax Review (send to the Tax Authority)
    - Request input from the importer

TAX AUTHORITY (http://localhost:8080 -> Tax Authority tab)
  Receives cases forwarded by Customs. A Tax officer can run the
  AI fraud-detection agent, which analyses the declared VAT category
  against Irish VAT legislation and returns a verdict with citations.

SIMULATION CONTROL PANEL (http://localhost:8505/simulation)
  Shows the live pipeline: transaction counts, risk scores, queue
  depths, and engine status. Use the Play / Pause / Reset buttons
  and the speed slider to control the simulation.


-------------------------------------------------------------------
THE TWO DEMO CASES
-------------------------------------------------------------------

Two pre-configured cases are designed to illustrate the key features.
They appear on the Customs Authority dashboard within the first two
minutes of simulation time (at x1 speed).

CASE 1 — SHENZEN TECHGLOBAL x BONE-CONDUCTION HEADSET
  Risk score: ~71 (High)
  25 orders, all declared at 0% VAT under category "Hearing aid /
  medical audio device" (EL-08).

  What to show:
  1. Click into the case. Notice the AI Suggested Action:
     "Submit for Tax Review" (based on a 50% retention rate in
     similar past cases — not high enough to auto-retain, not low
     enough to release).
  2. Click "Submit for Tax Review".
  3. Within 5 seconds, the fraud-detection agent returns:
       - Verdict: INCORRECT
       - Reason: bone-conduction headsets do not qualify as medical
         audio devices under VAT Consolidation Act 2010. The
         Schedule 2 medical carve-out requires certification that
         was not provided.
       - Estimated VAT gap: approximately 489 euros
  4. Switch to the Tax Authority page. The case appears there.
  5. Open the conversational assistant (right side of the case view)
     and type: "Apply Confirm Risk on this case"
     The assistant proposes the action with the VAT gap, fraud
     verdict, and historical context filled in automatically.

CASE 2 — DELHI PHARMAEXPORT x "CAPSULES FOR DAILY HEALTH SUPPORT"
  Risk score: ~62 (Medium)
  25 orders, declared at 0% VAT under "Pharmaceutical / medicinal
  product" (CO-06) — which is the correct Irish rate.

  What to show:
  The risk flag here is description vagueness (score 0.65, above the
  0.50 trigger). The product description is too generic to confirm
  whether it genuinely qualifies as a pharmaceutical product.
  The AI Suggested Action is "Request Input from Deemed Importer".

  This case demonstrates that risk is not always about the wrong VAT
  rate — sometimes the issue is insufficient information to verify
  the declared category.


-------------------------------------------------------------------
CONTROLLING THE SIMULATION
-------------------------------------------------------------------

All controls are on the Simulation page (http://localhost:8505/simulation).

  Play (triangle button)    Start or resume the simulation
  Pause                     Freeze the simulation at any point
  Reset                     Wipe all cases and restart from scratch
                            (the two demo cases re-appear automatically)
  Speed slider              x1 = real time (15 sim-minutes = 15 real
                            minutes). x10 = 10x faster. x100 = 9 seconds
                            for the full 15-minute window.

For a live demo, x1 speed is recommended so the cases appear
gradually and naturally.


-------------------------------------------------------------------
THE CONVERSATIONAL ASSISTANT
-------------------------------------------------------------------

Each case-review page has a chat panel on the right side. It runs
two modes automatically:

  ADVISOR mode (default)
    Answers questions about the case: risk signals, VAT rules,
    historical context, similar past cases. Never proposes actions.
    Example questions:
      "What is the main risk on this case?"
      "How does this compare to previous cases from this seller?"
      "What does Irish VAT law say about medical audio devices?"

  ACTION mode (triggered automatically)
    Activated when the officer clearly asks for a decision.
    Example phrases that trigger it:
      "Apply Confirm Risk on this case"
      "Submit this for tax review"
      "Release this case"
    The assistant proposes the action with a rationale and asks
    for confirmation (yes / no) before proceeding.

If you ask an off-topic question while an action is pending, the
assistant parks the proposal and answers your question. It will not
force you into a confirmation loop.


-------------------------------------------------------------------
SCREENS OVERVIEW
-------------------------------------------------------------------

At http://localhost:8505 (control panel):

  /simulation       Pipeline diagram, speed controls, event counts.
                    Start here.
  /main             Live transaction stream with KPI tiles.
  /dashboard        VAT metrics and charts by country and category.
  /suspicious       Historical transactions flagged by the alarm engine.
  /agent-log        Audit trail of every AI fraud-detection run,
                    with legislation references.

At http://localhost:8080 (operator dashboard):

  /customs-authority          Open cases for the Irish Customs office.
  /customs-authority/closed   Archive of closed cases.
  /tax-authority              Cases under tax review.
  Case detail pages           Risk signals, AI summary, VAT assessment,
                              order list, previous cases from the same
                              seller, and the conversational assistant.


-------------------------------------------------------------------
RESETTING BETWEEN DEMOS
-------------------------------------------------------------------

To replay from the beginning:
  1. Click the Reset button on the Simulation page.
  2. Click Play.
  The two demo cases will re-appear within the first two minutes.

If the Customs or Tax dashboard still shows old cases after a reset:
  Press Ctrl + Shift + R in the browser tab to force a full refresh.


-------------------------------------------------------------------
STOPPING THE APPLICATION
-------------------------------------------------------------------

Close the PowerShell window that was opened by .\run.ps1.
Both services (the control panel and the operator dashboard) will stop.


-------------------------------------------------------------------
FOR TECHNICAL QUESTIONS
-------------------------------------------------------------------

See README.md for the full developer documentation, including the
system architecture, API reference, and development setup.
Contact the project maintainer for support.
