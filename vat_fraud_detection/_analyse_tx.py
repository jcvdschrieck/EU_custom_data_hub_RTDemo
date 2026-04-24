"""
Standalone agent bridge entry point.

Reads a single transaction JSON from stdin, builds an Invoice + LineItem,
calls analyser.analyse(), and writes {"verdict": ..., "reasoning": ...} to stdout.

Designed to be invoked as a subprocess from EU_custom_data_bub_RTDemo so that
the two projects' `lib` packages do not conflict.
"""
import json
import sys
import traceback

def main():
    try:
        tx = json.load(sys.stdin)
    except Exception as e:
        sys.stdout.write(json.dumps({"verdict": "uncertain", "reasoning": f"JSON parse error: {e}", "success": False}))
        return

    try:
        from lib.models import Invoice, LineItem
        from lib import analyser

        quantity = 1.0
        unit_price = tx.get("value", 0.0)
        vat_rate   = tx.get("vat_rate", 0.0)
        vat_amount = tx.get("vat_amount", 0.0)

        line_item = LineItem(
            id="1",
            description=tx.get("item_description", ""),
            quantity=quantity,
            unit_price=unit_price,
            vat_rate_applied=vat_rate,
            vat_amount=vat_amount,
            total_incl_vat=round(unit_price + vat_amount, 2),
            product_category=tx.get("item_category", ""),
        )

        invoice = Invoice(
            id=tx.get("transaction_id", ""),
            source_file="EU_custom_data_hub",
            supplier_name=tx.get("seller_name", ""),
            supplier_vat_number="",
            customer_name=f"Buyer ({tx.get('buyer_country', '')})",
            supplier_country=tx.get("seller_country", ""),       # origin — where goods ship from
            destination_country=tx.get("buyer_country", ""),     # VAT jurisdiction to analyse against
            invoice_date=tx.get("transaction_date", "")[:10],
            invoice_number=tx.get("transaction_id", ""),
            currency="EUR",
            line_items=[line_item],
        )

        result = analyser.analyse(invoice)

        # Overall verdict + combined reasoning
        verdict  = result.overall_verdict
        reasonings = [
            f"{v.reasoning}"
            for v in result.verdicts
        ]
        reasoning = " | ".join(reasonings) if reasonings else "No reasoning returned."

        # Collect all unique legislation references across verdicts
        seen_refs = set()
        legislation_refs = []
        for v in result.verdicts:
            for ref in v.legislation_refs:
                key = (ref.source, ref.section)
                if key not in seen_refs:
                    seen_refs.add(key)
                    legislation_refs.append({
                        "ref":       ref.ref,
                        "source":    ref.source,
                        "section":   ref.section,
                        "url":       ref.url,
                        "page":      ref.page,
                        "paragraph": ref.paragraph,
                    })

        # Per-line verdicts — expose applied_rate and expected_rate so the
        # data hub writer can populate line_item_ai_analysis.correct_vat_pct,
        # correct_vat_value and vat_exposure. Today the analyser sees a single
        # synthetic line per transaction, so verdicts is a 1-element list.
        line_verdicts = [
            {
                "line_item_id":  v.line_item_id,
                "verdict":       v.verdict,
                "applied_rate":  v.applied_rate,
                "expected_rate": v.expected_rate,
                "reasoning":     v.reasoning,
            }
            for v in result.verdicts
        ]

        sys.stdout.write(json.dumps({
            "verdict":          verdict,
            "reasoning":        reasoning,
            "legislation_refs": legislation_refs,
            "line_verdicts":    line_verdicts,
            "success":          True,
        }))

    except Exception:
        sys.stdout.write(json.dumps({
            "verdict":   "uncertain",
            "reasoning": f"Agent error: {traceback.format_exc()}",
            "success":   False,
        }))


if __name__ == "__main__":
    main()
