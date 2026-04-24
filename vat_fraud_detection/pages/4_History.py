"""History — past analyses with option to re-queue for VAT analysis."""
import streamlit as st
import pandas as pd

st.title("📋 Analysis History")

from lib.persistence import load_results, clear_history

if "analysis_queue" not in st.session_state:
    st.session_state.analysis_queue: list = []

col_title, col_btn = st.columns([6, 1])
with col_btn:
    if st.button("🗑️ Clear history", use_container_width=True):
        clear_history()
        st.success("History cleared.")
        st.rerun()

results = load_results()
if not results:
    st.info("No analyses yet. Queue invoices from the EU Query page to get started.")
    st.stop()

_colours = {"correct": "🟢", "incorrect": "🔴", "uncertain": "🟡"}

# Build dataframe
rows = [{
    "Select":    False,
    "Date":      r.analysed_at[:10],
    "Invoice":   r.invoice.invoice_number or r.invoice.source_file,
    "Supplier":  r.invoice.supplier_name,
    "Country":   r.invoice.supplier_country,
    "Lines":     len(r.invoice.line_items),
    "Verdict":   f"{_colours.get(r.overall_verdict, '⚪')} {r.overall_verdict.upper()}",
} for r in results]

df = pd.DataFrame(rows)

# Show table with multi-select checkboxes
st.markdown("Select invoices to re-analyse, then click **Launch VAT Analysis**.")
edited = st.data_editor(
    df,
    column_config={"Select": st.column_config.CheckboxColumn("Select", default=False)},
    use_container_width=True,
    hide_index=True,
    num_rows="fixed",
)

selected_indices = [i for i, row in edited.iterrows() if row["Select"]]

col_a, col_b = st.columns([3, 1])
with col_a:
    st.caption(f"{len(selected_indices)} invoice(s) selected.")
with col_b:
    launch_btn = st.button(
        "🔬 Launch VAT Analysis",
        type="primary",
        use_container_width=True,
        disabled=False,
    )

if launch_btn:
    if not selected_indices:
        st.warning("⚠️ No invoices selected. Please tick at least one invoice before launching analysis.")
    else:
        queued_invoices = [results[i].invoice for i in selected_indices]
        st.session_state.analysis_queue = queued_invoices
        st.success(f"✅ {len(queued_invoices)} invoice(s) added to the analysis queue.")
        st.switch_page("pages/1_Invoice_Analyzer.py")

st.divider()

# ── Detail view ───────────────────────────────────────────────────────────────
selected_single = st.selectbox(
    "Inspect a result in detail",
    options=range(len(results)),
    format_func=lambda i: f"{results[i].invoice.invoice_number or results[i].invoice.source_file} — {results[i].invoice.supplier_name}",
    index=None,
    placeholder="Choose an invoice…",
)

if selected_single is not None:
    r = results[selected_single]
    st.subheader(f"Detail — {r.invoice.supplier_name or r.invoice.source_file}")
    for v in r.verdicts:
        icon = _colours.get(v.verdict, "⚪")
        with st.expander(f"{icon} Line {v.line_item_id}"):
            st.write(v.reasoning)
            if v.legislation_refs:
                st.markdown("**References:**")
                for ref in v.legislation_refs:
                    label = f"**{ref.ref}** — {ref.source}" if ref.ref else ref.source
                    if ref.section: label += f", {ref.section}"
                    if ref.page:    label += f" (p. {ref.page})"
                    if ref.url:     st.markdown(f"{label}  \n[View source]({ref.url})")
                    else:           st.markdown(label)
