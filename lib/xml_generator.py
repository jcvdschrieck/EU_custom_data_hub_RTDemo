"""Generate an XML message for a transaction (OSS e-commerce format)."""
from __future__ import annotations
import xml.etree.ElementTree as ET


def transaction_to_xml(row: dict) -> str:
    """
    Convert a transaction dict to an XML string conforming to the
    Customs Data Hub message format.
    """
    root = ET.Element(
        "Transaction",
        attrib={"xmlns": "urn:eu:customs:transaction:v1", "version": "1.0"},
    )

    ET.SubElement(root, "TransactionId").text    = row["transaction_id"]
    ET.SubElement(root, "TransactionDate").text  = row["transaction_date"]
    ET.SubElement(root, "TransactionType").text  = "B2C"
    ET.SubElement(root, "TransactionScope").text = "intra_EU_ecommerce"
    ET.SubElement(root, "Currency").text         = "EUR"

    seller = ET.SubElement(root, "Seller")
    ET.SubElement(seller, "Id").text         = row["seller_id"]
    ET.SubElement(seller, "Name").text       = row["seller_name"]
    ET.SubElement(seller, "Country").text    = row["seller_country"]

    buyer = ET.SubElement(root, "Buyer")
    ET.SubElement(buyer, "Country").text = row["buyer_country"]

    item = ET.SubElement(root, "Item")
    ET.SubElement(item, "Description").text = row["item_description"]
    ET.SubElement(item, "Category").text    = row["item_category"]
    ET.SubElement(item, "Value").text       = f"{row['value']:.2f}"

    vat = ET.SubElement(root, "VAT")
    ET.SubElement(vat, "AppliedRate").text       = f"{row['vat_rate']:.4f}"
    ET.SubElement(vat, "CorrectRate").text        = f"{row['correct_vat_rate']:.4f}"
    ET.SubElement(vat, "Amount").text             = f"{row['vat_amount']:.2f}"
    ET.SubElement(vat, "DestinationCountry").text = row["buyer_country"]
    ET.SubElement(vat, "OSSApplicable").text      = "true"
    ET.SubElement(vat, "RateError").text          = str(bool(row["has_error"])).lower()

    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        root, encoding="unicode"
    )
