"""Transaction Monitoring System — Real-Time Demo Dashboard (Streamlit entry point)."""
import streamlit as st

st.set_page_config(
    page_title="Custom Risk Monitoring",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.sidebar.title("Transaction\nMonitoring System")
st.sidebar.caption("Real-Time Customs Risk Demo")
st.sidebar.markdown("---")
st.sidebar.page_link("pages/1_Live_Queue.py",        label="📡 Live Transaction Queue")
st.sidebar.page_link("pages/2_VAT_Metrics.py",       label="📊 VAT Metrics")
st.sidebar.page_link("pages/3_Simulation.py",        label="⚙️ Simulation Control")

st.title("🛡️ Transaction Monitoring System")
st.markdown(
    """
    Welcome to the **Transaction Monitoring System** real-time demo.

    | Page | Description |
    |------|-------------|
    | 📡 **Live Queue** | Last 30 transactions as they arrive in real time |
    | 📊 **VAT Metrics** | Due VAT aggregated by country, supplier, category |
    | ⚙️ **Simulation** | Start, pause, speed and reset the March-2026 replay |

    Use the sidebar to navigate.
    """
)

# Quick stats from the API
import httpx
from lib.config import API_BASE_URL

try:
    r = httpx.get(f"{API_BASE_URL}/health", timeout=2)
    data = r.json()
    col1, col2 = st.columns(2)
    col1.metric("Records in Customs DB", f"{data['records_in_db']:,}")
    col2.metric("API status", "✅ Online")
except Exception:
    st.warning("API not reachable — start the FastAPI server first: `uvicorn api:app --port 8505`")
