"""Command line entry point: python -m conciliacion --data data/sample --out output"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from conciliacion.fx import to_usd
from conciliacion.normalize import clean_invoices, clean_payments
from conciliacion.reconcile import reconcile
from conciliacion.report import summary_by_vendor, write_reports


def run(data_dir: Path, out_dir: Path) -> pd.DataFrame:
    rates = pd.read_csv(data_dir / "fx_rates.csv")
    invoices = to_usd(clean_invoices(pd.read_csv(data_dir / "invoices.csv", dtype=str)), rates, "invoice_date")
    payments = to_usd(clean_payments(pd.read_csv(data_dir / "payments.csv", dtype=str)), rates, "payment_date")

    missing_rate = pd.concat([invoices, payments])["amount_usd"].isna().sum()
    if missing_rate:
        raise SystemExit(f"{missing_rate} rows have no exchange rate for their date; add rates to fx_rates.csv")

    results, exceptions = reconcile(invoices, payments)
    files = write_reports(results, exceptions, out_dir)

    print(f"Invoices: {len(results)}  |  Payment exceptions: {len(exceptions)}")
    print(results["status"].value_counts().to_string())
    print(f"Recoverable: USD {results['recoverable_usd'].sum():,.2f}")
    for name, path in files.items():
        print(f"  {name}: {path}")
    return summary_by_vendor(results)


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile vendor invoices against payments.")
    parser.add_argument("--data", type=Path, default=Path("data/sample"))
    parser.add_argument("--out", type=Path, default=Path("output"))
    args = parser.parse_args()
    run(args.data, args.out)


if __name__ == "__main__":
    main()
