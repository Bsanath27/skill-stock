"""
index_build.py — compute skill prices and write public/index.json.

Price formula:
  raw_share[skill][month] = distinct postings mentioning skill / total distinct postings
  price[skill][month]     = raw_share indexed to 100 at earliest month

Momentum:
  mom_pct = (price[t] - price[t-1]) / price[t-1] * 100
"""

from __future__ import annotations

import json
import os
from datetime import date
from typing import Any

import pandas as pd

from skills import SKILLS


def build_index(df: pd.DataFrame) -> dict[str, Any]:
    """
    df must have columns: month (YYYY-MM str), skills (list of canonical names).
    Returns the full index dict ready for JSON serialisation.
    """
    # Total distinct postings per month (denominator)
    total_per_month: pd.Series = df.groupby("month").size()

    months = sorted(total_per_month.index.tolist())

    skill_data: dict[str, Any] = {}

    for skill in SKILLS:
        # Count distinct postings mentioning this skill per month
        mask = df["skills"].map(lambda s, sk=skill: sk in s)
        counts = df[mask].groupby("month").size().reindex(months, fill_value=0)
        totals = total_per_month.reindex(months, fill_value=1)

        raw_share = counts / totals  # fraction 0–1

        # Index to 100 at first non-zero month
        nonzero = raw_share[raw_share > 0]
        if nonzero.empty:
            # Skill never found — include flat line at 0 so frontend knows it exists
            series = [
                {"month": m, "price": 0.0, "share": 0.0, "count": int(counts[m])}
                for m in months
            ]
            skill_data[skill] = {"series": series, "latest_momentum_pct": None}
            continue

        base_month = nonzero.index[0]
        base_share = nonzero.iloc[0]
        price = (raw_share / base_share * 100).round(2)

        # MoM momentum
        price_arr = price.tolist()
        mom_pct: list[float | None] = [None]
        for i in range(1, len(price_arr)):
            prev = price_arr[i - 1]
            curr = price_arr[i]
            if prev and prev != 0:
                mom_pct.append(round((curr - prev) / prev * 100, 2))
            else:
                mom_pct.append(None)

        series = [
            {
                "month": m,
                "price": float(price[m]),
                "share": round(float(raw_share[m]), 6),
                "count": int(counts[m]),
                "mom_pct": mom_pct[i],
            }
            for i, m in enumerate(months)
        ]

        latest_mom = next(
            (s["mom_pct"] for s in reversed(series) if s["mom_pct"] is not None), None
        )
        skill_data[skill] = {
            "series": series,
            "latest_momentum_pct": latest_mom,
        }

    data_through = months[-1] if months else "unknown"
    return {
        "generated_at": str(date.today()),
        "data_through": data_through,
        "total_months": len(months),
        "total_postings": len(df),
        "skills": skill_data,
    }


def write_index(index: dict[str, Any], out_path: str = "public/index.json") -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(index, f, separators=(",", ":"))
    size_kb = os.path.getsize(out_path) / 1024
    print(f"  Wrote {out_path} ({size_kb:.1f} KB)")
