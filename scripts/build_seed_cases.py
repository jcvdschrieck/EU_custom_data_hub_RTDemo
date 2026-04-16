"""
Build (or rebuild) data/seed_cases.db — the persistent set of open
sales-order cases that pre-exist when a simulation is launched.

The file has the same 3-table schema as investigation.db:
  Sales_Order, Sales_Order_Risk, Sales_Order_Case

On simulation start, every row is copied into investigation.db (only if
that DB is empty). Edit the SEED_CASES list below and re-run this
script to regenerate seed_cases.db.

Usage:
  python scripts/build_seed_cases.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.database import (  # noqa: E402
    _SALES_ORDER_DDL, _SALES_ORDER_RISK_DDL, _SALES_ORDER_CASE_DDL,
)
from lib.config import SEED_CASES_DB  # noqa: E402
from lib import case_statuses as STATUS  # noqa: E402


def _now_minus(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


# ── Seed catalogue ──────────────────────────────────────────────────────────
# Each entry generates one case + matching Sales_Order + Sales_Order_Risk row.
# Created_time is staggered into the past so they appear at the top of the
# FIFO queue (oldest first) when the simulation starts.

SEED_CASES = [
    {
        # Days-old, Ireland-bound CN electronics — classic VAT-rate-deviation pattern
        "Case_ID":                  "CASE-SEED00000001",
        "Sales_Order_Business_Key": "SEED-ORD-0001",
        "Sales_Order_ID":           "SEED-ORD-0001",
        "age_days":                 7,
        "Status":                   STATUS.NEW,
        "VAT_Problem_Type":         "VAT Rate Deviation",
        "HS_Product_Category":      "8517.62",
        "Product_Description":      "Wireless earbuds — bulk lot",
        "Product_Value":            14_800.00,
        "VAT_Rate":                 0.09,
        "VAT_Fee":                  1_332.00,
        "Seller_Name":              "ShenZhen TechGoods Ltd",
        "Country_Origin":           "CN",
        "Country_Destination":      "IE",
        "Overall_Risk_Score":       82.0,
        "Overall_Risk_Level":       "amber",
        "Confidence_Score":         0.85,
        "Proposed_Risk_Action":     "investigate",
    },
    {
        # Already escalated to Tax — under AI investigation when sim starts
        "Case_ID":                  "CASE-SEED00000002",
        "Sales_Order_Business_Key": "SEED-ORD-0002",
        "Sales_Order_ID":           "SEED-ORD-0002",
        "age_days":                 5,
        "Status":                   STATUS.UNDER_REVIEW_BY_TAX,
        "VAT_Problem_Type":         "Watchlist Match",
        "HS_Product_Category":      "8528.72",
        "Product_Description":      "LED TV — 55-inch units",
        "Product_Value":            22_300.00,
        "VAT_Rate":                 0.21,
        "VAT_Fee":                  4_683.00,
        "Seller_Name":              "Guangzhou DigitalMart Co.",
        "Country_Origin":           "CN",
        "Country_Destination":      "IE",
        "Overall_Risk_Score":       91.0,
        "Overall_Risk_Level":       "red",
        "Confidence_Score":         0.92,
        "Proposed_Risk_Action":     "investigate",
    },
    {
        # Customs picked it up but hasn't decided yet
        "Case_ID":                  "CASE-SEED00000003",
        "Sales_Order_Business_Key": "SEED-ORD-0003",
        "Sales_Order_ID":           "SEED-ORD-0003",
        "age_days":                 3,
        "Status":                   STATUS.UNDER_REVIEW_BY_CUSTOMS,
        "VAT_Problem_Type":         "VAT Rate Deviation + Watchlist Match",
        "HS_Product_Category":      "8525.80",
        "Product_Description":      "Drone cameras — DJI compatible",
        "Product_Value":            8_500.00,
        "VAT_Rate":                 0.09,
        "VAT_Fee":                  765.00,
        "Seller_Name":              "HK Aerial Systems Ltd",
        "Country_Origin":           "HK",
        "Country_Destination":      "FR",
        "Overall_Risk_Score":       77.0,
        "Overall_Risk_Level":       "amber",
        "Confidence_Score":         0.78,
        "Proposed_Risk_Action":     "investigate",
    },
    {
        # Awaiting third-party input
        "Case_ID":                  "CASE-SEED00000004",
        "Sales_Order_Business_Key": "SEED-ORD-0004",
        "Sales_Order_ID":           "SEED-ORD-0004",
        "age_days":                 10,
        "Status":                   STATUS.REQUESTED_INPUT,
        "VAT_Problem_Type":         "VAT Rate Deviation",
        "HS_Product_Category":      "9018.90",
        "Product_Description":      "Cosmetic LED face masks",
        "Product_Value":            5_400.00,
        "VAT_Rate":                 0.13,
        "VAT_Fee":                  702.00,
        "Seller_Name":              "Seoul BeautyTech Co.",
        "Country_Origin":           "KR",
        "Country_Destination":      "DE",
        "Overall_Risk_Score":       64.0,
        "Overall_Risk_Level":       "amber",
        "Confidence_Score":         0.70,
        "Proposed_Risk_Action":     "investigate",
    },
    {
        # Fresh case
        "Case_ID":                  "CASE-SEED00000005",
        "Sales_Order_Business_Key": "SEED-ORD-0005",
        "Sales_Order_ID":           "SEED-ORD-0005",
        "age_days":                 1,
        "Status":                   STATUS.NEW,
        "VAT_Problem_Type":         "Watchlist Match",
        "HS_Product_Category":      "8504.40",
        "Product_Description":      "Power banks — 20000mAh",
        "Product_Value":            3_200.00,
        "VAT_Rate":                 0.23,
        "VAT_Fee":                  736.00,
        "Seller_Name":              "Bangkok PowerTech Co.",
        "Country_Origin":           "TH",
        "Country_Destination":      "NL",
        "Overall_Risk_Score":       88.0,
        "Overall_Risk_Level":       "red",
        "Confidence_Score":         0.90,
        "Proposed_Risk_Action":     "investigate",
    },
]


def _ddl(conn: sqlite3.Connection, ddl: str) -> None:
    """Apply a multi-statement DDL string."""
    for stmt in ddl.strip().split(";"):
        s = stmt.strip()
        if s:
            conn.execute(s)


def build() -> None:
    if SEED_CASES_DB.exists():
        SEED_CASES_DB.unlink()
    SEED_CASES_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(SEED_CASES_DB)
    try:
        with conn:
            _ddl(conn, _SALES_ORDER_DDL)
            _ddl(conn, _SALES_ORDER_RISK_DDL)
            _ddl(conn, _SALES_ORDER_CASE_DDL)
            for s in SEED_CASES:
                created = _now_minus(s["age_days"])
                bk      = s["Sales_Order_Business_Key"]
                conn.execute("""
                    INSERT INTO Sales_Order (
                        Sales_Order_ID, Sales_Order_Business_Key,
                        HS_Product_Category, Product_Description, Product_Value,
                        VAT_Rate, VAT_Fee, Seller_Name,
                        Country_Origin, Country_Destination,
                        Status, Update_time, Updated_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    s["Sales_Order_ID"], bk,
                    s["HS_Product_Category"], s["Product_Description"], s["Product_Value"],
                    s["VAT_Rate"], s["VAT_Fee"], s["Seller_Name"],
                    s["Country_Origin"], s["Country_Destination"],
                    "investigate", created, "seed",
                ))
                conn.execute("""
                    INSERT INTO Sales_Order_Risk (
                        Sales_Order_Risk_ID, Sales_Order_Business_Key,
                        Risk_Type, Overall_Risk_Score, Overall_Risk_Level,
                        Confidence_Score, Proposed_Risk_Action,
                        Update_time, Updated_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    f"RISK-{s['Case_ID']}", bk,
                    "VAT", s["Overall_Risk_Score"], s["Overall_Risk_Level"],
                    s["Confidence_Score"], s["Proposed_Risk_Action"],
                    created, "seed",
                ))
                conn.execute("""
                    INSERT INTO Sales_Order_Case (
                        Case_ID, Sales_Order_Business_Key, Status,
                        VAT_Problem_Type, Communication,
                        Update_time, Updated_by, Created_time
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    s["Case_ID"], bk, s["Status"],
                    s["VAT_Problem_Type"], "[]",
                    created, "seed", created,
                ))
    finally:
        conn.close()
    print(f"Wrote {SEED_CASES_DB}  ({len(SEED_CASES)} cases)")


if __name__ == "__main__":
    build()
