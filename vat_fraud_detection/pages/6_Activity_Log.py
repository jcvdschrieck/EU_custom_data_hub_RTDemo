"""Ireland VAT App — LLM Analysis Activity Log."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from lib.analysis_log import clear_logs, get_logs

st.markdown("## 📡 LLM Analysis Activity Log")
st.caption(
    "Every VAT analysis call sent to LM Studio from this application. "
    "Timestamps are in UTC."
)

_VERDICT_EMOJI = {"correct": "✅", "incorrect": "❌", "uncertain": "⚠️"}

col_r, col_cl = st.columns([3, 1])
with col_r:
    auto_ref = st.toggle("Auto-refresh (10 s)", value=False)
with col_cl:
    if st.button("🗑️ Clear log", use_container_width=True):
        clear_logs()
        st.rerun()

if auto_ref:
    import time
    time.sleep(10)
    st.rerun()

rows = get_logs(limit=200)

if not rows:
    st.info("No analysis calls logged yet. Run an analysis from the Invoice Analyzer page.")
    st.stop()

df = pd.DataFrame(rows)

# ── Summary metrics ───────────────────────────────────────────────────────────
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Total analyses",    len(df))
k2.metric("Correct",           int((df["overall_verdict"] == "correct").sum()))
k3.metric("Incorrect",         int((df["overall_verdict"] == "incorrect").sum()))
k4.metric("Uncertain",         int((df["overall_verdict"] == "uncertain").sum()))
k5.metric("Avg latency",       f"{df['response_time_ms'].mean():.0f} ms")

st.divider()

# ── Format timestamp ──────────────────────────────────────────────────────────
def _fmt_ts(ts: str) -> str:
    try:
        dt = pd.to_datetime(ts, utc=True)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return ts

display = pd.DataFrame({
    "Timestamp (UTC)": df["timestamp"].map(_fmt_ts),
    "Invoice":         df["invoice_number"],
    "Supplier":        df["supplier_name"],
    "Lines":           df["line_items_count"],
    "Verdict":         df["overall_verdict"].map(
        lambda v: f"{_VERDICT_EMOJI.get(v, '⚪')} {v}" if v else "—"
    ),
    "Latency":         df["response_time_ms"].map(lambda x: f"{x:.0f} ms"),
    "Model":           df["model_used"],
    "Error":           df["error_message"].fillna(""),
})

st.dataframe(display, use_container_width=True, hide_index=True)
