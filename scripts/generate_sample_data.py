"""Generate a fictional, reproducible dataset with the problems real payment data has.

No real company or customer data is used. Run: python scripts/generate_sample_data.py
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

SEED = 42
OUT = Path(__file__).resolve().parents[1] / "data" / "sample"
VENDORS = ["VND-01", "VND-02", "VND-03", "VND-04", "VND-05"]
CURRENCIES = {"USD": 1.0, "EUR": 1.08, "CAD": 0.73}


def messy_ref(number: int, rng: random.Random) -> str:
    """Write the same invoice number the inconsistent ways payment files do."""
    styles = [
        f"INV-{number:06d}",
        f"inv{number}",
        f" {number} ",
        f"Factura #{number:05d}",
        f"INV {number}",
    ]
    return rng.choice(styles)


def fx_rates(start: date, days: int, rng: random.Random) -> pd.DataFrame:
    rows = []
    for d in range(0, days, 7):  # weekly rates, so merge_asof has to look back
        day = start + timedelta(days=d)
        for cur, base in CURRENCIES.items():
            if cur != "USD":
                rows.append({"date": day.isoformat(), "currency": cur, "rate_to_usd": round(base * rng.uniform(0.97, 1.03), 4)})
    return pd.DataFrame(rows)


def build(rng: random.Random) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    start = date(2026, 7, 1)
    invoices, payments = [], []
    pay_seq = 1

    def pay(vendor, ref, day, amount, currency, note):
        nonlocal pay_seq
        payments.append({
            "payment_id": f"PAY-{pay_seq:05d}", "vendor_id": vendor, "invoice_ref": ref,
            "payment_date": day.isoformat(), "amount": amount, "currency": currency, "note": note,
        })
        pay_seq += 1

    number = 1000
    for i in range(120):
        number += rng.randint(1, 5)
        vendor = rng.choice(VENDORS)
        currency = rng.choices(list(CURRENCIES), weights=[6, 2, 2])[0]
        inv_day = start + timedelta(days=rng.randint(0, 60))
        amount = round(rng.uniform(80, 5000), 2)
        invoices.append({
            "invoice_id": f"I{i + 1:04d}", "vendor_id": vendor if rng.random() > 0.1 else vendor.lower() + " ",
            "invoice_number": f"INV-{number:06d}", "invoice_date": inv_day.isoformat(),
            "amount": f"{amount:,.2f}", "currency": currency,
        })
        pay_day = inv_day + timedelta(days=rng.randint(10, 40))
        scenario = rng.choices(
            ["paid", "split", "under", "unpaid", "reversed", "over", "no_vendor"],
            weights=[45, 12, 15, 10, 5, 4, 9],
        )[0]
        ref = messy_ref(number, rng)
        if scenario == "paid":
            pay(vendor, ref, pay_day, amount, currency, "full")
        elif scenario == "split":
            first = round(amount * 0.6, 2)
            pay(vendor, ref, pay_day, first, currency, "partial 1/2")
            pay(vendor, messy_ref(number, rng), pay_day + timedelta(days=7), round(amount - first, 2), currency, "partial 2/2")
        elif scenario == "under":
            pay(vendor, ref, pay_day, round(amount * rng.uniform(0.70, 0.97), 2), currency, "short-paid (deduction)")
        elif scenario == "reversed":
            pay(vendor, ref, pay_day, amount, currency, "paid")
            pay(vendor, ref, pay_day + timedelta(days=5), f"({amount:,.2f})", currency, "chargeback reversal")
        elif scenario == "over":
            pay(vendor, ref, pay_day, round(amount * 1.05, 2), currency, "overpaid")
        elif scenario == "no_vendor":
            pay(None, ref, pay_day, amount, currency, "remittance without vendor code")
        # "unpaid": no payment at all

    # Same invoice number issued by two vendors: a payment without vendor code is ambiguous.
    number += 1
    for i, vendor in enumerate(["VND-01", "VND-02"]):
        invoices.append({
            "invoice_id": f"IDUP{i + 1}", "vendor_id": vendor, "invoice_number": f"INV-{number:06d}",
            "invoice_date": "2026-08-01", "amount": "500.00", "currency": "USD",
        })
    pay(None, f"inv{number}", date(2026, 8, 20), 500.00, "USD", "ambiguous: two vendors share this number")

    # Payments that point at invoices that do not exist.
    pay("VND-03", "INV-999999", date(2026, 8, 15), 250.00, "USD", "unknown invoice")
    pay("VND-04", "", date(2026, 8, 16), 75.50, "USD", "missing reference")

    # An exact duplicate invoice row (exported twice).
    invoices.append(dict(invoices[0]))

    return pd.DataFrame(invoices), pd.DataFrame(payments), fx_rates(start - timedelta(days=7), 140, rng)


def main() -> None:
    rng = random.Random(SEED)
    invoices, payments, rates = build(rng)
    OUT.mkdir(parents=True, exist_ok=True)
    invoices.to_csv(OUT / "invoices.csv", index=False)
    payments.to_csv(OUT / "payments.csv", index=False)
    rates.to_csv(OUT / "fx_rates.csv", index=False)
    print(f"{len(invoices)} invoices, {len(payments)} payments, {len(rates)} rates -> {OUT}")


if __name__ == "__main__":
    main()
