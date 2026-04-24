"""EU VAT Hub — Analytics (VAT flows, transaction patterns, country volumes)."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import streamlit as st
from lib.database import stats_by_country, stats_by_tx_type, stats_by_vat_treatment

st.markdown("## 📈 EU VAT Analytics")
st.caption("Cross-country analysis of VAT invoice flows. No risk scoring — pure factual data.")

# ── By country ────────────────────────────────────────────────────────────────
st.markdown("### Invoice Volume & VAT Amounts by Member State")
country_rows = stats_by_country()
if country_rows:
    df = pd.DataFrame([dict(r) for r in country_rows])
    eur = df[df["currency"] == "EUR"].copy()
    non_eur = df[df["currency"] != "EUR"].copy()

    col1, col2 = st.columns(2)
    with col1:
        st.bar_chart(df.set_index("country")[["invoice_count"]].rename(columns={"invoice_count": "Invoices"}))
        st.caption("Invoice count by country")
    with col2:
        if not eur.empty:
            st.bar_chart(eur.set_index("country")[["total_vat"]].rename(columns={"total_vat": "VAT (EUR)"}))
            st.caption("Total VAT collected (EUR countries only)")

    if not non_eur.empty:
        st.caption(f"Non-EUR countries ({', '.join(non_eur['country'].tolist())}) excluded from VAT chart — local currency.")

st.divider()

# ── By transaction type ───────────────────────────────────────────────────────
st.markdown("### Transaction Type & Scope")
tx_rows = stats_by_tx_type()
if tx_rows:
    tx_df = pd.DataFrame([dict(r) for r in tx_rows])
    tx_df["label"] = tx_df["transaction_type"] + " / " + tx_df["transaction_scope"]
    col1, col2 = st.columns(2)
    with col1:
        st.bar_chart(tx_df.set_index("label")[["invoice_count"]].rename(columns={"invoice_count": "Count"}))
        st.caption("Invoice count")
    with col2:
        st.bar_chart(tx_df.set_index("label")[["total_vat"]].rename(columns={"total_vat": "VAT Amount"}))
        st.caption("VAT amount")

st.divider()

# ── By VAT treatment ──────────────────────────────────────────────────────────
st.markdown("### VAT Treatment Distribution")
vt_rows = stats_by_vat_treatment()
if vt_rows:
    vt_df = pd.DataFrame([dict(r) for r in vt_rows])
    vt_df.columns = ["Treatment", "Invoices", "Total Net", "Total VAT"]
    vt_df = vt_df.sort_values("Invoices", ascending=False)

    col1, col2 = st.columns([2, 1])
    with col1:
        st.dataframe(
            vt_df.style.format({"Total Net": "{:,.0f}", "Total VAT": "{:,.0f}"}),
            use_container_width=True, hide_index=True,
        )
    with col2:
        st.bar_chart(vt_df.set_index("Treatment")[["Invoices"]])
