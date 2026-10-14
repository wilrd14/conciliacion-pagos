"""Run the whole pipeline on the generated sample and check it against the planted scenarios."""

from pathlib import Path

import pandas as pd
import pytest

from conciliacion.__main__ import run

DATA = Path(__file__).resolve().parents[1] / "data" / "sample"


@pytest.fixture(scope="module")
def outputs(tmp_path_factory):
    out = tmp_path_factory.mktemp("output")
    summary = run(DATA, out)
    return out, summary


def test_status_counts_match_the_planted_scenarios(outputs):
    out, _ = outputs
    results = pd.read_csv(out / "invoice_results.csv")
    payments = pd.read_csv(DATA / "payments.csv")
    notes = payments["note"].value_counts()

    counts = results["status"].value_counts()
    assert counts["UNDERPAID"] == notes["short-paid (deduction)"]
    assert counts["REVERSED"] == notes["chargeback reversal"]
    assert counts["OVERPAID"] == notes["overpaid"]
    assert counts["PAID"] == notes["full"] + notes["partial 2/2"] + notes["remittance without vendor code"]


def test_only_the_three_planted_exceptions(outputs):
    out, _ = outputs
    exceptions = pd.read_csv(out / "payment_exceptions.csv")
    assert sorted(exceptions["match_status"]) == ["AMBIGUOUS", "UNMATCHED_PAYMENT", "UNMATCHED_PAYMENT"]


def test_all_output_files_are_written(outputs):
    out, summary = outputs
    for name in ["invoice_results.csv", "recovery_claims.csv", "payment_exceptions.csv", "vendor_summary.csv", "invoice_results.parquet"]:
        assert (out / name).exists()
    assert pd.read_parquet(out / "invoice_results.parquet").shape[0] == pd.read_csv(out / "invoice_results.csv").shape[0]
    assert summary["recoverable_usd"].is_monotonic_decreasing
