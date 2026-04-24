# Ireland VAT misclassification demo dataset (synthetic)

This dataset is **synthetic** and intended for building demonstrators of VAT-rate misapplication / misclassification.

## Contents
- `invoices_pdf/` : 30 human-readable PDF invoices (typical invoice layout)
- `invoices_xml/` : 30 XML invoices in a **UBL-like** structure (Invoice-2 namespace) suitable for parsing demos
- `ground_truth.csv` : line-level annotations with:
  - applied VAT rate vs expected VAT rate
  - `is_fraud_line` label
  - scenario name

## Notes
- Rates used are Ireland rates effective **1 January 2026**:
  - Standard 23%, Reduced 13.5%, Second reduced 9%, Zero 0%.
- Scenarios included: electronics, consulting, food retail, catering/takeaway, ebooks/audiobooks, e-periodicals, children's clothing, ambiguous bundles.
- Some invoices contain a mix of correct and fraudulent lines to simulate realistic investigations.
