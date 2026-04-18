"""
Message factory — builds and transforms broker messages.

Responsibilities
────────────────
1. build_sales_order_event(row)         → sales order in simplified_order.json schema
2. build_arrival_notification(tx, time) → availability-notification_simplified.json schema
3. build_file_payload(topic, message)   → clean, schema-conforming version for JSON files

In-memory pub/sub messages keep all internal flat fields for backward compatibility
(alarm_checker, db_store, agent_worker, etc. all read those fields).
The JSON files written to data/events/ contain only the clean schema.

File naming
───────────
<orderIdentifier>_<topicName>.json   (e.g. "a3f7…_sales_order_event.json")
"""
from __future__ import annotations

from datetime import datetime, timezone

from lib.catalog import SUPPLIERS

# ── Lookup tables ─────────────────────────────────────────────────────────────

_SUPPLIER_VAT: dict[str, str] = {s["id"]: s["vat_number"] for s in SUPPLIERS}

# Representative HS-6 / CN-2 / TARIC-2 / CUS codes per product category.
# CUS codes follow the 9-char pattern used in the EU CUS register.
_CATEGORY_CODES: dict[str, dict[str, str]] = {
    "electronics":      {"hs": "847130", "cn": "00", "taric": "00", "cus": "0032240-2"},
    "clothing":         {"hs": "610910", "cn": "10", "taric": "00", "cus": "0039845-9"},
    "food":             {"hs": "210690", "cn": "98", "taric": "00", "cus": "0010000-4"},
    "books":            {"hs": "490199", "cn": "00", "taric": "00", "cus": "0000000-0"},
    "health":           {"hs": "300490", "cn": "99", "taric": "00", "cus": "0041678-4"},
    "home_goods":       {"hs": "392690", "cn": "99", "taric": "00", "cus": "0050000-1"},
    "cosmetics":        {"hs": "330499", "cn": "99", "taric": "00", "cus": "0048000-9"},
    "sports":           {"hs": "950699", "cn": "99", "taric": "00", "cus": "0052000-5"},
    "auto_accessories": {"hs": "870899", "cn": "99", "taric": "00", "cus": "0055000-8"},
}
_DEFAULT_CODES: dict[str, str] = {
    "hs": "999999", "cn": "99", "taric": "00", "cus": "0000000-0",
}

# Topic names (duplicated here to avoid importing broker and causing circular deps)
_TOPIC_SALES_ORDER    = "sales_order_event"
_TOPIC_RT_RISK_1      = "rt_risk_1_outcome"
_TOPIC_RT_RISK_2      = "rt_risk_2_outcome"
_TOPIC_RT_RISK_3      = "rt_risk_3_outcome"
_TOPIC_RT_RISK_4      = "rt_risk_4_outcome"
_TOPIC_ASSESSMENT     = "assessment_outcome"
_TOPIC_RT_SCORE       = "rt_score"
_TOPIC_ORDER_VAL      = "order_validation"
_TOPIC_ARRIVAL        = "arrival_notification"
_TOPIC_RELEASE        = "release_event"
_TOPIC_RETAIN         = "retain_event"
_TOPIC_INVESTIGATE    = "investigate_event"
_TOPIC_AGENT_RETAIN   = "agent_retain_event"
_TOPIC_AGENT_RELEASE  = "agent_release_event"
_TOPIC_RELEASE_AFTER  = "release_after_investigation_event"
_TOPIC_CUSTOM_OUTCOME = "custom_outcome"

# Flat fields that are internal-only and should be stripped from file payloads
_INTERNAL_FLAT_FIELDS = frozenset({
    "transaction_id", "transaction_date", "seller_id", "seller_name",
    "seller_country", "buyer_country", "value", "vat_rate", "vat_amount",
    "correct_vat_rate", "has_error", "item_category", "item_description",
    "xml_message", "created_at", "fired", "sales_order_id",
    # Producer fields propagated for in-memory workers; the producer info
    # also lives in the schema-conforming Seller block on the line item,
    # so the on-disk JSON gets it through that path.
    "producer_id", "producer_name", "producer_country", "producer_city",
})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _iso20(dt_str: str) -> str:
    """Normalise any ISO timestamp to exactly 20 chars (schema constraint)."""
    return dt_str[:19] + "Z"


def _lrn(order_identifier: str) -> str:
    """Derive a 22-char LRN from an order UUID (hex digits, upper-cased)."""
    return order_identifier.replace("-", "").upper()[:22]


def _now_iso20() -> str:
    return _iso20(datetime.now(timezone.utc).isoformat())


# ── Public builders ───────────────────────────────────────────────────────────

def build_sales_order_event(row: dict) -> dict:
    """
    Convert a flat DB row into a Sales Order Event message.

    The returned dict contains:
    • All fields required by simplified_order.json schema (including the
      line-item Seller block introduced in the two-tier party model:
      DeemedImporter = EU-based reseller, line-item Seller = non-EU producer)
    • Internal flat fields preserved at root level (for backward-compat workers)
    • _simulationMeta sub-object summarising the internal fields

    When written to file, build_file_payload() strips the internal flat fields.
    """
    order_id      = row["transaction_id"]
    tx_date       = row["transaction_date"]
    seller_id     = row.get("seller_id", "")
    seller_name   = row.get("seller_name", "")
    seller_country = row.get("seller_country", "")
    buyer_country = row.get("buyer_country", "")
    category      = row.get("item_category", "")
    description   = row.get("item_description", "")
    net_value     = row.get("value", 0.0)
    vat_amount    = row.get("vat_amount", 0.0)
    vat_rate      = row.get("vat_rate", 0.0)
    correct_rate  = row.get("correct_vat_rate", 0.0)
    has_error     = row.get("has_error", 0)
    codes         = _CATEGORY_CODES.get(category, _DEFAULT_CODES)

    # Producer (non-EU manufacturer) — populated by the seeder onto every
    # transaction row in the two-tier party model. Older rows from a
    # pre-migration DB may have NULL producer fields; render those as empty
    # strings so the schema validation still passes.
    producer_id      = row.get("producer_id")      or ""
    producer_name    = row.get("producer_name")    or ""
    producer_country = row.get("producer_country") or ""
    producer_city    = row.get("producer_city")    or ""

    total_invoiced = round(net_value + vat_amount, 2)

    msg: dict = {
        # ── New schema fields (simplified_order.json) ──────────────────────
        "LRN":                      _lrn(order_id),
        "documentIssueDateAndTime": _iso20(tx_date),
        "DeemedImporter": {
            "identificationNumber": _SUPPLIER_VAT.get(seller_id, seller_id),
            "name":                 seller_name,
            "Address":              {"country": seller_country},
        },
        "orderIdentifier":   order_id,
        "orderCreationDate": _iso20(tx_date),
        "totalAmountInvoiced": total_invoiced,
        "VATAmountInvoiced":   round(vat_amount, 2),
        "invoiceCurrency":     "EUR",
        "CountryOfDestination": {"country": buyer_country},
        "Buyer": {
            "identificationNumber": f"{buyer_country}-CONS-{order_id[:8].upper()}",
            "name":                 f"Consumer {buyer_country}",
            "BuyerAddress":         {"country": buyer_country},
        },
        "SalesLineItem": [
            {
                "salesLineItemIdentifier": f"{order_id}-LINE-001",
                "itemAmountPrice":          round(net_value, 2),
                "DescriptionOfGoods": {
                    "descriptionOfGoods": description,
                    "CUSCode":            codes["cus"],
                    "CommodityCode": {
                        "harmonisedSystemSubheadingCode": codes["hs"],
                        "combinedNomenclatureCode":       codes["cn"],
                        "TARICCode":                     codes["taric"],
                        "TARICAdditionalCode":            [],
                    },
                },
                # ── Line-item Seller (non-EU producer) ─────────────────────
                # Two-tier party model: the DeemedImporter above is the EU
                # reseller; this Seller block describes the actual producer
                # the goods originate from.
                "Seller": {
                    "identificationNumber": producer_id,
                    "name":                 producer_name,
                    "Address": {
                        "cityName": producer_city,
                        "country":  producer_country,
                    },
                },
            }
        ],
        # ── Simulation metadata (kept in file for transparency) ────────────
        "_simulationMeta": {
            "sellerId":        seller_id,
            "sellerName":      seller_name,
            "sellerCountry":   seller_country,
            "itemCategory":    category,
            "itemDescription": description,
            "vatRate":         vat_rate,
            "correctVatRate":  correct_rate,
            "hasError":        bool(has_error),
            # Producer (non-EU manufacturer)
            "producerId":      producer_id,
            "producerName":    producer_name,
            "producerCountry": producer_country,
            "producerCity":    producer_city,
        },
        # ── Backward-compat flat fields (in-memory only, stripped in files) ─
        "transaction_id":   order_id,
        "transaction_date": tx_date,
        "seller_id":        seller_id,
        "seller_name":      seller_name,
        "seller_country":   seller_country,
        "buyer_country":    buyer_country,
        "value":            net_value,
        "vat_rate":         vat_rate,
        "vat_amount":       vat_amount,
        "correct_vat_rate": correct_rate,
        "has_error":        has_error,
        "item_category":    category,
        "item_description": description,
        # Required by insert_transaction() in _db_store_worker — propagate the
        # original DB row's xml_message + created_at so terminal storage works.
        "xml_message":      row.get("xml_message"),
        "created_at":       row.get("created_at", tx_date),
        # Producer fields (two-tier party model). Propagated through the
        # broker pipeline as flat compat fields so _db_store_worker can
        # carry them into european_custom.db on terminal storage.
        "producer_id":      producer_id or None,
        "producer_name":    producer_name or None,
        "producer_country": producer_country or None,
        "producer_city":    producer_city or None,
    }
    return msg


def build_arrival_notification(tx: dict, target_time: datetime) -> dict:
    """
    Build an Arrival Notification message following availability-notification_simplified.json.

    tx is the in-memory Sales Order Event message (new schema with flat compat fields).
    target_time is the sim-clock datetime when the goods become available.
    """
    order_id       = tx.get("orderIdentifier") or tx.get("transaction_id", "")
    order_date_str = tx.get("orderCreationDate") or tx.get("documentIssueDateAndTime", "")
    seller_country = tx.get("seller_country") or (
        (tx.get("DeemedImporter") or {}).get("Address") or {}
    ).get("country", "XX")
    seller_vat = (tx.get("DeemedImporter") or {}).get(
        "identificationNumber",
        tx.get("seller_id", "XX000000"),
    )

    # UCR: year + exporting country + seller-VAT prefix + last 8 of order UUID
    ucr = f"26{seller_country}{seller_vat[:8]}{order_id[-8:].upper()}"
    ucr = ucr[:35]

    notif_iso = _iso20(target_time.isoformat())

    return {
        # ── New schema fields (availability-notification_simplified.json) ──
        "LRN":                       ("AN" + _lrn(order_id))[:22],
        "documentIssueDateAndTime":   notif_iso,
        "dateOfAvailabilityOfGoods":  notif_iso,
        "HouseConsignment": {
            "referenceNumberUcr": ucr,
            "Order": {
                "orderIdentifier":  order_id,
                "orderCreationDate": order_date_str,
            },
        },
        # ── Routing field (used by _release_factory._drain_arrival) ────────
        "orderIdentifier": order_id,
    }


# ── File payload builder ──────────────────────────────────────────────────────

def build_file_payload(topic: str, message: dict) -> dict:
    """
    Return the clean, schema-conforming version of *message* for JSON persistence.

    • SALES_ORDER_EVENT   → new schema, internal flat fields stripped
    • ARRIVAL_NOTIFICATION → already clean (built by build_arrival_notification)
    • All other topics    → lightweight: {orderIdentifier, timestamp, messageTopic, outcome}
    """
    if topic == _TOPIC_SALES_ORDER:
        return {k: v for k, v in message.items() if k not in _INTERNAL_FLAT_FIELDS}

    if topic == _TOPIC_ARRIVAL:
        # Strip any stale internal routing keys that might have been added
        _strip = {"transaction_id", "sales_order_id", "arrival_notif_at",
                  "seller_id", "buyer_country"}
        return {k: v for k, v in message.items() if k not in _strip}

    # Lightweight outcome message for all other topics
    order_id = (
        message.get("orderIdentifier")
        or message.get("order_id")
        or (message.get("tx") or {}).get("orderIdentifier")
        or (message.get("tx") or {}).get("transaction_id")
        or message.get("sales_order_id")
        or "unknown"
    )

    if topic == _TOPIC_RT_RISK_1:
        outcome = {
            "risk":     message.get("risk"),
            "flagged":  message.get("flagged"),
            "alarm_id": message.get("alarm_id"),
        }
    elif topic == _TOPIC_RT_RISK_2:
        outcome = {
            "risk":    message.get("risk"),
            "flagged": message.get("flagged"),
            "reason":  message.get("reason"),
        }
    elif topic == _TOPIC_RT_RISK_3:
        outcome = {
            "risk":    message.get("risk"),
            "flagged": message.get("flagged"),
            "reason":  message.get("reason"),
        }
    elif topic == _TOPIC_RT_RISK_4:
        outcome = {
            "risk":    message.get("risk"),
            "flagged": message.get("flagged"),
            "reason":  message.get("reason"),
        }
    elif topic == _TOPIC_ASSESSMENT:
        outcome = {
            "route":              message.get("route"),
            "Overall_Risk_Score": message.get("Overall_Risk_Score"),
            "Confidence_Score":   message.get("Confidence_Score"),
            "engine_outcomes":    message.get("engine_outcomes", {}),
        }
    elif topic == _TOPIC_RT_SCORE:
        outcome = {
            "risk_score":     message.get("risk_score"),
            "risk_1_flagged": message.get("risk_1_flagged"),
            "risk_2_flagged": message.get("risk_2_flagged"),
        }
    elif topic == _TOPIC_ORDER_VAL:
        outcome = {
            "validated":         message.get("validated"),
            "validation_errors": message.get("validation_errors", []),
        }
    elif topic == _TOPIC_RELEASE:
        outcome = {
            "validated":  message.get("validated"),
            "risk_score": message.get("risk_score"),
        }
    elif topic == _TOPIC_RETAIN:
        outcome = {"risk_score": message.get("risk_score", "red")}
    elif topic == _TOPIC_INVESTIGATE:
        outcome = {
            "risk_score": message.get("risk_score", "amber"),
            "validated":  message.get("validated"),
        }
    elif topic == _TOPIC_AGENT_RETAIN:
        outcome = {"verdict": message.get("verdict"), "risk_score": "retained"}
    elif topic == _TOPIC_AGENT_RELEASE:
        outcome = {"verdict": message.get("verdict")}
    elif topic == _TOPIC_RELEASE_AFTER:
        outcome = {"verdict": message.get("verdict"), "risk_score": "cleared"}
    elif topic == _TOPIC_CUSTOM_OUTCOME:
        outcome = {"status": message.get("status")}
    else:
        outcome = {}

    return {
        "orderIdentifier": order_id,
        "timestamp":       _now_iso20(),
        "messageTopic":    topic,
        "outcome":         outcome,
    }
