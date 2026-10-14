"""Currency conversion: every amount is compared in USD, using the rate in force on its date."""

from __future__ import annotations

import pandas as pd


def to_usd(df: pd.DataFrame, rates: pd.DataFrame, date_col: str) -> pd.DataFrame:
    """Add `rate_to_usd` and `amount_usd` columns.

    `rates` has columns date, currency, rate_to_usd (1 unit of currency = rate USD).
    Each row takes the latest rate published on or before its own date
    (pd.merge_asof per currency). USD rows always use 1.0. A row with no
    earlier rate keeps NaN, so a missing rate is visible instead of guessed.
    """
    rates = rates.copy()
    rates["date"] = pd.to_datetime(rates["date"])
    rates["currency"] = rates["currency"].str.strip().str.upper()

    df = df.copy()
    df["_row"] = range(len(df))
    usd = df[df["currency"] == "USD"].assign(rate_to_usd=1.0)
    other = df[df["currency"] != "USD"].sort_values(date_col)

    if other.empty:
        merged = other.assign(rate_to_usd=pd.Series(dtype=float))
    else:
        merged = pd.merge_asof(
            other,
            rates.sort_values("date"),
            left_on=date_col,
            right_on="date",
            by="currency",
            direction="backward",
        ).drop(columns="date")

    out = pd.concat([usd, merged]).sort_values("_row").drop(columns="_row")
    out["amount_usd"] = (out["amount"] * out["rate_to_usd"]).round(2)
    return out.reset_index(drop=True)
