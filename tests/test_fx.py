import pandas as pd

from conciliacion.fx import to_usd

RATES = pd.DataFrame(
    {
        "date": ["2026-08-01", "2026-08-08", "2026-08-01"],
        "currency": ["EUR", "EUR", "CAD"],
        "rate_to_usd": [1.10, 1.20, 0.70],
    }
)


def test_uses_latest_rate_on_or_before_the_date():
    df = pd.DataFrame(
        {
            "amount": [100.0, 100.0, 100.0, 50.0],
            "currency": ["EUR", "EUR", "CAD", "USD"],
            "d": pd.to_datetime(["2026-08-05", "2026-08-08", "2026-08-20", "2026-08-05"]),
        }
    )
    out = to_usd(df, RATES, "d")
    assert list(out["rate_to_usd"]) == [1.10, 1.20, 0.70, 1.0]
    assert list(out["amount_usd"]) == [110.0, 120.0, 70.0, 50.0]


def test_keeps_original_row_order():
    df = pd.DataFrame(
        {"amount": [1.0, 2.0, 3.0], "currency": ["EUR", "USD", "EUR"], "d": pd.to_datetime(["2026-08-09", "2026-08-01", "2026-08-02"])}
    )
    assert list(to_usd(df, RATES, "d")["amount"]) == [1.0, 2.0, 3.0]


def test_missing_rate_stays_visible_as_nan():
    df = pd.DataFrame({"amount": [10.0], "currency": ["EUR"], "d": pd.to_datetime(["2026-07-01"])})
    assert to_usd(df, RATES, "d")["amount_usd"].isna().all()
