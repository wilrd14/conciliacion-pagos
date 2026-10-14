import pandas as pd
import pytest

from conciliacion.reconcile import (
    AMBIGUOUS,
    OVERPAID,
    PAID,
    REVERSED,
    UNDERPAID,
    UNMATCHED_PAYMENT,
    UNPAID,
    reconcile,
)


def invoices(rows):
    df = pd.DataFrame(rows, columns=["invoice_id", "vendor_id", "invoice_key", "amount", "currency", "rate_to_usd"])
    df["amount_usd"] = df["amount"] * df["rate_to_usd"]
    return df


def payments(rows):
    df = pd.DataFrame(rows, columns=["payment_id", "vendor_id", "invoice_key", "amount", "currency", "rate_to_usd"])
    df["amount_usd"] = df["amount"] * df["rate_to_usd"]
    return df


def status_of(results, invoice_id):
    return results.set_index("invoice_id").loc[invoice_id, "status"]


def test_every_status():
    inv = invoices(
        [
            ("I1", "V1", "1", 100.0, "USD", 1.0),  # paid in full
            ("I2", "V1", "2", 100.0, "USD", 1.0),  # paid in two parts
            ("I3", "V1", "3", 100.0, "USD", 1.0),  # short-paid
            ("I4", "V1", "4", 100.0, "USD", 1.0),  # never paid
            ("I5", "V1", "5", 100.0, "USD", 1.0),  # paid then reversed
            ("I6", "V1", "6", 100.0, "USD", 1.0),  # overpaid
        ]
    )
    pay = payments(
        [
            ("P1", "V1", "1", 100.0, "USD", 1.0),
            ("P2", "V1", "2", 60.0, "USD", 1.0),
            ("P3", "V1", "2", 40.0, "USD", 1.0),
            ("P4", "V1", "3", 90.0, "USD", 1.0),
            ("P5", "V1", "5", 100.0, "USD", 1.0),
            ("P6", "V1", "5", -100.0, "USD", 1.0),
            ("P7", "V1", "6", 105.0, "USD", 1.0),
        ]
    )
    results, exceptions = reconcile(inv, pay)
    assert status_of(results, "I1") == PAID
    assert status_of(results, "I2") == PAID
    assert status_of(results, "I3") == UNDERPAID
    assert status_of(results, "I4") == UNPAID
    assert status_of(results, "I5") == REVERSED
    assert status_of(results, "I6") == OVERPAID
    assert exceptions.empty
    recoverable = results.set_index("invoice_id")["recoverable_usd"]
    assert recoverable["I3"] == pytest.approx(10.0)
    assert recoverable["I4"] == pytest.approx(100.0)
    assert recoverable["I5"] == pytest.approx(100.0)
    assert recoverable["I6"] == 0.0  # overpayment is not money the vendor is owed


def test_same_number_at_two_vendors_is_matched_by_vendor():
    inv = invoices([("A", "V1", "7", 50.0, "USD", 1.0), ("B", "V2", "7", 80.0, "USD", 1.0)])
    pay = payments([("P1", "V2", "7", 80.0, "USD", 1.0)])
    results, _ = reconcile(inv, pay)
    assert status_of(results, "B") == PAID
    assert status_of(results, "A") == UNPAID


def test_payment_without_vendor_and_shared_number_is_ambiguous_not_guessed():
    inv = invoices([("A", "V1", "7", 50.0, "USD", 1.0), ("B", "V2", "7", 50.0, "USD", 1.0)])
    pay = payments([("P1", None, "7", 50.0, "USD", 1.0)])
    results, exceptions = reconcile(inv, pay)
    assert list(exceptions["match_status"]) == [AMBIGUOUS]
    # Neither invoice is credited with a payment we could not attribute.
    assert set(results["status"]) == {UNPAID}


def test_payment_without_vendor_and_unique_number_is_matched_and_gets_vendor():
    inv = invoices([("A", "V1", "8", 50.0, "USD", 1.0)])
    pay = payments([("P1", None, "8", 50.0, "USD", 1.0)])
    results, exceptions = reconcile(inv, pay)
    assert status_of(results, "A") == PAID
    assert exceptions.empty


def test_unknown_or_missing_reference_is_unmatched():
    inv = invoices([("A", "V1", "8", 50.0, "USD", 1.0)])
    pay = payments([("P1", "V1", "999", 10.0, "USD", 1.0), ("P2", "V1", None, 5.0, "USD", 1.0)])
    _, exceptions = reconcile(inv, pay)
    assert list(exceptions["match_status"]) == [UNMATCHED_PAYMENT, UNMATCHED_PAYMENT]


def test_exchange_rate_movement_is_not_an_underpayment():
    # Invoiced 100 EUR when EUR = 1.10 USD, paid 100 EUR later when EUR = 1.05 USD.
    inv = invoices([("A", "V1", "9", 100.0, "EUR", 1.10)])
    pay = payments([("P1", "V1", "9", 100.0, "EUR", 1.05)])
    results, _ = reconcile(inv, pay)
    assert status_of(results, "A") == PAID


def test_payment_in_another_currency_is_converted_to_the_invoice_currency():
    # 100 EUR invoice at 1.10 = 110 USD; paid 110 USD.
    inv = invoices([("A", "V1", "10", 100.0, "EUR", 1.10)])
    pay = payments([("P1", "V1", "10", 110.0, "USD", 1.0)])
    results, _ = reconcile(inv, pay)
    assert status_of(results, "A") == PAID


def test_money_is_conserved():
    inv = invoices([("A", "V1", "1", 100.0, "USD", 1.0), ("B", "V1", "2", 200.0, "USD", 1.0)])
    pay = payments([("P1", "V1", "1", 70.0, "USD", 1.0), ("P2", "V1", "2", 200.0, "USD", 1.0)])
    results, _ = reconcile(inv, pay)
    assert results["paid_usd"].sum() + results["gap_usd"].sum() == pytest.approx(results["amount_usd"].sum())
