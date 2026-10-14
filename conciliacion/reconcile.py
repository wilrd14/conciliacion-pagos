"""Match payments to invoices and classify every discrepancy.

Rules, in order:
1. A payment with a vendor_id is matched on (vendor_id, invoice_key).
2. A payment without vendor_id is matched on invoice_key alone, but only when
   exactly one invoice has that key. If several vendors share the key the
   payment is AMBIGUOUS and is never assigned: a wrong match is worse than
   no match, because it would hide a real underpayment.
3. Payments that match nothing are UNMATCHED_PAYMENT.
"""

from __future__ import annotations

import pandas as pd

TOLERANCE = 0.01  # in the invoice currency

PAID = "PAID"
UNDERPAID = "UNDERPAID"
OVERPAID = "OVERPAID"
UNPAID = "UNPAID"
REVERSED = "REVERSED"
UNMATCHED_PAYMENT = "UNMATCHED_PAYMENT"
AMBIGUOUS = "AMBIGUOUS"


def assign_payments(invoices: pd.DataFrame, payments: pd.DataFrame) -> pd.DataFrame:
    """Return payments with an `invoice_id` column (the matched invoice) and `match_status`."""
    # pandas joins NaN keys to each other, so an invoice without a usable
    # number must never be a match candidate.
    keys = invoices[["invoice_id", "vendor_id", "invoice_key"]].dropna(subset=["invoice_key"])

    def match_on(frame: pd.DataFrame, on: list[str]) -> pd.DataFrame:
        # Count candidates first so a key shared by several invoices can never
        # duplicate the payment row (and double-count the money).
        candidates = keys.groupby(on).size().rename("candidates").reset_index()
        unique = keys.merge(candidates[candidates["candidates"] == 1], on=on)[on + ["invoice_id"]]
        frame = frame.merge(candidates, on=on, how="left").merge(unique, on=on, how="left")
        frame["match_status"] = "MATCHED"
        frame.loc[frame["candidates"].isna(), "match_status"] = UNMATCHED_PAYMENT
        frame.loc[frame["candidates"] > 1, "match_status"] = AMBIGUOUS
        return frame.drop(columns="candidates")

    with_vendor = match_on(payments[payments["vendor_id"].notna()], ["vendor_id", "invoice_key"])

    without_vendor = match_on(payments[payments["vendor_id"].isna()].drop(columns="vendor_id"), ["invoice_key"])
    # Recover the vendor from the invoice it was matched to.
    without_vendor = without_vendor.merge(
        keys[["invoice_id", "vendor_id"]], on="invoice_id", how="left"
    )

    return pd.concat([with_vendor, without_vendor], ignore_index=True)


def classify_invoices(invoices: pd.DataFrame, matched_payments: pd.DataFrame) -> pd.DataFrame:
    """One row per invoice with what was paid, the gap and a status.

    The comparison happens in the invoice's own currency. Converting both sides
    to USD at different dates would turn exchange-rate movement into fake
    underpayments. A payment made in another currency is converted to the
    invoice currency through USD; the USD columns are for reporting only.
    """
    matched = matched_payments[matched_payments["match_status"] == "MATCHED"].merge(
        invoices[["invoice_id", "currency", "rate_to_usd"]].rename(
            columns={"currency": "invoice_currency", "rate_to_usd": "invoice_rate"}
        ),
        on="invoice_id",
    )
    same = matched["currency"] == matched["invoice_currency"]
    matched["paid_in_invoice_ccy"] = matched["amount"].where(same, matched["amount_usd"] / matched["invoice_rate"])

    paid = matched.groupby("invoice_id").agg(
        paid=("paid_in_invoice_ccy", "sum"),
        payment_count=("payment_id", "count"),
        reversal_count=("amount", lambda s: int((s < 0).sum())),
    )

    out = invoices.merge(paid, left_on="invoice_id", right_index=True, how="left")
    out["paid"] = out["paid"].fillna(0.0).round(2)
    out["payment_count"] = out["payment_count"].fillna(0).astype(int)
    out["reversal_count"] = out["reversal_count"].fillna(0).astype(int)
    out["gap"] = (out["amount"] - out["paid"]).round(2)
    out["paid_usd"] = (out["paid"] * out["rate_to_usd"]).round(2)
    out["gap_usd"] = (out["gap"] * out["rate_to_usd"]).round(2)

    def status(row: pd.Series) -> str:
        if row["payment_count"] == 0:
            return UNPAID
        if row["reversal_count"] > 0 and abs(row["paid"]) <= TOLERANCE:
            return REVERSED
        if abs(row["gap"]) <= TOLERANCE:
            return PAID
        return UNDERPAID if row["gap"] > 0 else OVERPAID

    out["status"] = out.apply(status, axis=1)
    # Only money the vendor is still owed is recoverable.
    out["recoverable_usd"] = out["gap_usd"].where(out["status"].isin([UNDERPAID, UNPAID, REVERSED]), 0.0)
    return out


def reconcile(invoices: pd.DataFrame, payments: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run the full reconciliation on cleaned, USD-converted frames.

    Returns (invoice_results, payment_exceptions). The exceptions are payments
    that could not be safely assigned (UNMATCHED_PAYMENT or AMBIGUOUS).
    """
    assigned = assign_payments(invoices, payments)
    results = classify_invoices(invoices, assigned)
    exceptions = assigned[assigned["match_status"] != "MATCHED"].reset_index(drop=True)
    return results, exceptions
