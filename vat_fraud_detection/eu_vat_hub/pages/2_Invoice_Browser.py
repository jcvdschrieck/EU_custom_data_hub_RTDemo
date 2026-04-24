"""EU VAT Hub — Invoice Browser (factual invoice data, no risk scoring)."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from lib.database import count_invoices, get_countries, get_line_items, query_invoices

st.markdown("## 🗂️ Invoice Browser")
st.caption("Factual VAT invoice data across all member states. No risk classification is held here.")

_FLAGS = {
    "IE": "🇮🇪", "FR": "🇫🇷", "DE": "🇩🇪", "BE": "🇧🇪", "NL": "🇳🇱",
    "ES": "🇪🇸", "IT": "🇮🇹", "PL": "🇵🇱", "SE": "🇸🇪", "CZ": "🇨🇿",
}

all_countries = get_countries()
country_opts  = [f"{_FLAGS.get(c, '')} {c}" for c in all_countries]

with st.expander("Filters", expanded=True):
    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        sel_display  = st.multiselect("Country", options=country_opts, default=[])
        sel_countries = [c.split()[-1] for c in sel_display]
    with fc2:
        date_from = st.date_input("From date", value=None)
        date_to   = st.date_input("To date",   value=None)
    with fc3:
        sel_tx_type  = st.selectbox("Transaction Type",  ["All", "B2B", "B2C"], index=0)
        sel_tx_scope = st.selectbox("Scope", ["All", "domestic", "intra_EU", "extra_EU"], index=0)
        sel_vat_treat = st.selectbox(
            "VAT Treatment", ["All", "standard", "reduced", "zero", "exempt", "reverse_charge"], index=0
        )
    desc_filter = st.text_input("Description contains", placeholder="e.g. consulting, clothing…").strip().lower()

kwargs = dict(
    country           = sel_countries[0] if len(sel_countries) == 1 else None,
    date_from         = date_from.isoformat() if date_from else None,
    date_to           = date_to.isoformat()   if date_to   else None,
    transaction_type  = None if sel_tx_type  == "All" else sel_tx_type,
    transaction_scope = None if sel_tx_scope == "All" else sel_tx_scope,
    vat_treatment     = None if sel_vat_treat == "All" else sel_vat_treat,
    description       = desc_filter or None,
)

total = count_invoices(**kwargs)
rows  = query_invoices(**kwargs, limit=50)

k1, k2, k3, k4 = st.columns(4)
k1.metric("Matching",   f"{total:,}")
k2.metric("Shown",      len(rows))
k3.metric("B2B",        sum(1 for r in rows if r["transaction_type"] == "B2B"))
k4.metric("Intra-EU",   sum(1 for r in rows if r["transaction_scope"] == "intra_EU"))

st.caption(f"Showing first {len(rows)} of {total:,} matching records.")
st.divider()

if not rows:
    st.info("No invoices match the selected filters.")
    st.stop()

for row in rows:
    sf = _FLAGS.get(row["supplier_country"], "")
    cf = _FLAGS.get(row["customer_country"], "")
    label = (
        f"`{row['invoice_number']}` | "
        f"{sf} **{row['supplier_name']}** → {cf} {row['customer_name']} | "
        f"{row['invoice_date']} | {row['transaction_type']} · {row['transaction_scope']} | "
        f"`{row['vat_treatment']}` @ `{row['vat_rate_applied']:.1%}` | "
        f"{row['currency']} {row['gross_amount']:,.0f}"
    )
    with st.expander(label):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Net",       f"{row['currency']} {row['net_amount']:,.2f}")
        c2.metric("VAT",       f"{row['currency']} {row['vat_amount']:,.2f}")
        c3.metric("Gross",     f"{row['currency']} {row['gross_amount']:,.2f}")
        c4.metric("VAT Rate",  f"{row['vat_rate_applied']:.1%}")

        st.markdown(
            f"**Supplier:** {sf} {row['supplier_name']} (`{row['supplier_country']}`) · `{row['supplier_vat'] or '—'}`  \n"
            f"**Customer:** {cf} {row['customer_name']} (`{row['customer_country']}`) · `{row['customer_vat'] or '—'}`  \n"
            f"**Treatment:** `{row['vat_treatment']}` · **Scope:** `{row['transaction_scope']}`"
        )

        li_rows = get_line_items(row["invoice_id"])
        if li_rows:
            st.markdown("**Line Items**")
            for li in li_rows:
                st.markdown(
                    f"- {li['description']} ({li['product_category']}) "
                    f"— {li['quantity']:.0f} × {row['currency']} {li['unit_price']:,.2f} "
                    f"@ `{li['vat_rate_applied']:.1%}` "
                    f"= Net {row['currency']} {li['net_amount']:,.2f} + VAT {row['currency']} {li['vat_amount']:,.2f}"
                )
        st.caption(f"ID: `{row['invoice_id']}`")
