"""EU VAT Hub — API Activity Log (inbound requests from member states)."""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import streamlit as st
from lib.database import get_api_logs

st.markdown("## 📡 API Activity Log")
st.caption(
    "All inbound API requests from member-state applications. "
    "Auto-refreshes every 10 seconds."
)

_COUNTRY_FLAGS = {
    "IE": "🇮🇪", "FR": "🇫🇷", "DE": "🇩🇪", "BE": "🇧🇪", "NL": "🇳🇱",
    "ES": "🇪🇸", "IT": "🇮🇹", "PL": "🇵🇱", "SE": "🇸🇪", "CZ": "🇨🇿",
}

# Auto-refresh
col_r, col_lim = st.columns([3, 1])
with col_r:
    auto_refresh = st.toggle("Auto-refresh (10 s)", value=False)
with col_lim:
    limit = st.number_input("Records to show", min_value=20, max_value=500, value=100, step=20)

if auto_refresh:
    import time
    st.caption(f"Last refresh: {pd.Timestamp.now().strftime('%H:%M:%S')}")
    time.sleep(10)
    st.rerun()

rows = get_api_logs(limit=int(limit))

if not rows:
    st.info("No API requests logged yet. The log is populated when member states query this hub.")
    st.stop()

# ── Summary metrics ───────────────────────────────────────────────────────────
df = pd.DataFrame([dict(r) for r in rows])

k1, k2, k3, k4 = st.columns(4)
k1.metric("Total requests shown", len(df))
k2.metric("Unique client countries", df["client_country"].nunique())
k3.metric("Avg response (ms)", f"{df['response_time_ms'].mean():.0f}")
k4.metric("Error responses", int((df["status_code"] >= 400).sum()))

st.divider()

# ── Log table ─────────────────────────────────────────────────────────────────
def _fmt_ts(ts: str) -> str:
    try:
        return pd.to_datetime(ts, utc=True).strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return ts

display = df.copy()
display["client"] = display["client_country"].map(
    lambda c: f"{_COUNTRY_FLAGS.get(c, '🌐')} {c}" if c else "🌐 unknown"
)
display["status"] = display["status_code"].map(
    lambda s: f"✅ {s}" if s < 400 else f"❌ {s}"
)
display["time_ms"] = display["response_time_ms"].map(lambda x: f"{x:.0f} ms")
display["ts_fmt"]  = display["timestamp"].map(_fmt_ts)

table = display[["ts_fmt", "method", "endpoint", "client",
                  "status", "records_returned", "time_ms"]].copy()
table.columns = ["Timestamp (UTC)", "Method", "Endpoint",
                  "Client", "Status", "Records", "Latency"]

st.dataframe(
    table.style.apply(
        lambda row: ["background-color: #3d1a1a" if "❌" in str(row.get("Status", "")) else "" for _ in row],
        axis=1,
    ),
    use_container_width=True,
    hide_index=True,
)

# ── By client country breakdown ───────────────────────────────────────────────
if not df["client_country"].isna().all():
    st.markdown("### Requests by Client Country")
    by_client = df.groupby("client_country").agg(
        requests=("id", "count"),
        avg_ms=("response_time_ms", "mean"),
        records=("records_returned", "sum"),
    ).reset_index()
    by_client["client_country"] = by_client["client_country"].map(
        lambda c: f"{_COUNTRY_FLAGS.get(c, '🌐')} {c}"
    )
    by_client.columns = ["Country", "Requests", "Avg Latency (ms)", "Total Records Returned"]
    by_client["Avg Latency (ms)"] = by_client["Avg Latency (ms)"].round(0)
    st.dataframe(by_client, use_container_width=True, hide_index=True)
