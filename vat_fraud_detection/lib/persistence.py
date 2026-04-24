"""Save and load AnalysisResult records to/from data/history.json (and SQLite)."""
from __future__ import annotations
import json
from pathlib import Path
from lib.models import AnalysisResult

_HISTORY_FILE = Path(__file__).parent.parent / "data" / "history.json"

def save_result(result: AnalysisResult) -> None:
    records = _load_raw()
    records.append(result.to_dict())
    _HISTORY_FILE.write_text(json.dumps(records, indent=2), encoding="utf-8")
    _sync_to_db(result)

def load_results() -> list[AnalysisResult]:
    return [AnalysisResult.from_dict(r) for r in _load_raw()]

def clear_history() -> None:
    _HISTORY_FILE.write_text("[]", encoding="utf-8")

def _sync_to_db(result: AnalysisResult) -> None:
    """Write a freshly-analysed result into the SQLite DB with its risk scores."""
    try:
        from lib.database import init_db, upsert_scored_result
        from lib.risk_scorer import score_result
        from lib.persistence import load_results

        init_db()
        # Use all existing history as context for historical scoring
        past = [r for r in load_results() if r.id != result.id]
        rs = score_result(result, past)

        inv = result.invoice
        li_rows = []
        verdict_map = {v.line_item_id: v.verdict for v in result.verdicts}
        for li in inv.line_items:
            li_rows.append({
                "description": li.description or "",
                "product_category": getattr(li, "product_category", "") or "",
                "verdict": verdict_map.get(li.id, "correct"),
            })

        upsert_scored_result(
            result_id=result.id,
            invoice_number=inv.invoice_number or "",
            invoice_date=inv.invoice_date or "",
            supplier_name=inv.supplier_name or "",
            supplier_vat=inv.supplier_vat_number or "",
            customer_name=inv.customer_name or "",
            overall_verdict=result.overall_verdict or "",
            analysed_at=result.analysed_at or "",
            total_exposure=rs.vat_exposure_eur,
            materiality_score=rs.materiality_score,
            rule_severity_score=rs.rule_severity_score,
            historical_score=rs.historical_score,
            risk_score=rs.total_score,
            risk_tier=rs.tier,
            n_incorrect=rs.n_incorrect,
            n_uncertain=rs.n_uncertain,
            n_correct=rs.n_correct,
            past_issue_count=rs.past_issue_count,
            result_dict=result.to_dict(),
            line_items=li_rows,
        )
    except Exception:
        pass  # DB sync is best-effort; JSON remains the source of truth


def _load_raw() -> list[dict]:
    if not _HISTORY_FILE.exists():
        return []
    try:
        return json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
