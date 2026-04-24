"""Case View — auditor drill-down for a single taxpayer (supplier).

Drill-down hierarchy:
  Taxpayer → Period (quarter) → Counterparty → Flagged line item → Raw record

AC1: Reached via "Open Case View" button in the Prioritization Dashboard.
AC2: Interactive breakdown by period, counterparty, and anomaly type.
AC3: Raw invoice viewer shows the exact underlying record for every anomaly.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

import streamlit as st

# ── session state guards ──────────────────────────────────────────────────────
if "all_results" not in st.session_state:
    st.session_state.all_results = []

_taxpayer_name = st.session_state.get("case_taxpayer_name", "")
_taxpayer_vat  = st.session_state.get("case_taxpayer_vat",  "")

if not _taxpayer_name and not _taxpayer_vat:
    st.info(
        "No taxpayer selected.  \n"
        "Go to **Prioritization Dashboard**, expand a flagged supplier card "
        "and click **🔍 Open Case View**."
    )
    st.stop()

# ── load all records (history + current session) ──────────────────────────────
from lib.persistence import load_results

_all_hist    = load_results()
_all_session = st.session_state.all_results
_combined    = {r.id: r for r in _all_hist + _all_session}  # dedup by id

_case_results = [
    r for r in _combined.values()
    if (
        (_taxpayer_vat  and r.invoice.supplier_vat_number == _taxpayer_vat)
        or (_taxpayer_name and r.invoice.supplier_name    == _taxpayer_name)
    )
]
_case_results.sort(key=lambda r: r.invoice.invoice_date or "")

if not _case_results:
    st.warning(f"No records found for **{_taxpayer_name or _taxpayer_vat}**.")
    st.stop()


# ── helpers ───────────────────────────────────────────────────────────────────

_VERDICT_EMOJI = {"correct": "✅", "incorrect": "❌", "uncertain": "⚠️"}

def _quarter(date_str: str) -> str:
    try:
        dt = datetime.fromisoformat(date_str)
        return f"Q{(dt.month - 1) // 3 + 1} {dt.year}"
    except Exception:
        return "Unknown"


def _exposure(result) -> float:
    """Estimated VAT gap in EUR for this result."""
    verdict_map = {v.line_item_id: v for v in result.verdicts}
    total = 0.0
    for li in result.invoice.line_items:
        v = verdict_map.get(li.id)
        if v and v.verdict in ("incorrect", "uncertain") and v.expected_rate is not None:
            if li.total_incl_vat and li.vat_rate_applied > 0:
                base = li.total_incl_vat / (1 + li.vat_rate_applied)
            elif li.unit_price and li.quantity:
                base = li.unit_price * li.quantity
            else:
                base = 1_000
            total += abs(li.vat_rate_applied - v.expected_rate) * base
    return round(total, 2)


def _anomaly_key(li, v) -> str:
    """Group anomalies by category + rate-pair."""
    cat = li.product_category or "Unknown category"
    app = f"{li.vat_rate_applied:.0%}"
    exp = f"{v.expected_rate:.0%}" if v.expected_rate is not None else "?"
    return f"{cat} — {app} applied (expected {exp})"


def _render_raw_invoice(result) -> None:
    """Show the full raw invoice record for a single AnalysisResult."""
    inv = result.invoice
    verdict_map = {v.line_item_id: v for v in result.verdicts}

    st.markdown(f"**Invoice:** `{inv.invoice_number or inv.source_file}`")
    st.markdown(
        f"**Supplier:** {inv.supplier_name} ({inv.supplier_vat_number})  |  "
        f"**Customer:** {inv.customer_name}  |  "
        f"**Date:** {inv.invoice_date}  |  "
        f"**Currency:** {inv.currency}"
    )

    # Line items + verdicts table
    rows_md = [
        "| # | Description | Category | Applied | Expected | Verdict | Reasoning |",
        "|---|-------------|----------|:-------:|:--------:|---------|-----------|",
    ]
    for li in inv.line_items:
        v   = verdict_map.get(li.id)
        exp = f"{v.expected_rate:.1%}" if v and v.expected_rate is not None else "—"
        ve  = (_VERDICT_EMOJI.get(v.verdict, "⚠️") + f" {v.verdict}") if v else "⚠️ uncertain"
        rsn = ""
        if v:
            rsn = v.reasoning.replace("|", "&#124;").replace("\n", " ")
            if len(rsn) > 200:
                rsn = rsn[:200] + "…"
        rows_md.append(
            f"| {li.id} | {li.description} | {li.product_category or '—'} "
            f"| {li.vat_rate_applied:.1%} | {exp} | {ve} | {rsn} |"
        )
    st.markdown("\n".join(rows_md))

    # Legislation refs
    all_refs = [
        ref
        for v in result.verdicts
        for ref in v.legislation_refs
        if ref.source or ref.url
    ]
    if all_refs:
        seen: set[str] = set()
        ref_parts = []
        for ref in all_refs:
            key = ref.url or ref.source
            if key and key not in seen:
                seen.add(key)
                label = ref.source or ref.url
                if ref.section:
                    label += f" — {ref.section}"
                ref_parts.append(f"[{label}]({ref.url})" if ref.url else label)
        st.caption("**Legislation:** " + " · ".join(ref_parts))

    st.caption(f"Analysed: {result.analysed_at[:19]}  |  Model: {result.model_used}  |  ID: `{result.id}`")


# ── page header ───────────────────────────────────────────────────────────────
_inv0 = _case_results[0].invoice
st.markdown(f"# 🔍 Case View: {_taxpayer_name}")
st.caption(
    f"VAT No: **{_taxpayer_vat or '—'}** | "
    f"Period covered: **{_case_results[0].invoice.invoice_date or '—'}** → "
    f"**{_case_results[-1].invoice.invoice_date or '—'}**"
)

if st.button("← Back to Dashboard"):
    st.switch_page("pages/2_Prioritization_Dashboard.py")

st.divider()

# ── KPI strip ─────────────────────────────────────────────────────────────────
_total      = len(_case_results)
_n_inc      = sum(1 for r in _case_results if r.overall_verdict == "incorrect")
_n_unc      = sum(1 for r in _case_results if r.overall_verdict == "uncertain")
_n_ok       = sum(1 for r in _case_results if r.overall_verdict == "correct")
_total_exp  = sum(_exposure(r) for r in _case_results)
_quarters   = sorted({_quarter(r.invoice.invoice_date) for r in _case_results if r.invoice.invoice_date})
_customers  = sorted({r.invoice.customer_name for r in _case_results if r.invoice.customer_name})

_k1, _k2, _k3, _k4, _k5, _k6 = st.columns(6)
_k1.metric("Total Invoices",    _total)
_k2.metric("Incorrect",         _n_inc, delta=f"-{_n_inc}" if _n_inc else None,
           delta_color="inverse")
_k3.metric("Uncertain",         _n_unc)
_k4.metric("Correct",           _n_ok)
_k5.metric("VAT Exposure",      f"€{_total_exp:,.0f}")
_k6.metric("Active Periods",    len(_quarters))

st.divider()


# ════════════════════════════════════════════════════════════════════════════
# Drill-down tabs
# ════════════════════════════════════════════════════════════════════════════
_tab_period, _tab_counterparty, _tab_anomaly, _tab_raw = st.tabs([
    "📅 By Period", "🏢 By Counterparty", "⚠️ Anomaly Detail", "📄 Raw Records"
])


# ── TAB 1: By Period ─────────────────────────────────────────────────────────
with _tab_period:
    st.markdown("### Invoices by Quarter")
    st.caption("Expand a quarter to see individual invoices and their verdicts.")

    _by_quarter: dict[str, list] = defaultdict(list)
    for r in _case_results:
        _by_quarter[_quarter(r.invoice.invoice_date)].append(r)

    for _q in sorted(_by_quarter.keys()):
        _qresults = _by_quarter[_q]
        _qi       = sum(1 for r in _qresults if r.overall_verdict == "incorrect")
        _qu       = sum(1 for r in _qresults if r.overall_verdict == "uncertain")
        _qok      = sum(1 for r in _qresults if r.overall_verdict == "correct")
        _qexp     = sum(_exposure(r) for r in _qresults)
        _status   = "❌" if _qi else ("⚠️" if _qu else "✅")

        _label = (
            f"{_status} **{_q}** — {len(_qresults)} invoice(s) | "
            f"❌ {_qi} incorrect · ⚠️ {_qu} uncertain · ✅ {_qok} correct | "
            f"Exposure: **€{_qexp:,.0f}**"
        )
        with st.expander(_label, expanded=(_qi > 0)):
            for _r in sorted(_qresults, key=lambda r: r.invoice.invoice_date or ""):
                _ve = _VERDICT_EMOJI.get(_r.overall_verdict, "⚠️")
                _exp_r = _exposure(_r)
                _c1, _c2, _c3, _c4 = st.columns([2, 2, 2, 3])
                _c1.markdown(f"`{_r.invoice.invoice_number or _r.invoice.source_file}`")
                _c2.markdown(_r.invoice.invoice_date or "—")
                _c3.markdown(_r.invoice.customer_name or "—")
                _c4.markdown(
                    f"{_ve} **{_r.overall_verdict}** | "
                    f"Exposure: €{_exp_r:,.0f}"
                )

                # Inline flagged line items per invoice
                _vm = {v.line_item_id: v for v in _r.verdicts}
                for _li in _r.invoice.line_items:
                    _v = _vm.get(_li.id)
                    if _v and _v.verdict != "correct":
                        _exp_rate = (
                            f"{_v.expected_rate:.1%}"
                            if _v.expected_rate is not None else "?"
                        )
                        st.markdown(
                            f"&nbsp;&nbsp;&nbsp;&nbsp;"
                            f"{_VERDICT_EMOJI.get(_v.verdict, '⚠️')} "
                            f"Item {_li.id}: **{_li.description}** — "
                            f"applied `{_li.vat_rate_applied:.1%}` → expected `{_exp_rate}`"
                        )
                st.markdown("---")


# ── TAB 2: By Counterparty ────────────────────────────────────────────────────
with _tab_counterparty:
    st.markdown("### Invoices by Customer / Counterparty")
    st.caption("Identify which customer relationships carry the most risk.")

    _by_customer: dict[str, list] = defaultdict(list)
    for r in _case_results:
        _key = r.invoice.customer_name or "Unknown"
        _by_customer[_key].append(r)

    # Sort customers by exposure descending
    _sorted_customers = sorted(
        _by_customer.items(),
        key=lambda kv: sum(_exposure(r) for r in kv[1]),
        reverse=True,
    )

    for _cust, _cresults in _sorted_customers:
        _ci    = sum(1 for r in _cresults if r.overall_verdict == "incorrect")
        _cu    = sum(1 for r in _cresults if r.overall_verdict == "uncertain")
        _cok   = sum(1 for r in _cresults if r.overall_verdict == "correct")
        _cexp  = sum(_exposure(r) for r in _cresults)
        _cstatus = "❌" if _ci else ("⚠️" if _cu else "✅")

        _clabel = (
            f"{_cstatus} **{_cust}** — {len(_cresults)} invoice(s) | "
            f"❌ {_ci} incorrect · ⚠️ {_cu} uncertain · ✅ {_cok} correct | "
            f"Exposure: **€{_cexp:,.0f}**"
        )
        with st.expander(_clabel, expanded=(_ci > 0)):
            # Timeline of invoices with this customer
            _timeline_rows = [
                "| Invoice | Date | Quarter | Overall | Exposure |",
                "|---------|------|---------|---------|----------|",
            ]
            for _r in sorted(_cresults, key=lambda r: r.invoice.invoice_date or ""):
                _ve   = _VERDICT_EMOJI.get(_r.overall_verdict, "⚠️")
                _exp_r = _exposure(_r)
                _timeline_rows.append(
                    f"| `{_r.invoice.invoice_number or _r.invoice.source_file}` "
                    f"| {_r.invoice.invoice_date or '—'} "
                    f"| {_quarter(_r.invoice.invoice_date)} "
                    f"| {_ve} {_r.overall_verdict} "
                    f"| €{_exp_r:,.0f} |"
                )
            st.markdown("\n".join(_timeline_rows))

            # Flagged line items across all invoices with this customer
            _flagged = [
                (_r, _li, _vm[_li.id])
                for _r in _cresults
                for _vm in [{v.line_item_id: v for v in _r.verdicts}]
                for _li in _r.invoice.line_items
                if _li.id in _vm and _vm[_li.id].verdict != "correct"
            ]
            if _flagged:
                st.markdown("**Flagged line items with this counterparty:**")
                for _r, _li, _v in _flagged:
                    _exp_rate = (
                        f"{_v.expected_rate:.1%}"
                        if _v.expected_rate is not None else "?"
                    )
                    st.markdown(
                        f"- {_VERDICT_EMOJI.get(_v.verdict, '⚠️')} "
                        f"`{_r.invoice.invoice_number}` / Item {_li.id}: "
                        f"**{_li.description}** ({_li.product_category or '—'}) — "
                        f"applied `{_li.vat_rate_applied:.1%}`, expected `{_exp_rate}`"
                    )


# ── TAB 3: Anomaly Detail ─────────────────────────────────────────────────────
with _tab_anomaly:
    st.markdown("### Anomalies Grouped by Type")
    st.caption(
        "Each group clusters identical misclassifications across invoices, "
        "making systemic patterns immediately visible."
    )

    # Collect all non-correct verdicts
    _all_anomalies: dict[str, list[tuple]] = defaultdict(list)
    for _r in _case_results:
        _vm = {v.line_item_id: v for v in _r.verdicts}
        for _li in _r.invoice.line_items:
            _v = _vm.get(_li.id)
            if _v and _v.verdict != "correct":
                _key = _anomaly_key(_li, _v)
                _all_anomalies[_key].append((_r, _li, _v))

    if not _all_anomalies:
        st.success("No anomalies detected across all records for this taxpayer.")
    else:
        # Sort by number of instances (most systemic first)
        for _akey, _instances in sorted(
            _all_anomalies.items(), key=lambda kv: len(kv[1]), reverse=True
        ):
            _a_exp = sum(_exposure(_r) for _r, _, _ in _instances)
            _a_label = (
                f"⚠️ **{_akey}** — "
                f"{len(_instances)} instance(s) | "
                f"Total exposure: **€{_a_exp:,.0f}**"
            )
            with st.expander(_a_label, expanded=(len(_instances) >= 2)):
                # Pattern explanation
                _sample_v = _instances[0][2]
                if _sample_v.expected_rate is not None:
                    _rate_gap = abs(_instances[0][1].vat_rate_applied - _sample_v.expected_rate)
                    st.info(
                        f"**Pattern:** {_akey.split(' — ')[0]} items are being charged "
                        f"`{_instances[0][1].vat_rate_applied:.1%}` instead of "
                        f"`{_sample_v.expected_rate:.1%}` — a rate gap of "
                        f"**{_rate_gap:.1%}** per unit of base amount."
                    )

                # All instances
                for _r, _li, _v in sorted(_instances, key=lambda t: t[0].invoice.invoice_date or ""):
                    _exp_rate = (
                        f"{_v.expected_rate:.1%}"
                        if _v.expected_rate is not None else "?"
                    )
                    _item_exp = _exposure(_r)

                    with st.container():
                        _ic1, _ic2, _ic3 = st.columns([3, 3, 4])
                        _ic1.markdown(
                            f"📄 `{_r.invoice.invoice_number}` — {_r.invoice.invoice_date}"
                        )
                        _ic2.markdown(f"👤 {_r.invoice.customer_name or '—'}")
                        _ic3.markdown(
                            f"{_VERDICT_EMOJI.get(_v.verdict, '⚠️')} "
                            f"Applied `{_li.vat_rate_applied:.1%}` → "
                            f"Expected `{_exp_rate}` | "
                            f"€{_item_exp:,.0f} exposure"
                        )

                        # Reasoning on expand
                        with st.expander("Reasoning", expanded=False):
                            st.markdown(_v.reasoning)
                            if _v.legislation_refs:
                                for _ref in _v.legislation_refs:
                                    if _ref.source or _ref.url:
                                        _lbl = _ref.source or _ref.url
                                        if _ref.section:
                                            _lbl += f" — {_ref.section}"
                                        st.caption(
                                            f"[{_lbl}]({_ref.url})"
                                            if _ref.url else _lbl
                                        )


# ── TAB 4: Raw Records ────────────────────────────────────────────────────────
with _tab_raw:
    st.markdown("### Raw Invoice Records")
    st.caption(
        "Select any invoice to inspect the complete underlying record — "
        "every line item, verdict, reasoning, and legislation reference."
    )

    # Selector
    _inv_options = {
        f"{r.invoice.invoice_number or r.invoice.source_file} — "
        f"{r.invoice.invoice_date} — {_VERDICT_EMOJI.get(r.overall_verdict, '⚠️')} "
        f"{r.overall_verdict}": r
        for r in sorted(_case_results, key=lambda r: r.invoice.invoice_date or "")
    }
    _selected_label = st.selectbox(
        "Choose invoice",
        options=list(_inv_options.keys()),
        index=0,
    )
    _selected_result = _inv_options[_selected_label]

    st.divider()
    _render_raw_invoice(_selected_result)

    # Show legislation paragraph excerpts if any
    _paras = [
        (ref, v.line_item_id)
        for v in _selected_result.verdicts
        for ref in v.legislation_refs
        if ref.paragraph
    ]
    if _paras:
        st.markdown("**Legislation Excerpts:**")
        _seen_p: set[str] = set()
        for _ref, _lid in _paras:
            if _ref.paragraph in _seen_p:
                continue
            _seen_p.add(_ref.paragraph)
            _label = f"Item {_lid} — {_ref.source or ''}"
            if _ref.section:
                _label += f" / {_ref.section}"
            with st.expander(_label.strip(" —/")):
                st.code(_ref.paragraph, language=None)
                if _ref.url:
                    st.markdown(f"[View source]({_ref.url})")
