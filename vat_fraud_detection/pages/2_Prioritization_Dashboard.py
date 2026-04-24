"""Prioritization Dashboard — risk-ranked view of analysed invoices (SQLite-backed).

Risk Score (0-100) = 50% materiality · 30% rule severity · 20% supplier history.
Default view: the 20 most recent invoices.  All filters push down to SQLite.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import streamlit as st

# ── session state defaults ────────────────────────────────────────────────────
if "all_results" not in st.session_state:
    st.session_state.all_results: list = []
if "rationale_cache" not in st.session_state:
    st.session_state.rationale_cache: dict = {}

_TIER_EMOJI = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}
_TIER_BADGE = {
    "HIGH":   ":red[**HIGH**]",
    "MEDIUM": ":orange[**MEDIUM**]",
    "LOW":    ":green[**LOW**]",
}

st.markdown("## 📊 Risk Prioritization Dashboard")
st.caption(
    "Invoices are ranked by a weighted Risk Score: "
    "**50% materiality** (VAT exposure €) · "
    "**30% rule severity** (incorrect/uncertain line items) · "
    "**20% supplier history** (past issues in the database). "
    "Expand any row for a full risk rationale."
)

# ── seed / initialise DB ──────────────────────────────────────────────────────
from lib.database import (
    count_invoices, get_result_json, get_suppliers, init_db, query_invoices,
    total_count,
)
from lib.db_seeder import seed_if_empty

init_db()
if total_count() < 100:
    with st.spinner("Building demo database — this takes ~10 seconds the first time…"):
        added = seed_if_empty()
    if added:
        st.toast(f"Seeded {added:,} records into the demo database.", icon="✅")

# ── Filters ───────────────────────────────────────────────────────────────────
_TODAY     = date.today()
_ISO_TODAY = _TODAY.isoformat()

_PERIOD_OPTIONS = [
    "Latest 20",
    "Last 7 days",
    "Last 30 days",
    "Last 90 days",
    "This year",
    "All time",
    "Custom range",
]

with st.expander("Filters", expanded=True):
    _fc1, _fc2 = st.columns([2, 2])
    with _fc1:
        _period_preset = st.selectbox("Period", options=_PERIOD_OPTIONS, index=0)
    with _fc2:
        _filter_tiers = st.multiselect(
            "Risk Tier",
            options=["HIGH", "MEDIUM", "LOW"],
            default=["HIGH", "MEDIUM", "LOW"],
        )

    # Date range from preset
    _date_from: str | None = None
    _date_to:   str | None = None
    _limit_to_20 = False

    if _period_preset == "Latest 20":
        _limit_to_20 = True
    elif _period_preset == "Last 7 days":
        _date_from = (_TODAY - timedelta(days=7)).isoformat()
    elif _period_preset == "Last 30 days":
        _date_from = (_TODAY - timedelta(days=30)).isoformat()
    elif _period_preset == "Last 90 days":
        _date_from = (_TODAY - timedelta(days=90)).isoformat()
    elif _period_preset == "This year":
        _date_from = date(_TODAY.year, 1, 1).isoformat()
    elif _period_preset == "All time":
        pass  # no date filter
    elif _period_preset == "Custom range":
        _cr1, _cr2 = st.columns(2)
        with _cr1:
            _custom_from = st.date_input("From", value=_TODAY - timedelta(days=90))
        with _cr2:
            _custom_to = st.date_input("To", value=_TODAY)
        _date_from = _custom_from.isoformat()
        _date_to   = _custom_to.isoformat()

    _fc3, _fc4, _fc5 = st.columns(3)
    with _fc3:
        _all_suppliers = get_suppliers()
        _filter_suppliers = st.multiselect(
            "Supplier (leave blank for all)",
            options=_all_suppliers,
            default=[],
        )
    with _fc4:
        _filter_min_score = st.slider(
            "Minimum Risk Score", min_value=0, max_value=100, value=0, step=5
        )
    with _fc5:
        _filter_description = st.text_input(
            "Line item description contains",
            placeholder="e.g. consulting, children, food…",
        ).strip().lower()

# ── query SQLite ──────────────────────────────────────────────────────────────
_common_kwargs = dict(
    date_from   = _date_from,
    date_to     = _date_to,
    suppliers   = _filter_suppliers or None,
    tiers       = _filter_tiers or None,
    min_score   = _filter_min_score,
    description = _filter_description or None,
)

if _limit_to_20:
    # "Latest 20": no date filter; just take 20 most recent by invoice_date / risk_score
    _rows  = query_invoices(**_common_kwargs, limit=20, offset=0)
    _total = total_count()   # show total DB size as context
    _shown_label = f"Showing **{len(_rows)}** most recent of **{_total:,}** total"
else:
    _total = count_invoices(**_common_kwargs)
    _rows  = query_invoices(**_common_kwargs, limit=_total or 1, offset=0)
    _shown_label = f"Showing **{len(_rows)}** of **{_total:,}** matching invoices"

# ── KPI strip ─────────────────────────────────────────────────────────────────
_kc1, _kc2, _kc3, _kc4 = st.columns(4)
_kc1.metric("Invoices shown",  len(_rows))
_kc2.metric("High risk",       sum(1 for r in _rows if r["risk_tier"] == "HIGH"))
_kc3.metric("Medium risk",     sum(1 for r in _rows if r["risk_tier"] == "MEDIUM"))
_kc4.metric("Total exposure",  f"€{sum(r['total_exposure'] for r in _rows):,.0f}")

st.caption(_shown_label)
st.divider()

if not _rows:
    st.info("No results match the current filters.")
    st.stop()

# ── Ranked cards ──────────────────────────────────────────────────────────────
for _rank, _row in enumerate(_rows, start=1):
    _tier  = _row["risk_tier"]
    _label = (
        f"{_TIER_EMOJI.get(_tier, '⚪')} **#{_rank}** — "
        f"`{_row['invoice_number'] or _row['result_id'][:8]}` | "
        f"{_TIER_BADGE.get(_tier)} | "
        f"Score: **{_row['risk_score']:.0f}/100** | "
        f"Exposure: **€{_row['total_exposure']:,.2f}** | "
        f"{_row['supplier_name'] or '—'} | {_row['invoice_date'] or '—'}"
    )
    with st.expander(_label, expanded=(_rank == 1 and _tier == "HIGH")):

        # Score breakdown
        _sc1, _sc2, _sc3, _sc4 = st.columns(4)
        _sc1.metric("Risk Score",     f"{_row['risk_score']:.0f}/100")
        _sc2.metric("Materiality",    f"{_row['materiality_score']:.0f}/100")
        _sc3.metric("Rule Severity",  f"{_row['rule_severity_score']:.0f}/100")
        _sc4.metric("History Score",  f"{_row['historical_score']:.0f}/100")

        if _row["past_issue_count"] > 0:
            st.caption(
                f"⚠️ Supplier **{_row['supplier_name']}** has "
                f"**{_row['past_issue_count']}** prior non-correct invoice(s) in the database."
            )

        st.markdown(
            f"**Verdicts:** ✅ {_row['n_correct']} correct · "
            f"❌ {_row['n_incorrect']} incorrect · "
            f"⚠️ {_row['n_uncertain']} uncertain"
        )

        # ── Case View drill-down button ───────────────────────────────────────
        if st.button("🔍 Open Case View", key=f"case_{_row['result_id']}"):
            st.session_state.case_taxpayer_name = _row["supplier_name"]
            st.session_state.case_taxpayer_vat  = _row["supplier_vat"]
            st.switch_page("pages/3_Case_View.py")

        # ── Risk Rationale section ────────────────────────────────────────────
        st.markdown("### Risk Rationale")

        _rid        = _row["result_id"]
        _cached_rat = st.session_state.rationale_cache.get(_rid)

        if _cached_rat is None:
            if st.button("Generate Risk Rationale", key=f"rat_{_rid}"):
                with st.spinner("Synthesising rationale via LM Studio…"):
                    from lib.models import AnalysisResult
                    from lib.risk_rationale import generate_rationale
                    from lib.risk_scorer import RiskScore

                    _rdict = get_result_json(_rid)
                    if _rdict:
                        _result = AnalysisResult.from_dict(_rdict)
                        _risk   = RiskScore(
                            result_id           = _rid,
                            invoice_ref         = _row["invoice_number"] or _rid[:8],
                            materiality_score   = _row["materiality_score"],
                            rule_severity_score = _row["rule_severity_score"],
                            historical_score    = _row["historical_score"],
                            total_score         = _row["risk_score"],
                            tier                = _row["risk_tier"],
                            vat_exposure_eur    = _row["total_exposure"],
                            n_incorrect         = _row["n_incorrect"],
                            n_uncertain         = _row["n_uncertain"],
                            n_correct           = _row["n_correct"],
                            supplier_name       = _row["supplier_name"] or "",
                            supplier_vat        = _row["supplier_vat"] or "",
                            invoice_date        = _row["invoice_date"] or "",
                            past_issue_count    = _row["past_issue_count"],
                        )
                        _rat = generate_rationale(_result, _risk)
                        st.session_state.rationale_cache[_rid] = _rat
                        st.rerun()
        else:
            _rat = _cached_rat

            # LLM narrative
            st.info(_rat.narrative)

            # Top contributing factors
            if _rat.top_factors:
                st.markdown("**Top Contributing Factors**")
                for _fi, _fac in enumerate(_rat.top_factors, 1):
                    _bar = "█" * int(_fac["weight"] / 10) + "░" * (10 - int(_fac["weight"] / 10))
                    st.markdown(
                        f"**{_fi}. {_fac['label']}** `[{_fac['weight']:.0f}/100]` {_bar}\n\n"
                        f"> {_fac['detail']}"
                    )

            # Linked data points
            if _rat.data_links:
                st.markdown("**Flagged Line Items**")
                for _dl in _rat.data_links:
                    _exp = (
                        f"{_dl['expected_rate']:.1%}"
                        if _dl["expected_rate"] is not None else "—"
                    )
                    _ve = "❌" if _dl["verdict"] == "incorrect" else "⚠️"
                    st.markdown(
                        f"- {_ve} **Item {_dl['line_item_id']}** — "
                        f"{_dl['description']} ({_dl['category']})  \n"
                        f"  Applied: `{_dl['applied_rate']:.1%}` → Expected: `{_exp}`  \n"
                        f"  *{_dl['reasoning_excerpt']}*"
                    )
                    if _dl["sources"]:
                        st.caption("Sources: " + " · ".join(_dl["sources"]))

        st.caption(
            f"Full verdict table in **Invoice Analyzer** · Result ID: `{_rid}`"
        )
