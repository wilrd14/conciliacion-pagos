"""Summaries a non-technical reader can act on, written to CSV and Parquet."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

STATUS_ORDER = ["UNPAID", "UNDERPAID", "REVERSED", "OVERPAID", "PAID"]


def summary_by_vendor(results: pd.DataFrame) -> pd.DataFrame:
    """Invoice count per status and recoverable USD, one row per vendor."""
    counts = pd.crosstab(results["vendor_id"], results["status"])
    counts = counts.reindex(columns=[s for s in STATUS_ORDER if s in counts.columns], fill_value=0)
    money = results.groupby("vendor_id").agg(
        invoiced_usd=("amount_usd", "sum"),
        paid_usd=("paid_usd", "sum"),
        recoverable_usd=("recoverable_usd", "sum"),
    ).round(2)
    return counts.join(money).sort_values("recoverable_usd", ascending=False).reset_index()


def write_reports(results: pd.DataFrame, exceptions: pd.DataFrame, out_dir: Path) -> dict[str, Path]:
    """Write every output file and return their paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    recovery = results[results["recoverable_usd"] > 0].sort_values("recoverable_usd", ascending=False)
    files = {
        "invoice_results": out_dir / "invoice_results.csv",
        "recovery_claims": out_dir / "recovery_claims.csv",
        "payment_exceptions": out_dir / "payment_exceptions.csv",
        "vendor_summary": out_dir / "vendor_summary.csv",
        "invoice_results_parquet": out_dir / "invoice_results.parquet",
    }
    results.to_csv(files["invoice_results"], index=False)
    recovery.to_csv(files["recovery_claims"], index=False)
    exceptions.to_csv(files["payment_exceptions"], index=False)
    summary_by_vendor(results).to_csv(files["vendor_summary"], index=False)
    results.to_parquet(files["invoice_results_parquet"], index=False)
    return files
