"""Simulation Control — start, pause, speed, reset."""
import time
import httpx
import streamlit as st

from lib.config import API_BASE_URL, MIN_SPEED, MAX_SPEED, DEFAULT_SPEED

st.set_page_config(page_title="Simulation Control", page_icon="⚙️", layout="wide")
st.title("⚙️ Simulation Control")
st.caption(
    "Controls the replay of March-2026 transactions into the Customs Database. "
    "Speed = simulated minutes per real second (120 = 2 sim-hours/sec ≈ 6 real min for full March)."
)


def _api(method: str, path: str, **kw):
    try:
        fn = getattr(httpx, method)
        return fn(f"{API_BASE_URL}{path}", timeout=3, **kw).json()
    except Exception as exc:
        return {"error": str(exc)}


# ── Status ────────────────────────────────────────────────────────────────────
status_ph = st.empty()


def render_status():
    s = _api("get", "/api/simulation/status")
    if "error" in s:
        status_ph.error(f"API unreachable: {s['error']}")
        return s

    with status_ph.container():
        k1, k2, k3, k4, k5 = st.columns(5)
        running_icon = "▶️ Running" if s.get("running") else ("⏸ Paused" if s.get("fired_count") else "⏹ Not started")
        k1.metric("Status",           running_icon)
        k2.metric("Sim time",         s.get("sim_time", "")[:16].replace("T", " "))
        k3.metric("Speed",            f"{s.get('speed', 0):.0f}× sim-min/s")
        k4.metric("Transactions fired", f"{s.get('fired_count', 0):,} / {s.get('total', 0):,}")
        k5.metric("Progress",         f"{s.get('pct_complete', 0):.1f}%")

        if s.get("total", 0):
            st.progress(s.get("pct_complete", 0) / 100)

        if s.get("finished"):
            st.success("✅ Simulation complete — all March-2026 transactions have been replayed.")

    return s


s = render_status()

st.divider()

# ── Control buttons ───────────────────────────────────────────────────────────
st.subheader("Controls")
c1, c2, c3, c4 = st.columns(4)

if c1.button("▶ Start / Resume", use_container_width=True):
    if s.get("finished"):
        st.warning("Simulation finished. Reset first.")
    elif s.get("running"):
        st.info("Already running.")
    else:
        endpoint = "/api/simulation/start" if not s.get("fired_count") else "/api/simulation/resume"
        _api("post", endpoint)
        st.rerun()

if c2.button("⏸ Pause", use_container_width=True):
    _api("post", "/api/simulation/pause")
    st.rerun()

if c3.button("🔄 Reset", use_container_width=True, type="secondary"):
    _api("post", "/api/simulation/reset")
    st.success("Simulation reset. Customs DB simulation data cleared from the live queue.")
    st.rerun()

st.divider()

# ── Speed control ─────────────────────────────────────────────────────────────
st.subheader("Speed")

PRESETS = {
    "🐢 Slow (30×)":    30,
    "🚶 Normal (120×)": 120,
    "🏃 Fast (360×)":   360,
    "🚀 Turbo (1440×)": 1440,
}
current_speed = s.get("speed", DEFAULT_SPEED)

col_preset, col_custom = st.columns([2, 3])

with col_preset:
    st.markdown("**Presets**")
    for label, spd in PRESETS.items():
        if st.button(label, use_container_width=True,
                     type="primary" if abs(current_speed - spd) < 1 else "secondary"):
            _api("post", "/api/simulation/speed", json={"speed": spd})
            st.rerun()

with col_custom:
    st.markdown("**Custom speed**")
    new_speed = st.slider(
        "Simulated minutes per real second",
        min_value=int(MIN_SPEED),
        max_value=int(MAX_SPEED),
        value=int(current_speed),
        step=10,
        key="speed_slider",
    )
    if st.button("Apply", key="apply_speed"):
        _api("post", "/api/simulation/speed", json={"speed": float(new_speed)})
        st.rerun()

    # Estimated completion time
    remaining = s.get("total", 0) - s.get("fired_count", 0)
    if remaining > 0 and new_speed > 0:
        # remaining transactions roughly correspond to remaining sim-days
        fired = s.get("fired_count", 0)
        total = s.get("total", 0)
        if total:
            remaining_sim_min = (1 - fired / total) * 31 * 24 * 60  # March = 31 days
            remaining_real_sec = remaining_sim_min / new_speed
            if remaining_real_sec < 60:
                eta = f"{remaining_real_sec:.0f} seconds"
            else:
                eta = f"{remaining_real_sec/60:.1f} minutes"
            st.caption(f"Estimated time to complete at this speed: **{eta}**")

st.divider()

# ── XML message preview ───────────────────────────────────────────────────────
st.subheader("Latest XML message")
st.caption("The XML format sent to the Customs Database when each transaction fires.")

try:
    q = _api("get", "/api/queue")
    items = q.get("items", [])
    if items:
        latest = items[0]
        xml_msg = latest.get("xml_message", "")
        if xml_msg:
            st.code(xml_msg, language="xml")
        else:
            st.info("No XML message stored for the latest transaction.")
    else:
        st.info("No transactions yet — start the simulation.")
except Exception as exc:
    st.error(str(exc))

# ── Auto-refresh while running ────────────────────────────────────────────────
if s.get("running"):
    time.sleep(2)
    st.rerun()
