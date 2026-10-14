"""Cleaning helpers: turn messy invoice references and amounts into comparable values."""

from __future__ import annotations

import re

import pandas as pd

# Prefixes that payment systems glue in front of the invoice number ("INV-00123", "Factura #123").
# The prefix only counts when a digit follows it (after optional separators),
# so "inv1005" loses "INV" but an id such as "NORTH-12" keeps its letters.
_PREFIX = re.compile(r"^(INVOICE|INV|FACTURA|FAC|NO)(?=[\s#.\-:]*\d)", re.IGNORECASE)
_NON_ALNUM = re.compile(r"[^A-Z0-9]")


def normalize_invoice_id(value: object) -> str | None:
    """Return a canonical invoice id, or None when nothing usable is left.

    "  inv-000123 " -> "123" and "Factura #A-0045" -> "A0045": the prefix and
    punctuation go, and only the leading zeros of the whole id are dropped.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().upper()
    text = _PREFIX.sub("", text)
    text = _NON_ALNUM.sub("", text)
    text = text.lstrip("0")
    return text or None


def normalize_vendor_id(value: object) -> str | None:
    """Vendor codes only differ by case and spaces ("vnd-01 " == "VND-01")."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().upper().replace(" ", "")
    return text or None


def parse_amount(value: object) -> float | None:
    """Parse amounts written as "1,234.50", "$ 99.9" or "(25.00)" (accounting negative)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    negative = text.startswith("(") and text.endswith(")")
    text = re.sub(r"[^0-9.\-]", "", text)
    if text in {"", "-", "."}:
        return None
    amount = float(text)
    return -abs(amount) if negative else amount


def clean_invoices(invoices: pd.DataFrame) -> pd.DataFrame:
    """Normalize ids and amounts, and drop exact duplicate invoice rows."""
    df = invoices.copy()
    df["vendor_id"] = df["vendor_id"].map(normalize_vendor_id)
    df["invoice_key"] = df["invoice_number"].map(normalize_invoice_id)
    df["amount"] = df["amount"].map(parse_amount)
    df["currency"] = df["currency"].str.strip().str.upper()
    df["invoice_date"] = pd.to_datetime(df["invoice_date"])
    return df.drop_duplicates(subset=["vendor_id", "invoice_key", "amount", "currency"])


def clean_payments(payments: pd.DataFrame) -> pd.DataFrame:
    """Normalize ids and amounts; vendor_id may legitimately be missing on a payment."""
    df = payments.copy()
    df["vendor_id"] = df["vendor_id"].map(normalize_vendor_id)
    df["invoice_key"] = df["invoice_ref"].map(normalize_invoice_id)
    df["amount"] = df["amount"].map(parse_amount)
    df["currency"] = df["currency"].str.strip().str.upper()
    df["payment_date"] = pd.to_datetime(df["payment_date"])
    return df
