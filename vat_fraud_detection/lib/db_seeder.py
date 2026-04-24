"""Seed the SQLite database with ~2 500 synthetic VAT audit records.

Call ``seed_if_empty()`` from the dashboard on first load.
Re-running is safe: the function is a no-op when the DB already has data.
"""
from __future__ import annotations

import json
import math
import random
import uuid
from datetime import date, timedelta

_RNG = random.Random(42)

# ── date helpers ──────────────────────────────────────────────────────────────
_START = date(2024, 1, 1)
_END   = date(2026, 3, 25)       # Irish DB cutoff — records after this date are in EU Hub only
_SPAN  = (_END - _START).days

def _random_date() -> date:
    """Weighted towards recent dates (last 6 months more dense)."""
    # 60% of records in first 70% of span, 40% in last 30% (recent)
    if _RNG.random() < 0.6:
        d = _RNG.randint(0, int(_SPAN * 0.70))
    else:
        d = _RNG.randint(int(_SPAN * 0.70), _SPAN)
    return _START + timedelta(days=d)


# ── supplier profiles ─────────────────────────────────────────────────────────

_CUSTOMERS = [
    ("Celtic Retailers Ltd",    "IE9988776E"),
    ("Connacht Wholesale Ltd",  "IE8877665F"),
    ("Munster Hospitality Ltd", "IE7766554G"),
    ("Ulster Trading Ltd",      "IE6655443H"),
    ("Leinster Goods Ltd",      "IE5544332I"),
]

def _customer():
    return _RNG.choice(_CUSTOMERS)


def _inv_id(prefix: str, n: int) -> str:
    return f"SEED-{prefix}-{n:04d}"

def _uid() -> str:
    return str(uuid.UUID(int=_RNG.getrandbits(128)))


# Each item template: (description, product_category, unit_price_range, vat_applied, expected, verdict)
_LIFFEY_INCORRECT = [
    ("IT advisory services",                "Professional Services", (150, 600)),
    ("IT project management",               "Professional Services", (200, 800)),
    ("Network infrastructure design",       "Professional Services", (300, 900)),
    ("Software implementation consulting",  "Professional Services", (250, 1000)),
    ("Data analytics dashboard development","Professional Services", (350, 1200)),
    ("Cloud migration planning",            "Professional Services", (400, 1100)),
    ("IT security audit",                   "Professional Services", (500, 1500)),
    ("Systems integration services",        "Professional Services", (300, 900)),
    ("Database administration",             "Professional Services", (200, 700)),
    ("Technical documentation",             "Professional Services", (150, 400)),
]  # applied 13.5%, expected 23%, verdict incorrect

_LIFFEY_CORRECT = [
    ("GDPR compliance review",              "Professional Services", (600, 1200)),
    ("Employment law advisory",             "Professional Services", (400, 900)),
    ("Contract drafting",                   "Professional Services", (500, 1100)),
    ("Financial audit support",             "Professional Services", (700, 1400)),
]  # applied 23%, expected 23%, verdict correct

_EMERALD_INCORRECT = [
    ("Children's jacket (under 11)",        "Children's Clothing",   (30, 80)),
    ("Children's shoes (under 12)",         "Children's Clothing",   (25, 70)),
    ("Baby bodysuit set (0-12 months)",     "Children's Clothing",   (10, 30)),
    ("School uniform set — age 8",          "Children's Clothing",   (35, 90)),
    ("Children's trousers (age 4-10)",      "Children's Clothing",   (15, 45)),
    ("Children's boots (age 6-10)",         "Children's Clothing",   (30, 75)),
    ("Children's swimsuit (age 4-8)",       "Children's Clothing",   (15, 40)),
    ("Children's hat (age 2-6)",            "Children's Clothing",   (8,  22)),
    ("Children's socks pack (age 3-8)",     "Children's Clothing",   (5,  15)),
    ("School sportswear kit — age 10",      "Children's Clothing",   (20, 55)),
]  # applied 23%, expected 0%, verdict incorrect

_EMERALD_CORRECT = [
    ("Adult winter jacket",                 "Adult Clothing",        (80, 200)),
    ("Women's running shoes",               "Adult Clothing",        (60, 150)),
    ("Men's formal trousers",               "Adult Clothing",        (50, 130)),
    ("Adult gym wear",                      "Adult Clothing",        (25, 70)),
    ("Ladies' dress",                       "Adult Clothing",        (40, 120)),
]  # applied 23%, expected 23%, correct

_SHAMROCK_CORRECT = [
    ("Hot food platters",                   "Catering Services",     (25, 80)),
    ("Catering service — lunch",            "Catering Services",     (100, 400)),
    ("Prepared hot food",                   "Catering Services",     (15, 60)),
    ("Non-alcoholic beverages",             "Food & Beverages",      (3, 12)),
    ("Event catering — buffet",             "Catering Services",     (200, 800)),
    ("Hot beverages service",               "Food & Beverages",      (50, 200)),
]  # applied 9%, expected 9%, correct

_SHAMROCK_INCORRECT = [
    ("Catering service — dinner",           "Catering Services",     (150, 600)),
    ("Private dining service",              "Catering Services",     (200, 900)),
]  # applied 13.5%, expected 9%, incorrect

_ATLANTIC_CORRECT = [
    ("E-book bundle — fiction",             "Electronic Publications", (8,  25)),
    ("Printed novel — hardback",            "Print Publications",     (12, 30)),
    ("Digital magazine subscription",       "Electronic Publications", (30, 80)),
    ("E-periodical subscription (monthly)", "Electronic Publications", (15, 50)),
    ("Audiobook download",                  "Electronic Publications", (8,  20)),
    ("Cloud storage service — B2B",         "Professional Services",   (80, 250)),
    ("Printed trade catalogue",             "Print Publications",     (5,  20)),
]  # applied 0%/9%/23% correctly

_ATLANTIC_UNCERTAIN = [
    ("Digital music streaming subscription","Telecommunications",     (60, 150)),
    ("Video-on-demand platform access",     "Telecommunications",     (80, 200)),
    ("Podcast platform subscription",       "Telecommunications",     (40, 100)),
]  # applied 23%, expected None, uncertain

_MEDTECH_CORRECT = [
    ("Insulin pens (Class IIa device)",     "Medical Devices",        (20, 40)),
    ("Sterile surgical gloves (box 100)",   "Medical Devices",        (15, 35)),
    ("Blood pressure monitor",              "Medical Devices",        (40, 120)),
    ("Diagnostic test kits",               "Medical Devices",        (25, 80)),
    ("Wound dressing packs",               "Medical Devices",        (10, 30)),
    ("Oral rehydration sachets",            "Pharmaceuticals",        (5,  20)),
    ("Antibiotic ointment (pharmacy grade)","Pharmaceuticals",        (8,  25)),
]  # applied 0%, expected 0%, correct

_CORK_INCORRECT = [
    ("Daily newspaper (print edition)",     "Print Publications",     (1, 3)),
    ("Regional newspaper (print)",          "Print Publications",     (1, 4)),
]  # applied 9%, expected 0%, incorrect

_CORK_CORRECT = [
    ("Monthly lifestyle magazine (print)",  "Print Publications",     (3, 8)),
    ("Trade journal subscription",          "Print Publications",     (20, 60)),
    ("Business weekly magazine",            "Print Publications",     (4, 10)),
]  # applied 9%, expected 9%, correct

_GALWAY_CORRECT = [
    ("Fresh whole milk (2L)",               "Food & Beverages",       (1, 2)),
    ("Sliced bread loaves",                 "Food & Beverages",       (1, 3)),
    ("Salted butter 500g",                  "Food & Beverages",       (2, 4)),
    ("Free-range eggs (dozen)",             "Food & Beverages",       (2, 5)),
    ("Irish cheddar cheese 400g",           "Food & Beverages",       (3, 7)),
    ("Fresh vegetables box",               "Food & Beverages",       (5, 15)),
    ("Organic oat porridge 1kg",           "Food & Beverages",       (2, 6)),
]  # applied 0%, correct

_DUBLIN_CONST_CORRECT = [
    ("Building renovation — office fit-out","Construction",           (2000, 8000)),
    ("Electrical installation work",        "Construction",           (800, 3000)),
    ("Plumbing installation",               "Construction",           (600, 2500)),
    ("Roof repair and restoration",         "Construction",           (1000, 5000)),
    ("Floor tiling — commercial",           "Construction",           (500, 2000)),
    ("Painting and decorating services",    "Construction",           (400, 1500)),
]  # applied 13.5%, correct

_MUNSTER_TECH_INCORRECT = [
    ("IT support contract (monthly)",       "Professional Services",  (200, 800)),
    ("Helpdesk managed services",           "Professional Services",  (300, 1200)),
    ("Cybersecurity monitoring",            "Professional Services",  (400, 1500)),
    ("Software licence deployment",         "Professional Services",  (250, 900)),
    ("ERP system configuration",            "Professional Services",  (500, 2000)),
]  # applied 13.5%, expected 23%, incorrect

_MUNSTER_TECH_CORRECT = [
    ("HR process consulting",               "Professional Services",  (500, 1200)),
    ("Strategy advisory",                   "Professional Services",  (600, 1500)),
]  # applied 23%, correct

_PHARMA_CORRECT = [
    ("Paracetamol tablets 500mg (bulk)",    "Pharmaceuticals",        (10, 40)),
    ("Ibuprofen capsules 400mg",            "Pharmaceuticals",        (12, 45)),
    ("Prescription vitamins D3",            "Pharmaceuticals",        (8,  30)),
    ("Antiseptic wound spray",              "Pharmaceuticals",        (6,  20)),
    ("Allergy nasal spray",                 "Pharmaceuticals",        (9,  28)),
]  # applied 0%, correct

_WICKLOW_CORRECT = [
    ("Outdoor catering — corporate",        "Catering Services",      (300, 1200)),
    ("Sandwich platter — office",           "Catering Services",      (40, 200)),
    ("Hot lunch buffet",                    "Catering Services",      (150, 600)),
    ("Coffee and pastry service",           "Food & Beverages",       (20, 100)),
]  # applied 9%, correct

_WATERFORD_MIXED = [
    ("Online learning platform subscription","Electronic Publications", (40, 150)),
    ("E-textbook bundle",                   "Electronic Publications", (15, 60)),
    ("Digital newspaper access (annual)",   "Electronic Publications", (50, 150)),
]  # applied 9%, some uncertain

_KERRY_CORRECT = [
    ("GP consultation (private)",           "Medical Devices",        (50, 150)),
    ("Physiotherapy session",               "Medical Devices",        (40, 120)),
    ("Dental consumables (sterile)",        "Medical Devices",        (20, 60)),
]  # applied 0% or 23% correctly

_TIPPERARY_CORRECT = [
    ("Organic honey 500g",                  "Food & Beverages",       (4, 12)),
    ("Free-range chicken (whole)",          "Food & Beverages",       (6, 14)),
    ("Artisan sourdough bread",             "Food & Beverages",       (3, 8)),
    ("Mixed berry jam 340g",               "Food & Beverages",       (2, 6)),
]  # applied 0%, correct

_LIMERICK_CORRECT = [
    ("Commercial lease review",             "Professional Services",  (400, 1200)),
    ("Litigation support services",         "Professional Services",  (600, 2000)),
    ("Notarial services",                   "Professional Services",  (100, 500)),
    ("Corporate secretarial services",      "Professional Services",  (200, 600)),
]  # applied 23%, correct


# ── record builders ───────────────────────────────────────────────────────────

def _make_item(template, qty_range=(1, 8)):
    desc, cat, price_range = template
    qty   = _RNG.randint(*qty_range)
    price = round(_RNG.uniform(*price_range), 2)
    return desc, cat, qty, price


def _build_result(
    inv_number: str,
    inv_date: date,
    supplier_name: str,
    supplier_vat: str,
    items: list[tuple],   # (desc, cat, qty, unit_price, vat_rate, expected_rate, verdict, reasoning)
    customer_name: str,
    customer_vat: str,
) -> dict:
    """Return a dict matching AnalysisResult.to_dict() structure."""
    rid  = _uid()
    iid  = _uid()
    line_items = []
    verdicts   = []
    for i, (desc, cat, qty, price, vat_rate, exp_rate, verdict, reasoning) in enumerate(items, 1):
        vat_amt   = round(qty * price * vat_rate, 2)
        total_inc = round(qty * price * (1 + vat_rate), 2)
        line_items.append({
            "id": str(i), "description": desc, "quantity": float(qty),
            "unit_price": price, "vat_rate_applied": vat_rate,
            "vat_amount": vat_amt, "total_incl_vat": total_inc,
            "product_category": cat,
        })
        verdicts.append({
            "line_item_id": str(i),
            "applied_rate": vat_rate,
            "expected_rate": exp_rate,
            "verdict": verdict,
            "reasoning": reasoning,
            "legislation_refs": [],
        })

    n_inc = sum(1 for v in verdicts if v["verdict"] == "incorrect")
    n_unc = sum(1 for v in verdicts if v["verdict"] == "uncertain")
    overall = "incorrect" if n_inc else ("uncertain" if n_unc else "correct")

    return {
        "id": rid,
        "invoice": {
            "id": iid,
            "source_file": f"{inv_number}.xml",
            "supplier_name": supplier_name,
            "supplier_vat_number": supplier_vat,
            "customer_name": customer_name,
            "supplier_country": "IE",
            "invoice_date": inv_date.isoformat(),
            "invoice_number": inv_number,
            "currency": "EUR",
            "line_items": line_items,
            "raw_text": "",
        },
        "verdicts": verdicts,
        "overall_verdict": overall,
        "analysed_at": inv_date.isoformat() + "T08:00:00.000000",
        "model_used": "seeded",
    }


def _risk_scores(result: dict, past_issue_counts: dict[str, int]) -> dict:
    """Compute risk score fields for a result dict."""
    import math
    verdicts    = result["verdicts"]
    line_items  = result["invoice"]["line_items"]
    vm          = {v["line_item_id"]: v for v in verdicts}
    supplier    = result["invoice"]["supplier_name"]

    # Materiality
    exposure = 0.0
    for li in line_items:
        v = vm.get(li["id"])
        if v and v["verdict"] in ("incorrect", "uncertain") and v["expected_rate"] is not None:
            base = li["total_incl_vat"] / (1 + li["vat_rate_applied"]) if li["vat_rate_applied"] > 0 else li["unit_price"] * li["quantity"]
            exposure += abs(li["vat_rate_applied"] - v["expected_rate"]) * base
    mat = min(100.0, math.log10(1 + exposure) / math.log10(1 + 20_000) * 100)

    # Rule severity
    sev_weights = {"incorrect": 100.0, "uncertain": 30.0, "correct": 0.0}
    sev = sum(sev_weights.get(v["verdict"], 0) for v in verdicts) / max(len(verdicts), 1)

    # Historical
    past = past_issue_counts.get(supplier, 0)
    hist = min(100.0, past * 20)

    total = round(0.5 * mat + 0.3 * sev + 0.2 * hist, 1)
    tier  = "HIGH" if total >= 70 else ("MEDIUM" if total >= 35 else "LOW")

    n_inc = sum(1 for v in verdicts if v["verdict"] == "incorrect")
    n_unc = sum(1 for v in verdicts if v["verdict"] == "uncertain")
    n_ok  = sum(1 for v in verdicts if v["verdict"] == "correct")

    return {
        "total_exposure":      round(exposure, 2),
        "materiality_score":   round(mat, 1),
        "rule_severity_score": round(sev, 1),
        "historical_score":    round(hist, 1),
        "risk_score":          total,
        "risk_tier":           tier,
        "n_incorrect":         n_inc,
        "n_uncertain":         n_unc,
        "n_correct":           n_ok,
        "past_issue_count":    past,
    }


# ── supplier generators ───────────────────────────────────────────────────────

def _gen_liffey(n: int) -> list[dict]:
    records = []
    for i in range(1, n + 1):
        cust, cvat = _customer()
        n_items    = _RNG.randint(1, 3)
        items      = []
        is_correct = _RNG.random() < 0.20
        templates  = _LIFFEY_CORRECT if is_correct else _LIFFEY_INCORRECT
        for _ in range(n_items):
            t = _RNG.choice(templates)
            desc, cat, qty, price = _make_item(t)
            if is_correct:
                items.append((desc, cat, qty, price, 0.23, 0.23, "correct",
                    "This professional service is correctly standard-rated at 23%."))
            else:
                items.append((desc, cat, qty, price, 0.135, 0.23, "incorrect",
                    f"{desc} is a standard-rated professional service (23%). "
                    "The 13.5% reduced rate does not apply to IT consulting or related services."))
        records.append(("LIFF", i, "Liffey Services Ltd", "IE1357924D", items, cust, cvat))
    return records


def _gen_emerald(n: int) -> list[dict]:
    records = []
    for i in range(1, n + 1):
        cust, cvat = _customer()
        n_items    = _RNG.randint(1, 4)
        items      = []
        for _ in range(n_items):
            if _RNG.random() < 0.65:
                t = _RNG.choice(_EMERALD_INCORRECT)
                desc, cat, qty, price = _make_item(t, (1, 12))
                items.append((desc, cat, qty, price, 0.23, 0.0, "incorrect",
                    f"{desc} is zero-rated children's clothing under Schedule 2 VATCA 2010. "
                    "The 23% standard rate should not be applied."))
            else:
                t = _RNG.choice(_EMERALD_CORRECT)
                desc, cat, qty, price = _make_item(t, (1, 8))
                items.append((desc, cat, qty, price, 0.23, 0.23, "correct",
                    "Adult clothing is correctly standard-rated at 23%."))
        records.append(("EMER", i, "Emerald Supplies Ltd", "IE1234567A", items, cust, cvat))
    return records


def _gen_shamrock(n: int) -> list[dict]:
    records = []
    for i in range(1, n + 1):
        cust, cvat = _customer()
        n_items    = _RNG.randint(1, 3)
        items      = []
        for _ in range(n_items):
            if _RNG.random() < 0.90:
                t = _RNG.choice(_SHAMROCK_CORRECT)
                desc, cat, qty, price = _make_item(t, (1, 20))
                items.append((desc, cat, qty, price, 0.09, 0.09, "correct",
                    "Hot food and catering services are correctly rated at 9%."))
            else:
                t = _RNG.choice(_SHAMROCK_INCORRECT)
                desc, cat, qty, price = _make_item(t, (1, 10))
                items.append((desc, cat, qty, price, 0.135, 0.09, "incorrect",
                    f"{desc} should be rated at 9% as a catering/food service. "
                    "13.5% has been incorrectly applied."))
        records.append(("SHAM", i, "Shamrock Digital Ltd", "IE7654321B", items, cust, cvat))
    return records


def _gen_atlantic(n: int) -> list[dict]:
    records = []
    _correct_rates = {
        "Electronic Publications": (0.09, 0.09, "correct"),
        "Print Publications":      (0.0,  0.0,  "correct"),
        "Professional Services":   (0.23, 0.23, "correct"),
    }
    for i in range(1, n + 1):
        cust, cvat = _customer()
        n_items = _RNG.randint(1, 3)
        items   = []
        for _ in range(n_items):
            if _RNG.random() < 0.20:
                t = _RNG.choice(_ATLANTIC_UNCERTAIN)
                desc, cat, qty, price = _make_item(t, (1, 3))
                items.append((desc, cat, qty, price, 0.23, None, "uncertain",
                    f"{desc}: the applicable VAT rate is unclear — could be standard "
                    "electronic service (23%) or a cultural/entertainment service at a "
                    "reduced rate. Revenue clarification recommended."))
            else:
                t = _RNG.choice(_ATLANTIC_CORRECT)
                desc, cat, qty, price = _make_item(t, (1, 5))
                vat_a, vat_e, verdict = _correct_rates.get(cat, (0.23, 0.23, "correct"))
                items.append((desc, cat, qty, price, vat_a, vat_e, verdict,
                    "Correctly rated for this publication/service type."))
        records.append(("ATLA", i, "Atlantic Traders Ltd", "IE2468135C", items, cust, cvat))
    return records


def _gen_simple(prefix, n, sup_name, sup_vat, templates, vat_a, vat_e, verdict_val, reasoning_fn, qty_range=(1, 6)):
    records = []
    for i in range(1, n + 1):
        cust, cvat = _customer()
        n_items = _RNG.randint(1, 3)
        items   = []
        for _ in range(n_items):
            t = _RNG.choice(templates)
            desc, cat, qty, price = _make_item(t, qty_range)
            items.append((desc, cat, qty, price, vat_a, vat_e, verdict_val, reasoning_fn(desc)))
        records.append((prefix, i, sup_name, sup_vat, items, *_customer()))
    return records


def _gen_cork(n: int) -> list[dict]:
    records = []
    for i in range(1, n + 1):
        cust, cvat = _customer()
        n_items = _RNG.randint(1, 3)
        items   = []
        for _ in range(n_items):
            if _RNG.random() < 0.50:
                t = _RNG.choice(_CORK_INCORRECT)
                desc, cat, qty, price = _make_item(t, (10, 100))
                items.append((desc, cat, qty, price, 0.09, 0.0, "incorrect",
                    f"Print newspapers are zero-rated under Schedule 2 VATCA 2010. "
                    "The 9% reduced rate has been incorrectly applied."))
            else:
                t = _RNG.choice(_CORK_CORRECT)
                desc, cat, qty, price = _make_item(t, (5, 50))
                items.append((desc, cat, qty, price, 0.09, 0.09, "correct",
                    "Periodical magazines are correctly rated at 9%."))
        records.append(("CORK", i, "Cork Print Media Ltd", "IE5678901J", items, cust, cvat))
    return records


def _gen_munster_tech(n: int) -> list[dict]:
    records = []
    for i in range(1, n + 1):
        cust, cvat = _customer()
        n_items    = _RNG.randint(1, 3)
        items      = []
        is_correct = _RNG.random() < 0.40
        templates  = _MUNSTER_TECH_CORRECT if is_correct else _MUNSTER_TECH_INCORRECT
        for _ in range(n_items):
            t = _RNG.choice(templates)
            desc, cat, qty, price = _make_item(t)
            if is_correct:
                items.append((desc, cat, qty, price, 0.23, 0.23, "correct",
                    "This professional service is correctly standard-rated at 23%."))
            else:
                items.append((desc, cat, qty, price, 0.135, 0.23, "incorrect",
                    f"{desc} is standard-rated at 23%. The 13.5% reduced rate does not apply."))
        records.append(("MNTE", i, "Munster Tech Services Ltd", "IE4567890L", items, cust, cvat))
    return records


# ── main entry point ──────────────────────────────────────────────────────────

def _all_supplier_records() -> list[tuple]:
    """Return all (prefix, seq, sup_name, sup_vat, items, cust, cvat) tuples."""
    return (
        _gen_liffey(300) +
        _gen_emerald(260) +
        _gen_shamrock(200) +
        _gen_atlantic(170) +
        _gen_simple("MEDT", 130, "Shannon MedTech Ltd", "IE3456789H",
            _MEDTECH_CORRECT, 0.0, 0.0, "correct",
            lambda d: f"{d} is a medical device zero-rated under Schedule 2 VATCA 2010.", (1, 30)) +
        _gen_cork(110) +
        _gen_simple("GALW", 130, "Galway Fresh Foods Ltd", "IE6789012K",
            _GALWAY_CORRECT, 0.0, 0.0, "correct",
            lambda d: f"{d} is an unprocessed food item zero-rated under Irish VAT.", (10, 100)) +
        _gen_simple("DUBL", 110, "Dublin Construction Co", "IE9012345N",
            _DUBLIN_CONST_CORRECT, 0.135, 0.135, "correct",
            lambda d: f"{d} is a construction service correctly rated at 13.5%.", (1, 2)) +
        _gen_munster_tech(170) +
        _gen_simple("PHAR", 110, "Leinster Pharma Ltd", "IE8901234M",
            _PHARMA_CORRECT, 0.0, 0.0, "correct",
            lambda d: f"{d} is a pharmaceutical product zero-rated in Ireland.", (10, 200)) +
        _gen_simple("WICK", 130, "Wicklow Catering Co", "IE2345678P",
            _WICKLOW_CORRECT, 0.09, 0.09, "correct",
            lambda d: f"{d} is a catering/food service correctly rated at 9%.", (1, 10)) +
        _gen_simple("WATR", 90, "Waterford Digital Ltd", "IE3456789Q",
            _WATERFORD_MIXED, 0.09, 0.09, "correct",
            lambda d: f"{d} is correctly rated at 9% as a digital publication.", (1, 5)) +
        _gen_simple("KERR", 90, "Kerry Healthcare Ltd", "IE4567890R",
            _KERRY_CORRECT, 0.0, 0.0, "correct",
            lambda d: f"{d} is zero-rated as a healthcare/medical item.", (1, 10)) +
        _gen_simple("TIPP", 90, "Tipperary Foods Ltd", "IE5678901S",
            _TIPPERARY_CORRECT, 0.0, 0.0, "correct",
            lambda d: f"{d} is an unprocessed food item correctly zero-rated.", (5, 50)) +
        _gen_simple("LIMK", 90, "Limerick Legal Ltd", "IE6789012T",
            _LIMERICK_CORRECT, 0.23, 0.23, "correct",
            lambda d: f"{d} is a legal professional service correctly rated at 23%.", (1, 4))
    )


def seed_if_empty() -> int:
    """Seed the DB if it has fewer than 100 records. Returns records added."""
    from lib.database import init_db, total_count, upsert_scored_result

    init_db()
    if total_count() >= 100:
        return 0

    raw_records = _all_supplier_records()

    # Assign random dates, then sort chronologically to compute historical scores
    dated: list[tuple[date, tuple]] = []
    for rec in raw_records:
        dated.append((_random_date(), rec))
    dated.sort(key=lambda x: x[0])

    # Track per-supplier non-correct counts (for historical scoring)
    past_issues: dict[str, int] = {}
    inserted = 0

    for inv_date, (prefix, seq, sup_name, sup_vat, items, cust, cvat) in dated:
        inv_number = _inv_id(prefix, seq)
        result     = _build_result(inv_number, inv_date, sup_name, sup_vat,
                                   items, cust, cvat)
        rs         = _risk_scores(result, past_issues)

        # Update historical count for next record of this supplier
        if result["overall_verdict"] != "correct":
            past_issues[sup_name] = past_issues.get(sup_name, 0) + 1

        li_rows = [
            {"description": li["description"],
             "product_category": li["product_category"],
             "verdict": (next((v["verdict"] for v in result["verdicts"]
                               if v["line_item_id"] == li["id"]), "correct"))}
            for li in result["invoice"]["line_items"]
        ]

        inv = result["invoice"]
        upsert_scored_result(
            result_id=result["id"],
            invoice_number=inv["invoice_number"],
            invoice_date=inv["invoice_date"],
            supplier_name=inv["supplier_name"],
            supplier_vat=inv["supplier_vat_number"],
            customer_name=inv["customer_name"],
            overall_verdict=result["overall_verdict"],
            analysed_at=result["analysed_at"],
            total_exposure=rs["total_exposure"],
            materiality_score=rs["materiality_score"],
            rule_severity_score=rs["rule_severity_score"],
            historical_score=rs["historical_score"],
            risk_score=rs["risk_score"],
            risk_tier=rs["risk_tier"],
            n_incorrect=rs["n_incorrect"],
            n_uncertain=rs["n_uncertain"],
            n_correct=rs["n_correct"],
            past_issue_count=rs["past_issue_count"],
            result_dict=result,
            line_items=li_rows,
        )
        inserted += 1

    # Also import existing JSON history records
    _import_json_history(past_issues)

    return inserted


def _import_json_history(past_issues: dict[str, int]) -> None:
    """Import records from data/history.json that are not yet in the DB."""
    import json as _json
    from pathlib import Path as _Path
    from lib.database import upsert_scored_result, total_count

    hist_file = _Path("data/history.json")
    if not hist_file.exists():
        return
    try:
        records = _json.loads(hist_file.read_text(encoding="utf-8"))
    except Exception:
        return

    for r in records:
        rs  = _risk_scores(r, past_issues)
        inv = r["invoice"]
        li_rows = [
            {"description": li["description"],
             "product_category": li.get("product_category", ""),
             "verdict": (next((v["verdict"] for v in r.get("verdicts", [])
                               if v["line_item_id"] == li["id"]), "correct"))}
            for li in inv.get("line_items", [])
        ]
        upsert_scored_result(
            result_id=r["id"],
            invoice_number=inv.get("invoice_number", ""),
            invoice_date=inv.get("invoice_date", ""),
            supplier_name=inv.get("supplier_name", ""),
            supplier_vat=inv.get("supplier_vat_number", ""),
            customer_name=inv.get("customer_name", ""),
            overall_verdict=r.get("overall_verdict", "uncertain"),
            analysed_at=r.get("analysed_at", ""),
            total_exposure=rs["total_exposure"],
            materiality_score=rs["materiality_score"],
            rule_severity_score=rs["rule_severity_score"],
            historical_score=rs["historical_score"],
            risk_score=rs["risk_score"],
            risk_tier=rs["risk_tier"],
            n_incorrect=rs["n_incorrect"],
            n_uncertain=rs["n_uncertain"],
            n_correct=rs["n_correct"],
            past_issue_count=rs["past_issue_count"],
            result_dict=r,
            line_items=li_rows,
        )
        if r.get("overall_verdict") != "correct":
            sup = inv.get("supplier_name", "")
            past_issues[sup] = past_issues.get(sup, 0) + 1
