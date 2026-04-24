"""Seed the EU VAT Hub database with ~3 000 synthetic multi-country invoices.

The EU Hub stores ONLY factual data extracted from invoices.
No verdicts, no risk scores — those are computed by each member state.

Ireland records span the full demo range (2024-01-01 → 2026-03-30),
so records after 2026-03-25 form the increment not yet visible to Ireland.
"""
from __future__ import annotations

import random
import uuid
from datetime import date, timedelta

_RNG = random.Random(99)

_START = date(2023, 1, 1)
_END   = date(2026, 3, 30)
_SPAN  = (_END - _START).days


def _random_date() -> date:
    if _RNG.random() < 0.55:
        d = _RNG.randint(0, int(_SPAN * 0.65))
    else:
        d = _RNG.randint(int(_SPAN * 0.65), _SPAN)
    return _START + timedelta(days=d)


def _uid() -> str:
    return str(uuid.UUID(int=_RNG.getrandbits(128)))


# ── Country metadata ──────────────────────────────────────────────────────────

_COUNTRY_META = {
    "IE": {"currency": "EUR", "std": 0.23, "reduced": [0.135, 0.09], "zero": 0.0},
    "FR": {"currency": "EUR", "std": 0.20, "reduced": [0.10, 0.055], "zero": 0.0},
    "DE": {"currency": "EUR", "std": 0.19, "reduced": [0.07],        "zero": 0.0},
    "BE": {"currency": "EUR", "std": 0.21, "reduced": [0.12, 0.06],  "zero": 0.0},
    "NL": {"currency": "EUR", "std": 0.21, "reduced": [0.09],        "zero": 0.0},
    "ES": {"currency": "EUR", "std": 0.21, "reduced": [0.10, 0.04],  "zero": 0.0},
    "IT": {"currency": "EUR", "std": 0.22, "reduced": [0.10, 0.05],  "zero": 0.0},
    "PL": {"currency": "PLN", "std": 0.23, "reduced": [0.08, 0.05],  "zero": 0.0},
    "SE": {"currency": "SEK", "std": 0.25, "reduced": [0.12, 0.06],  "zero": 0.0},
    "CZ": {"currency": "CZK", "std": 0.21, "reduced": [0.15, 0.10],  "zero": 0.0},
}

_SUPPLIERS = {
    "IE": [
        ("Liffey Tech Solutions Ltd",  "IE1357924D", "Professional Services"),
        ("Emerald Fashion Group Ltd",   "IE1234567A", "Retail"),
        ("Shannon MedTech Ltd",         "IE3456789H", "Medical Devices"),
        ("Cork Print Media Ltd",        "IE5678901J", "Publishing"),
        ("Galway Fresh Foods Ltd",      "IE6789012K", "Food & Agriculture"),
    ],
    "FR": [
        ("Maison Beauté SARL",          "FR12345678901", "Cosmetics & Luxury"),
        ("BioTech France SAS",          "FR98765432109", "Pharmaceuticals"),
        ("Vins & Terroirs SA",          "FR55544433322", "Food & Beverages"),
        ("Conseil Digital FR SARL",     "FR11223344556", "Professional Services"),
    ],
    "DE": [
        ("Bayern Maschinenbau GmbH",    "DE123456789",   "Manufacturing"),
        ("Frankfurter Digital GmbH",    "DE987654321",   "Professional Services"),
        ("GreenEnergy Deutschland AG",  "DE555444333",   "Energy"),
        ("München Pharma GmbH",         "DE111222333",   "Pharmaceuticals"),
    ],
    "BE": [
        ("Brussels Finance SA",         "BE0123456789",  "Financial Services"),
        ("Chocolaterie Belge SPRL",     "BE9876543210",  "Food & Beverages"),
        ("Pharma Benelux NV",           "BE1122334455",  "Pharmaceuticals"),
        ("Logistics BeLux SA",          "BE5544332211",  "Logistics"),
    ],
    "NL": [
        ("Amsterdam Tech BV",           "NL123456789B01","Professional Services"),
        ("Dutch Agri BV",               "NL987654321B02","Food & Agriculture"),
        ("Rotterdam Logistics BV",      "NL555444333B03","Logistics"),
        ("Pharma Nederland BV",         "NL111222333B04","Pharmaceuticals"),
    ],
    "ES": [
        ("Ibertech Soluciones SL",      "ESB12345678",   "Professional Services"),
        ("Vinos Ibéricos SA",           "ESB98765432",   "Food & Beverages"),
        ("Turismo Costa Brava SL",      "ESB55544433",   "Hospitality"),
        ("Moda España SA",              "ESB11223344",   "Retail"),
    ],
    "IT": [
        ("Milano Moda SpA",             "IT12345678901", "Retail"),
        ("Gusto Italiano SRL",          "IT98765432109", "Food & Beverages"),
        ("TechRoma SRL",                "IT55544433322", "Professional Services"),
        ("Farmaceutica Nord SpA",       "IT11223344556", "Pharmaceuticals"),
    ],
    "PL": [
        ("Warsaw Software Sp z oo",     "PL1234567890",  "Professional Services"),
        ("Polska Fabryka Sp z oo",      "PL9876543210",  "Manufacturing"),
        ("EcoFood Polska Sp z oo",      "PL5554443332",  "Food & Agriculture"),
    ],
    "SE": [
        ("Stockholm SaaS AB",           "SE556012345601","Professional Services"),
        ("Nordic Paper AB",             "SE556098765402","Publishing"),
        ("Svensk Pharma AB",            "SE556055544403","Pharmaceuticals"),
    ],
    "CZ": [
        ("Praha Digital sro",           "CZ12345678",    "Professional Services"),
        ("Brno Manufacturing as",       "CZ98765432",    "Manufacturing"),
        ("Czech Foods as",              "CZ55544433",    "Food & Agriculture"),
    ],
}

_B2B_CUSTOMERS = [
    ("Celtic Retailers Ltd",      "IE9988776E",    "IE"),
    ("Connacht Wholesale Ltd",    "IE8877665F",    "IE"),
    ("Société Générale Achats",   "FR22233344455", "FR"),
    ("Deutsche Handels GmbH",     "DE444555666",   "DE"),
    ("Belgian Imports BVBA",      "BE0987654321",  "BE"),
    ("Dutch Trade BV",            "NL444333222B01","NL"),
    ("Iberian Partners SL",       "ESA22233344",   "ES"),
    ("Italian Buyers SpA",        "IT22233344455", "IT"),
    ("Polish Partners Sp z oo",   "PL2223334445",  "PL"),
    ("Nordic Buyers AB",          "SE556022233301","SE"),
    ("Prague Importers sro",      "CZ22334455",    "CZ"),
]

_B2C_CUSTOMERS = [
    ("Private Customer", None),
    ("Individual Client", None),
    ("Consumer", None),
]

_ITEMS_BY_CATEGORY = {
    "Professional Services": [
        ("IT consulting services",        200,  1200),
        ("Software development",          300,  1500),
        ("Management consulting",         400,  2000),
        ("Legal advisory",                300,  1200),
        ("Financial audit services",      500,  2000),
        ("Data analytics services",       350,  1500),
        ("Cybersecurity assessment",      400,  1800),
        ("IT project management",         200,   800),
        ("Network infrastructure design", 300,   900),
        ("ERP system configuration",      500,  2000),
    ],
    "Pharmaceuticals": [
        ("Prescription medication (bulk)", 50,  400),
        ("Vitamins & supplements",          20,  150),
        ("Medical supplies",                30,  200),
        ("Laboratory reagents",            100,  600),
        ("Over-the-counter analgesics",     15,   80),
    ],
    "Medical Devices": [
        ("Surgical instruments (sterile)", 80,  500),
        ("Diagnostic equipment",          500, 5000),
        ("Patient monitoring supplies",   100,  800),
        ("Disposable medical gloves",      20,  120),
        ("Blood pressure monitor",         40,  120),
    ],
    "Food & Agriculture": [
        ("Fresh vegetables (bulk)",   5,   80),
        ("Grain cereals",            10,  100),
        ("Dairy products",            8,   60),
        ("Processed food items",     15,  100),
        ("Organic produce",          10,   90),
        ("Alcoholic beverages",      20,  200),
    ],
    "Food & Beverages": [
        ("Wine (case of 12)",        30,  300),
        ("Artisan cheese selection", 20,  150),
        ("Premium olive oil",        15,   80),
        ("Restaurant catering",     100,  800),
        ("Spirits & liqueurs",       40,  250),
    ],
    "Retail": [
        ("Adult clothing",            30,  300),
        ("Children's clothing",       15,  100),
        ("Children's shoes",          25,   70),
        ("Children's jacket",         30,   80),
        ("Footwear (adult)",          40,  200),
        ("Sports equipment",          50,  500),
        ("Consumer electronics",     100, 1500),
    ],
    "Cosmetics & Luxury": [
        ("Perfume (luxury brand)",   80,  400),
        ("Skincare collection",      60,  300),
        ("Cosmetics gift set",       40,  200),
        ("Hair care products",       20,  100),
    ],
    "Manufacturing": [
        ("Steel components (batch)", 200, 2000),
        ("Precision machined parts", 300, 3000),
        ("Electrical components",    100, 1000),
        ("Industrial raw materials", 150, 1500),
    ],
    "Energy": [
        ("Electricity supply (commercial)", 500, 5000),
        ("Natural gas (commercial)",        300, 3000),
        ("Renewable energy certificates",   100, 1000),
        ("Energy consulting services",      200, 1000),
    ],
    "Financial Services": [
        ("Payment processing fees",      100, 1000),
        ("Trade finance services",       200, 2000),
        ("Currency exchange commission",  50,  500),
        ("Insurance premium",            150, 1500),
    ],
    "Logistics": [
        ("Freight forwarding (intra-EU)", 300, 3000),
        ("Warehousing services",          200, 2000),
        ("Customs brokerage",             100,  800),
        ("Last-mile delivery",             50,  400),
    ],
    "Hospitality": [
        ("Hotel accommodation",   150, 1500),
        ("Conference venue hire", 300, 3000),
        ("Restaurant meal",        50,  500),
        ("Tour package",          200, 2000),
    ],
    "Publishing": [
        ("Print newspaper (bulk)",         1,    5),
        ("Trade magazine",                 5,   30),
        ("E-book collection",             10,   60),
        ("Academic journal subscription", 20,  200),
        ("Daily newspaper (print)",        1,    3),
    ],
}

# Typical correct VAT treatment per category
_CATEGORY_TREATMENT = {
    "Professional Services": "standard",
    "Pharmaceuticals":       "zero",
    "Medical Devices":       "zero",
    "Food & Agriculture":    "zero",
    "Food & Beverages":      "reduced",
    "Retail":                "standard",
    "Cosmetics & Luxury":    "standard",
    "Manufacturing":         "standard",
    "Energy":                "reduced",
    "Financial Services":    "exempt",
    "Logistics":             "standard",
    "Hospitality":           "reduced",
    "Publishing":            "reduced",
}


def _applied_rate(category: str, country: str, tx_scope: str, tx_type: str) -> tuple[float, str]:
    """Return (applied_vat_rate, vat_treatment) — factual, with realistic error injection."""
    meta = _COUNTRY_META[country]
    std  = meta["std"]
    reds = meta["reduced"]

    # Intra-EU B2B → reverse charge
    if tx_scope == "intra_EU" and tx_type == "B2B":
        return 0.0, "reverse_charge"
    # Extra-EU → export, zero-rated
    if tx_scope == "extra_EU":
        return 0.0, "zero"

    treatment = _CATEGORY_TREATMENT.get(category, "standard")

    if treatment == "exempt":
        return 0.0, "exempt"

    # Correct rates
    if treatment == "zero":
        correct_rate = 0.0
    elif treatment == "reduced":
        correct_rate = reds[0] if reds else std
    else:
        correct_rate = std

    # Inject realistic errors (same patterns as Irish DB seeder)
    error_chance = 0.0
    wrong_rate   = std

    if country == "IE":
        if treatment == "standard" and category == "Professional Services":
            error_chance, wrong_rate = 0.60, 0.135  # IT at 13.5%
        elif treatment == "zero" and "Retail" in category:
            error_chance, wrong_rate = 0.55, 0.23   # children's clothing at 23%
        elif treatment == "reduced" and category == "Publishing":
            error_chance, wrong_rate = 0.45, 0.09   # newspapers at 9% instead of 0%
    elif country == "FR" and treatment == "standard":
        error_chance, wrong_rate = 0.25, reds[0] if reds else std
    elif country == "DE" and treatment == "reduced":
        error_chance, wrong_rate = 0.30, std
    elif country == "ES" and treatment == "reduced":
        error_chance, wrong_rate = 0.35, std
    elif country == "IT" and treatment in ("reduced", "zero"):
        error_chance, wrong_rate = 0.28, std
    elif country == "PL" and treatment == "zero":
        error_chance, wrong_rate = 0.40, std

    if _RNG.random() < error_chance:
        applied = wrong_rate
    else:
        applied = correct_rate

    return applied, treatment


def _pick_customer(supplier_country: str, tx_type: str, tx_scope: str):
    if tx_type == "B2C":
        c = _RNG.choice(_B2C_CUSTOMERS)
        return c[0], c[1], supplier_country
    if tx_scope == "domestic":
        domestic = [c for c in _B2B_CUSTOMERS if c[2] == supplier_country]
        if domestic:
            c = _RNG.choice(domestic)
            return c[0], c[1], c[2]
    foreign = [c for c in _B2B_CUSTOMERS if c[2] != supplier_country]
    c = _RNG.choice(foreign) if foreign else _RNG.choice(_B2B_CUSTOMERS)
    return c[0], c[1], c[2]


def _build_invoice(supplier_name, supplier_vat, supplier_country, industry, inv_date, seq):
    meta = _COUNTRY_META[supplier_country]
    curr = meta["currency"]

    tx_type  = "B2B" if _RNG.random() < 0.70 else "B2C"
    s = _RNG.random()
    if s < 0.55:
        tx_scope = "domestic"
    elif s < 0.85:
        tx_scope = "intra_EU"
    else:
        tx_scope = "extra_EU" if tx_type == "B2B" else "domestic"

    cust_name, cust_vat, cust_country = _pick_customer(supplier_country, tx_type, tx_scope)

    templates = _ITEMS_BY_CATEGORY.get(industry, _ITEMS_BY_CATEGORY["Professional Services"])
    n_items   = _RNG.randint(1, 4)
    line_items = []
    net_total = vat_total = 0.0
    dominant_rate = 0.0
    dominant_treat = "standard"

    for i in range(1, n_items + 1):
        desc, lo, hi = _RNG.choice(templates)
        qty   = _RNG.randint(1, 20)
        price = round(_RNG.uniform(lo, hi), 2)
        net   = round(qty * price, 2)

        applied, treat = _applied_rate(industry, supplier_country, tx_scope, tx_type)
        vat_amt = round(net * applied, 2)
        net_total  += net
        vat_total  += vat_amt

        line_items.append({
            "description":      desc,
            "product_category": industry,
            "quantity":         float(qty),
            "unit_price":       price,
            "vat_rate_applied": applied,
            "net_amount":       net,
            "vat_amount":       vat_amt,
        })
        if i == 1:
            dominant_rate  = applied
            dominant_treat = treat

    net_total   = round(net_total, 2)
    vat_total   = round(vat_total, 2)
    gross_total = round(net_total + vat_total, 2)

    return {
        "invoice_id":        _uid(),
        "invoice_number":    f"EU-{supplier_country}-{industry[:3].upper()}-{seq:05d}",
        "invoice_date":      inv_date.isoformat(),
        "supplier_name":     supplier_name,
        "supplier_vat":      supplier_vat,
        "supplier_country":  supplier_country,
        "customer_name":     cust_name,
        "customer_vat":      cust_vat,
        "customer_country":  cust_country,
        "net_amount":        net_total,
        "vat_amount":        vat_total,
        "gross_amount":      gross_total,
        "currency":          curr,
        "transaction_type":  tx_type,
        "transaction_scope": tx_scope,
        "vat_treatment":     dominant_treat,
        "vat_rate_applied":  dominant_rate,
        "reporting_country": supplier_country,
        "created_at":        inv_date.isoformat() + "T09:00:00+00:00",
        "line_items":        line_items,
    }


_COUNTRY_COUNTS = {
    "IE": 400, "FR": 320, "DE": 300, "BE": 260,
    "NL": 280, "ES": 290, "IT": 300, "PL": 250,
    "SE": 240, "CZ": 210,
}


_IE_INCREMENT_START = date(2026, 3, 26)
_IE_INCREMENT_END   = date(2026, 3, 30)

def _ie_increment_invoices() -> list[dict]:
    """Generate 25 IE invoices dated March 26-30 — the increment not yet in the Irish DB."""
    days      = (_IE_INCREMENT_END - _IE_INCREMENT_START).days + 1
    suppliers = _SUPPLIERS["IE"]
    records   = []
    for i in range(25):
        sup_name, sup_vat, industry = suppliers[i % len(suppliers)]
        day      = _IE_INCREMENT_START + timedelta(days=i % days)
        records.append(_build_invoice(sup_name, sup_vat, "IE", industry, day, 9000 + i))
    return records


def seed_if_empty() -> int:
    from lib.database import init_db, total_count, upsert_invoice

    init_db()
    if total_count() >= 100:
        return 0

    all_invoices = []
    for country, count in _COUNTRY_COUNTS.items():
        suppliers    = _SUPPLIERS.get(country, [])
        per_supplier = max(1, count // len(suppliers))
        seq = 1
        for sup_name, sup_vat, industry in suppliers:
            for _ in range(per_supplier):
                all_invoices.append(
                    _build_invoice(sup_name, sup_vat, country, industry, _random_date(), seq)
                )
                seq += 1

    # Add dedicated IE increment records (March 26-30) — not in Irish DB
    all_invoices.extend(_ie_increment_invoices())
    all_invoices.sort(key=lambda x: x["invoice_date"])

    for inv in all_invoices:
        li_rows = inv.pop("line_items")
        upsert_invoice(**inv, line_items=li_rows)

    return len(all_invoices)
