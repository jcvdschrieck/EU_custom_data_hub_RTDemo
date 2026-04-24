"""EU VAT Hub — Overview (factual data only)."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import streamlit as st
from lib.database import count_invoices, stats_by_country, stats_by_tx_type, total_count

st.markdown("## 🌍 EU VAT Hub — Overview")
st.caption(
    "Central repository of factual VAT invoice data submitted by EU member states. "
    "Risk assessment is performed by each country's own system."
)

_COUNTRY_NAMES = {
    "IE": "🇮🇪 Ireland",   "FR": "🇫🇷 France",
    "DE": "🇩🇪 Germany",   "BE": "🇧🇪 Belgium",
    "NL": "🇳🇱 Netherlands","ES": "🇪🇸 Spain",
    "IT": "🇮🇹 Italy",     "PL": "🇵🇱 Poland",
    "SE": "🇸🇪 Sweden",    "CZ": "🇨🇿 Czech Republic",
}

total = total_count()
b2b   = count_invoices(transaction_type="B2B")
intra = count_invoices(transaction_scope="intra_EU")
extra = count_invoices(transaction_scope="extra_EU")

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Total Invoices",    f"{total:,}")
k2.metric("Member States",     "10")
k3.metric("B2B",               f"{b2b:,}")
k4.metric("Intra-EU",          f"{intra:,}")
k5.metric("Extra-EU (Export)", f"{extra:,}")

st.divider()
st.markdown("### Invoices by Member State")

rows = stats_by_country()
if rows:
    df = pd.DataFrame([dict(r) for r in rows])
    df["country_name"] = df["country"].map(lambda c: _COUNTRY_NAMES.get(c, c))
    df_display = df[["country_name", "currency", "invoice_count", "total_net", "total_vat", "total_gross"]].copy()
    df_display.columns = ["Country", "Currency", "Invoices", "Total Net", "Total VAT", "Total Gross"]
    df_display["Total Net"]   = df_display["Total Net"].map(lambda x: f"{x:,.0f}")
    df_display["Total VAT"]   = df_display["Total VAT"].map(lambda x: f"{x:,.0f}")
    df_display["Total Gross"] = df_display["Total Gross"].map(lambda x: f"{x:,.0f}")
    st.dataframe(df_display, use_container_width=True, hide_index=True)

    st.markdown("### Invoice Count by Country")
    st.bar_chart(df.set_index("country_name")[["invoice_count"]].rename(columns={"invoice_count": "Invoices"}))

st.divider()
st.markdown("### Transaction Scope")
tx_rows = stats_by_tx_type()
if tx_rows:
    tx_df = pd.DataFrame([dict(r) for r in tx_rows])
    tx_df["label"] = tx_df["transaction_type"] + " / " + tx_df["transaction_scope"]
    tx_df = tx_df[["label", "invoice_count", "total_net", "total_vat"]].copy()
    tx_df.columns = ["Type / Scope", "Invoices", "Total Net", "Total VAT"]
    tx_df["Total Net"] = tx_df["Total Net"].map(lambda x: f"{x:,.0f}")
    tx_df["Total VAT"] = tx_df["Total VAT"].map(lambda x: f"{x:,.0f}")
    st.dataframe(tx_df, use_container_width=True, hide_index=True)
