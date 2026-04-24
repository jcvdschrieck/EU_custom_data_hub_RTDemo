"""Ireland VAT App — EU VAT Hub Query Interface.

Tabs:
  1. Query & Results  — filtered browse of EU Hub invoices
  2. Increment        — IE invoices in EU Hub after the Irish DB cutoff (March 25)
                        with rule-based pre-classification and VAT analysis queue
  3. Activity Log     — outgoing requests from this app to the EU Hub
"""
from __future__ import annotations

import streamlit as st

if "eu_query_results"       not in st.session_state: st.session_state.eu_query_results       = None
if "eu_detail_result"       not in st.session_state: st.session_state.eu_detail_result       = None
if "eu_selected_invoice_id" not in st.session_state: st.session_state.eu_selected_invoice_id = ""
if "analysis_queue"         not in st.session_state: st.session_state.analysis_queue         = []
if "increment_data"         not in st.session_state: st.session_state.increment_data         = None
if "increment_checks"       not in st.session_state: st.session_state.increment_checks       = {}

st.markdown("## 🌍 EU VAT Hub — Query Interface")
st.caption(
    "Query the central European VAT invoice database from Ireland. "
    "All requests carry `X-Client-Country: IE` and are logged locally."
)

from lib import eu_client

_hub_ok = eu_client.health_check()
if _hub_ok:
    st.success("🟢 EU VAT Hub is online at `http://localhost:8503`")
else:
    st.error(
        "🔴 EU VAT Hub is **offline** — start it with:\n"
        "```\ncd eu_vat_hub && uvicorn api:app --port 8503\n```"
    )

st.divider()

_FLAGS = {
    "IE": "🇮🇪", "FR": "🇫🇷", "DE": "🇩🇪", "BE": "🇧🇪", "NL": "🇳🇱",
    "ES": "🇪🇸", "IT": "🇮🇹", "PL": "🇵🇱", "SE": "🇸🇪", "CZ": "🇨🇿",
}

tab_query, tab_increment, tab_log = st.tabs(
    ["🔍 Query & Results", f"🆕 Increment (after {eu_client.IE_CUTOFF_DATE})", "📡 Activity Log"]
)


# ═══════════════════════════════════════════════════════════════════════════════
with tab_query:
    st.markdown("### Query EU Invoice Database")

    with st.expander("Filters", expanded=True):
        qc1, qc2, qc3 = st.columns(3)
        with qc1:
            q_country = st.selectbox(
                "Country (supplier/customer/reporting)",
                ["All", "IE", "FR", "DE", "BE", "NL", "ES", "IT", "PL", "SE", "CZ"],
                index=0,
            )
            q_tx_type  = st.selectbox("Transaction Type", ["All", "B2B", "B2C"], index=0)
        with qc2:
            q_date_from = st.date_input("From date", value=None, key="eu_from")
            q_date_to   = st.date_input("To date",   value=None, key="eu_to")
        with qc3:
            q_tx_scope = st.selectbox(
                "Scope", ["All", "domestic", "intra_EU", "extra_EU"], index=0
            )
            q_vat_treat = st.selectbox(
                "VAT Treatment",
                ["All", "standard", "reduced", "zero", "exempt", "reverse_charge"],
                index=0,
            )
        q_description = st.text_input("Description contains", placeholder="e.g. consulting, clothing…").strip().lower()
        q_limit = st.slider("Max results", 20, 500, 100, 20)

    if st.button("🔎 Fetch from EU Hub", type="primary", disabled=not _hub_ok):
        with st.spinner("Querying EU VAT Hub…"):
            st.session_state.eu_query_results = eu_client.list_invoices(
                country           = None if q_country == "All" else q_country,
                date_from         = q_date_from.isoformat() if q_date_from else None,
                date_to           = q_date_to.isoformat()   if q_date_to   else None,
                transaction_type  = None if q_tx_type   == "All" else q_tx_type,
                transaction_scope = None if q_tx_scope  == "All" else q_tx_scope,
                vat_treatment     = None if q_vat_treat == "All" else q_vat_treat,
                description       = q_description or None,
                limit             = q_limit,
            )

    results = st.session_state.eu_query_results
    if results is not None:
        items = results.get("items", [])
        total = results.get("total", 0)

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Total matching", f"{total:,}")
        k2.metric("Fetched",        len(items))
        k3.metric("B2B",            sum(1 for i in items if i["transaction_type"] == "B2B"))
        k4.metric("Intra-EU",       sum(1 for i in items if i["transaction_scope"] == "intra_EU"))

        if not items:
            st.info("No invoices matched.")
        else:
            for inv in items:
                sf = _FLAGS.get(inv["supplier_country"], "")
                cf = _FLAGS.get(inv["customer_country"], "")
                label = (
                    f"`{inv['invoice_number']}` | "
                    f"{sf} **{inv['supplier_name']}** → {cf} {inv['customer_name']} | "
                    f"{inv['invoice_date']} | {inv['transaction_type']} · {inv['transaction_scope']} | "
                    f"`{inv['vat_treatment']}` @ `{inv['vat_rate_applied']:.1%}` | "
                    f"{inv['currency']} {inv['gross_amount']:,.0f}"
                )
                with st.expander(label):
                    dc1, dc2, dc3 = st.columns(3)
                    dc1.metric("Net",   f"{inv['currency']} {inv['net_amount']:,.2f}")
                    dc2.metric("VAT",   f"{inv['currency']} {inv['vat_amount']:,.2f}")
                    dc3.metric("Gross", f"{inv['currency']} {inv['gross_amount']:,.2f}")
                    st.markdown(
                        f"**Supplier:** {sf} {inv['supplier_name']} (`{inv['supplier_country']}`) · `{inv['supplier_vat'] or '—'}`  \n"
                        f"**Customer:** {cf} {inv['customer_name']} (`{inv['customer_country']}`) · `{inv['customer_vat'] or '—'}`  \n"
                        f"**Scope:** `{inv['transaction_scope']}` · **Treatment:** `{inv['vat_treatment']}`"
                    )
                    if st.button("📄 Load Full Detail", key=f"det_{inv['invoice_id']}"):
                        st.session_state.eu_selected_invoice_id = inv["invoice_id"]


# ═══════════════════════════════════════════════════════════════════════════════
with tab_increment:
    st.markdown(f"### 🆕 Irish Invoices After {eu_client.IE_CUTOFF_DATE}")
    st.caption(
        f"These are IE supplier records in the EU Hub with date **after {eu_client.IE_CUTOFF_DATE}** "
        "— not yet present in the Irish database. Pre-classified by rule: "
        "known high-error supplier → HIGH, known clean supplier → LOW, new supplier → MEDIUM."
    )

    col_fetch, col_info = st.columns([2, 3])
    with col_fetch:
        fetch_inc = st.button("📥 Fetch Increment from EU Hub", type="primary", disabled=not _hub_ok)

    if fetch_inc:
        with st.spinner("Fetching increment data…"):
            raw = eu_client.fetch_increment(limit=500)
            # Filter to IE supplier records only
            items = [i for i in raw.get("items", []) if i["supplier_country"] == "IE"]
            st.session_state.increment_data   = items
            st.session_state.increment_checks = {i["invoice_id"]: False for i in items}

    inc_items = st.session_state.increment_data

    if inc_items is None:
        st.info("Click **Fetch Increment from EU Hub** to load new Irish invoices.")
    elif not inc_items:
        st.info("No Irish increment records found after the cutoff date.")
    else:
        # ── Pre-classify using Irish DB supplier history ───────────────────────
        from lib.database import _conn as ie_conn

        def _supplier_stats() -> dict[str, dict]:
            try:
                with ie_conn() as c:
                    rows = c.execute("""
                        SELECT supplier_name,
                               COUNT(*) as total,
                               SUM(CASE WHEN overall_verdict != 'correct' THEN 1 ELSE 0 END) as errors
                        FROM invoices GROUP BY supplier_name
                    """).fetchall()
                return {
                    r["supplier_name"]: {
                        "total":      r["total"],
                        "error_rate": r["errors"] / r["total"] if r["total"] > 0 else 0,
                    }
                    for r in rows
                }
            except Exception:
                return {}

        def _pre_classify(inv: dict, stats: dict) -> str:
            sup   = inv.get("supplier_name", "")
            gross = inv.get("gross_amount", 0)
            if sup in stats:
                er = stats[sup]["error_rate"]
                if er >= 0.50 or gross > 15_000: return "HIGH"
                if er >= 0.15:                    return "MEDIUM"
                return "LOW"
            return "MEDIUM"  # unknown supplier → cautious

        sup_stats = _supplier_stats()

        _TIER_EMOJI = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}
        _TIER_BADGE = {
            "HIGH":   ":red[**HIGH**]",
            "MEDIUM": ":orange[**MEDIUM**]",
            "LOW":    ":green[**LOW**]",
        }

        classified = [(inv, _pre_classify(inv, sup_stats)) for inv in inc_items]
        high_n = sum(1 for _, t in classified if t == "HIGH")
        med_n  = sum(1 for _, t in classified if t == "MEDIUM")
        low_n  = sum(1 for _, t in classified if t == "LOW")

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Increment records",  len(classified))
        k2.metric("Pre-classified HIGH",   high_n)
        k3.metric("Pre-classified MEDIUM", med_n)
        k4.metric("Pre-classified LOW",    low_n)

        st.markdown("---")

        # Sort: HIGH first, then MEDIUM, then LOW
        _TIER_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        classified.sort(key=lambda x: (_TIER_ORDER[x[1]], x[0]["invoice_date"]))

        # ── Controls above the list ───────────────────────────────────────────
        ctrl1, ctrl2, ctrl3, ctrl4 = st.columns([1, 1, 1, 3])
        with ctrl1:
            if st.button("☑️ Select all"):
                for inv, _ in classified:
                    iid = inv["invoice_id"]
                    st.session_state.increment_checks[iid] = True
                    st.session_state[f"inc_{iid}"] = True
                st.rerun()
        with ctrl2:
            if st.button("⬜ Select none"):
                for inv, _ in classified:
                    iid = inv["invoice_id"]
                    st.session_state.increment_checks[iid] = False
                    st.session_state[f"inc_{iid}"] = False
                st.rerun()

        n_checked = sum(1 for v in st.session_state.increment_checks.values() if v)
        with ctrl3:
            launch = st.button(
                f"🔬 Launch VAT Analysis ({n_checked} selected)",
                type="primary",
                use_container_width=True,
            )

        if launch:
            if n_checked == 0:
                st.warning(
                    "⚠️ No invoices selected. "
                    "Please tick at least one invoice before launching analysis."
                )
            else:
                selected_ids = [
                    iid for iid, checked in st.session_state.increment_checks.items() if checked
                ]
                invoices_to_queue = []
                with st.spinner(f"Fetching {len(selected_ids)} full invoice(s) from EU Hub…"):
                    for iid in selected_ids:
                        detail = eu_client.get_invoice(iid)
                        if detail:
                            invoices_to_queue.append(eu_client.eu_detail_to_invoice(detail))
                st.session_state.analysis_queue = invoices_to_queue
                for iid in st.session_state.increment_checks:
                    st.session_state.increment_checks[iid] = False
                    st.session_state[f"inc_{iid}"] = False
                st.success(f"✅ {len(invoices_to_queue)} invoice(s) queued. Switching to Invoice Analyzer…")
                st.switch_page("pages/1_Invoice_Analyzer.py")

        st.markdown("**Tick invoices to queue for VAT analysis:**")

        for inv, tier in classified:
            iid   = inv["invoice_id"]
            label = (
                f"{_TIER_EMOJI[tier]} {_TIER_BADGE[tier]} | "
                f"`{inv['invoice_number']}` | **{inv['supplier_name']}** → {inv['customer_name']} | "
                f"{inv['invoice_date']} | EUR {inv['gross_amount']:,.0f}"
            )
            checked = st.session_state.increment_checks.get(iid, False)
            new_checked = st.checkbox(label, value=checked, key=f"inc_{iid}")
            st.session_state.increment_checks[iid] = new_checked

            with st.expander("Details", expanded=False):
                dc1, dc2, dc3 = st.columns(3)
                dc1.metric("Net",   f"EUR {inv['net_amount']:,.2f}")
                dc2.metric("VAT",   f"EUR {inv['vat_amount']:,.2f}")
                dc3.metric("Gross", f"EUR {inv['gross_amount']:,.2f}")
                st.markdown(
                    f"**Treatment:** `{inv['vat_treatment']}` @ `{inv['vat_rate_applied']:.1%}` · "
                    f"**Scope:** `{inv['transaction_scope']}` · **Type:** `{inv['transaction_type']}`  \n"
                    f"**Supplier VAT:** `{inv['supplier_vat'] or '—'}` · "
                    f"**Customer:** {inv['customer_name']} (`{inv['customer_country']}`)"
                )
                if tier in ("HIGH", "MEDIUM") and inv["supplier_name"] in sup_stats:
                    s = sup_stats[inv["supplier_name"]]
                    st.caption(
                        f"ℹ️ Irish DB history: **{s['total']}** invoices, "
                        f"error rate **{s['error_rate']:.0%}**."
                    )



# ═══════════════════════════════════════════════════════════════════════════════
with tab_log:
    st.markdown("### 📡 Ireland → EU Hub Activity Log")
    st.caption("Requests sent from this application to the EU VAT Hub.")

    col_r, col_cl = st.columns([3, 1])
    with col_r:
        auto_ref = st.toggle("Auto-refresh (10 s)", value=False)
    with col_cl:
        if st.button("🗑️ Clear log"):
            eu_client.clear_local_logs()
            st.rerun()

    if auto_ref:
        import time
        time.sleep(10)
        st.rerun()

    local_logs = eu_client.get_local_logs(limit=200)
    if not local_logs:
        st.info("No requests logged yet.")
    else:
        import pandas as pd
        log_df = pd.DataFrame(local_logs)

        lk1, lk2, lk3, lk4 = st.columns(4)
        lk1.metric("Total",         len(log_df))
        lk2.metric("Successful",    int(log_df["success"].sum()))
        lk3.metric("Failed",        int((log_df["success"] == 0).sum()))
        lk4.metric("Avg latency",   f"{log_df['response_time_ms'].mean():.0f} ms")

        display = pd.DataFrame({
            "Timestamp": log_df["timestamp"],
            "Method":    log_df["method"],
            "Endpoint":  log_df["endpoint"],
            "Status":    log_df.apply(
                lambda r: f"✅ {int(r['status_code'])}" if r["success"] and r["status_code"]
                else f"❌ {r['status_code'] or 'ERR'}",
                axis=1,
            ),
            "Records":   log_df["records_returned"],
            "Latency":   log_df["response_time_ms"].map(lambda x: f"{x:.0f} ms"),
            "Error":     log_df["error_message"].fillna(""),
        })
        st.dataframe(display, use_container_width=True, hide_index=True)
