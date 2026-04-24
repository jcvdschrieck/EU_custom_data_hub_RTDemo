"""Invoice Analyzer — runs VAT compliance analysis on queued invoices.

Invoices are queued from the EU Query page (increment data) or the
History page (re-analysis of existing records). Results are saved to
the Ireland database and shown here.
"""
from __future__ import annotations

import io

import pandas as pd
import streamlit as st

# ── session state ─────────────────────────────────────────────────────────────
if "messages"        not in st.session_state: st.session_state.messages:        list = []
if "all_results"     not in st.session_state: st.session_state.all_results:     list = []
if "rationale_cache" not in st.session_state: st.session_state.rationale_cache: dict = {}
if "analysis_queue"  not in st.session_state: st.session_state.analysis_queue:  list = []  # list[Invoice]

# ── helpers ───────────────────────────────────────────────────────────────────
_VERDICT_EMOJI = {"correct": "✅", "incorrect": "❌", "uncertain": "⚠️"}
_VERDICT_BADGE = {
    "correct":   ":green[**CORRECT**]",
    "incorrect": ":red[**INCORRECT**]",
    "uncertain": ":orange[**UNCERTAIN**]",
}


def _result_header_md(result) -> str:
    inv     = result.invoice
    overall = result.overall_verdict
    badge   = _VERDICT_BADGE.get(overall, ":orange[**UNCERTAIN**]")
    lines   = [
        f"#### {_VERDICT_EMOJI.get(overall, '⚠️')} `{inv.invoice_number or inv.source_file}` — {badge}",
        "",
        f"**Supplier:** {inv.supplier_name or '—'}  |  "
        f"**Customer:** {inv.customer_name or '—'}  |  "
        f"**Date:** {inv.invoice_date or '—'}  |  "
        f"**Currency:** {inv.currency}",
        "",
        "| # | Description | Category | Applied VAT | Expected VAT | Verdict | Rationale |",
        "|---|-------------|----------|:-----------:|:------------:|---------|-----------|",
    ]
    verdict_map = {v.line_item_id: v for v in result.verdicts}
    for li in inv.line_items:
        v   = verdict_map.get(li.id)
        exp = f"{v.expected_rate:.1%}" if v and v.expected_rate is not None else "—"
        ve  = _VERDICT_EMOJI.get(v.verdict, "⚠️") + f" {v.verdict}" if v else "⚠️ uncertain"
        rat = (v.reasoning.replace("|", "&#124;").replace("\n", " ")[:250] + "…"
               if v and len(v.reasoning) > 250
               else (v.reasoning.replace("|", "&#124;").replace("\n", " ") if v else "No verdict."))
        cat = li.product_category or "—"
        lines.append(
            f"| {li.id} | {li.description} | {cat} "
            f"| {li.vat_rate_applied:.1%} | {exp} | {ve} | {rat} |"
        )
    seen: set[str] = set()
    ref_lines = []
    for v in result.verdicts:
        for ref in (v.legislation_refs if v else []):
            key = ref.url or ref.source
            if key and key not in seen:
                seen.add(key)
                label = ref.source or ref.url
                if ref.section: label += f" — {ref.section}"
                if ref.page:    label += f" (p. {ref.page})"
                ref_lines.append(f"[{label}]({ref.url})" if ref.url else label)
    if ref_lines:
        lines += ["", "**Sources:** " + " · ".join(ref_lines)]
    return "\n".join(lines)


def _make_voice_text(result) -> str:
    inv         = result.invoice
    verdict_map = {v.line_item_id: v for v in result.verdicts}
    parts = [f"Analysis of invoice {inv.invoice_number or inv.source_file}."]
    if inv.supplier_name: parts.append(f"Supplier: {inv.supplier_name}.")
    parts.append(f"Overall verdict: {result.overall_verdict}.")
    for li in inv.line_items:
        v = verdict_map.get(li.id)
        parts.append(f"Line item {li.id}: {li.description}. Applied VAT: {li.vat_rate_applied:.0%}.")
        if v:
            if v.expected_rate is not None: parts.append(f"Expected VAT: {v.expected_rate:.0%}.")
            parts.append(f"Verdict: {v.verdict}.")
            reasoning = v.reasoning.replace("**", "").replace("*", "").replace("`", "")
            parts.append((reasoning[:350] + "…") if len(reasoning) > 350 else reasoning)
    return " ".join(parts)


def _generate_tts(text: str) -> bytes:
    from gtts import gTTS
    buf = io.BytesIO()
    gTTS(text=text, lang="en", tld="ie").write_to_fp(buf)
    buf.seek(0)
    return buf.getvalue()


def _voice_button(voice_text: str, key: str = "") -> None:
    if st.button("🔊 Voice outcome", key=f"voice_{key}"):
        with st.spinner("Generating audio…"):
            audio = _generate_tts(voice_text)
        st.audio(audio, format="audio/mp3", autoplay=True)


def _render_result_live(result) -> None:
    st.markdown(_result_header_md(result))

    # Full rationale per line item (expandable — table column is truncated)
    if result.verdicts:
        with st.expander("📋 Full rationale per line item"):
            for v in result.verdicts:
                icon = _VERDICT_EMOJI.get(v.verdict, "⚠️")
                st.markdown(f"**{icon} Line {v.line_item_id}**")
                st.markdown(v.reasoning)
                if v != result.verdicts[-1]:
                    st.divider()

    all_refs = [(v, ref) for v in result.verdicts for ref in v.legislation_refs if ref.paragraph]
    if all_refs:
        st.markdown("**Legislation excerpts:**")
        seen: set[str] = set()
        for v, ref in all_refs:
            if ref.paragraph in seen: continue
            seen.add(ref.paragraph)
            label = (ref.ref or "")
            if ref.source:  label += f"  {ref.source}"
            if ref.section: label += f" — {ref.section}"
            if ref.page:    label += f" (p. {ref.page})"
            label = label.strip(" —")
            with st.expander(label):
                if ref.url: st.markdown(f"[View source]({ref.url})")
                st.markdown(f"```\n{ref.paragraph}\n```")
    _voice_button(_make_voice_text(result), key=result.id)


def _build_xlsx(results) -> bytes:
    rows = []
    for result in results:
        inv         = result.invoice
        verdict_map = {v.line_item_id: v for v in result.verdicts}
        for li in inv.line_items:
            v = verdict_map.get(li.id)
            rows.append({
                "Invoice Number":  inv.invoice_number or inv.source_file,
                "Supplier":        inv.supplier_name,
                "Customer":        inv.customer_name,
                "Date":            inv.invoice_date,
                "Item #":          li.id,
                "Description":     li.description,
                "Category":        li.product_category,
                "Qty":             li.quantity,
                "Unit Price":      li.unit_price,
                "Applied VAT %":   f"{li.vat_rate_applied:.1%}",
                "Expected VAT %":  (f"{v.expected_rate:.1%}" if v and v.expected_rate is not None else ""),
                "VAT Amount":      li.vat_amount,
                "Total incl. VAT": li.total_incl_vat,
                "Verdict":         v.verdict if v else "uncertain",
                "Rationale":       v.reasoning if v else "",
            })
    df  = pd.DataFrame(rows)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="VAT Analysis")
        ws = writer.sheets["VAT Analysis"]
        for col_cells in ws.columns:
            width = max(len(str(cell.value or "")) for cell in col_cells)
            ws.column_dimensions[col_cells[0].column_letter].width = min(width + 3, 70)
    return buf.getvalue()


def _run_analysis(invoice):
    """Run LLM VAT analysis on a single Invoice model object. Returns AnalysisResult."""
    from lib.analyser import analyse
    return analyse(invoice)


# ── sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🧾 VAT Compliance Checker")
    st.caption("Analyse invoices queued from EU Query or History pages.")
    st.divider()

    queue_len = len(st.session_state.analysis_queue)
    if queue_len:
        st.info(f"**{queue_len}** invoice(s) ready to analyse.")
        analyse_btn = st.button("▶️ Run Analysis", type="primary", use_container_width=True)
        if st.button("🗑️ Clear queue", use_container_width=True):
            st.session_state.analysis_queue = []
            st.rerun()
    else:
        analyse_btn = False
        st.info(
            "No invoices queued.\n\n"
            "Select invoices in **EU Query → Increment** or **History**, "
            "then click **Launch VAT Analysis**."
        )

    if st.session_state.all_results:
        st.divider()
        st.download_button(
            label="⬇️ Export to Excel",
            data=_build_xlsx(st.session_state.all_results),
            file_name="vat_analysis.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
        if st.button("🗑️ Clear session results", use_container_width=True):
            st.session_state.messages    = []
            st.session_state.all_results = []
            st.rerun()

    st.divider()
    st.caption(
        "**How it works**\n\n"
        "1. Go to **EU Query** and select increment invoices, or\n"
        "2. Go to **History** and select past invoices.\n"
        "3. Click **Launch VAT Analysis** on either page.\n"
        "4. Return here — the queue runs automatically."
    )


# ── main area ─────────────────────────────────────────────────────────────────
st.markdown("## 🧾 Invoice Analyzer")

# Show queued invoices before running
if st.session_state.analysis_queue and not analyse_btn:
    st.markdown(f"### ⏳ {len(st.session_state.analysis_queue)} invoice(s) queued")
    for inv in st.session_state.analysis_queue:
        st.markdown(
            f"- `{inv.invoice_number or inv.source_file}` — "
            f"**{inv.supplier_name or '—'}** | {inv.invoice_date or '—'} | "
            f"{len(inv.line_items)} line item(s)"
        )
    st.info("Click **▶️ Run Analysis** in the sidebar to start.")

# Show past chat messages
if not st.session_state.messages and not st.session_state.analysis_queue:
    with st.chat_message("assistant"):
        st.markdown(
            "👋 Welcome to the **Invoice Analyzer**.\n\n"
            "To analyse invoices:\n"
            "- Go to **🌍 EU Query → Increment** tab, select invoices and click **Launch VAT Analysis**, or\n"
            "- Go to **📋 History**, select invoices and click **Launch VAT Analysis**.\n\n"
            "Results will appear here with a verdict for each line item."
        )

for i, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "assistant" and msg.get("voice_text"):
            _voice_button(msg["voice_text"], key=str(i))


# ── run analysis on queued invoices ───────────────────────────────────────────
if analyse_btn and st.session_state.analysis_queue:
    from lib.persistence import save_result

    queue = list(st.session_state.analysis_queue)
    st.session_state.analysis_queue = []

    names = ", ".join(
        f"`{inv.invoice_number or inv.source_file}`" for inv in queue[:5]
    )
    if len(queue) > 5:
        names += f" … and {len(queue) - 5} more"
    user_text = (
        f"Please analyse {len(queue)} invoice(s): {names}"
        if len(queue) > 1
        else f"Please analyse invoice: {names}"
    )
    st.session_state.messages.append({"role": "user", "content": user_text})
    with st.chat_message("user"):
        st.markdown(user_text)

    new_results = []
    for invoice in queue:
        label = invoice.invoice_number or invoice.source_file
        with st.chat_message("assistant"):
            with st.spinner(f"Analysing **{label}**…"):
                try:
                    result = _run_analysis(invoice)
                    new_results.append(result)
                    st.session_state.all_results.append(result)
                    save_result(result)
                    _render_result_live(result)
                    compact = _result_header_md(result)
                    st.session_state.messages.append({
                        "role":       "assistant",
                        "content":    compact,
                        "voice_text": _make_voice_text(result),
                    })
                except Exception as exc:
                    err = f"❌ Failed to analyse **{label}**: {exc}"
                    st.error(err)
                    st.session_state.messages.append({"role": "assistant", "content": err})

    if len(new_results) > 1:
        n_ok  = sum(1 for r in new_results if r.overall_verdict == "correct")
        n_err = sum(1 for r in new_results if r.overall_verdict == "incorrect")
        n_unc = len(new_results) - n_ok - n_err
        summary = (
            f"**Batch complete** — {len(new_results)} invoices analysed.\n\n"
            f"✅ {n_ok} correct  |  ❌ {n_err} with issues  |  ⚠️ {n_unc} uncertain\n\n"
            "Switch to **Prioritization Dashboard** to see them ranked by risk score."
        )
        with st.chat_message("assistant"):
            st.markdown(summary)
        st.session_state.messages.append({"role": "assistant", "content": summary})

    st.rerun()
