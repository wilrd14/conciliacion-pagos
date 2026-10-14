import math

import pandas as pd
import pytest

from conciliacion.normalize import clean_invoices, normalize_invoice_id, normalize_vendor_id, parse_amount


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("INV-001005", "1005"),
        ("inv1005", "1005"),
        (" 1005 ", "1005"),
        ("Factura #01005", "1005"),
        ("INV 1005", "1005"),
        ("A-0045", "A0045"),
        ("NORTH-12", "NORTH12"),  # letters that look like a prefix but are part of the id
        ("", None),
        ("---", None),
        (None, None),
        (float("nan"), None),
    ],
)
def test_normalize_invoice_id(raw, expected):
    assert normalize_invoice_id(raw) == expected


def test_normalize_vendor_id_ignores_case_and_spaces():
    assert normalize_vendor_id(" vnd-01 ") == "VND-01"
    assert normalize_vendor_id(None) is None


@pytest.mark.parametrize(
    "raw, expected",
    [("1,234.50", 1234.5), ("$ 99.90", 99.9), ("(25.00)", -25.0), ("-10", -10.0), (42, 42.0), ("", None)],
)
def test_parse_amount(raw, expected):
    result = parse_amount(raw)
    if expected is None:
        assert result is None
    else:
        assert math.isclose(result, expected)


def test_clean_invoices_drops_exact_duplicates_only():
    raw = pd.DataFrame(
        {
            "invoice_id": ["I1", "I1", "I2"],
            "vendor_id": ["VND-01", "vnd-01 ", "VND-01"],
            "invoice_number": ["INV-000010", "inv10", "INV-000011"],
            "invoice_date": ["2026-08-01"] * 3,
            "amount": ["100.00", "100.00", "100.00"],
            "currency": ["USD", "usd", "USD"],
        }
    )
    cleaned = clean_invoices(raw)
    assert list(cleaned["invoice_key"]) == ["10", "11"]
