"""
index_build.py — compute skill prices and write public/index.json.

Price formula:
  raw_share[skill][month] = distinct postings mentioning skill / total distinct postings
  price[skill][month]     = raw_share indexed to 100 at earliest month

Momentum:
  mom_pct = (price[t] - price[t-1]) / price[t-1] * 100

Saturation (scarcity score):
  supply_score = weighted composite of normalised Udemy/NCES/GitHub signals
  raw_sat = supply_score / (demand_share + ε)
  scarcity = 1 - normalised(raw_sat) → 0=crowded, 100=scarce/opportunity
"""

from __future__ import annotations

import json
import os
from datetime import date
from typing import Any, Optional

import pandas as pd

from skills import SKILLS


MIN_POSTINGS_PER_MONTH = 50  # drop sparse months (noise, not signal)


def _compute_saturation_scores(
    demand_shares: dict[str, float],
    supply_df: "pd.DataFrame",
    month: str,
) -> dict[str, Optional[float]]:
    """
    Compute saturation score per skill for a given month.
    Returns {skill: 0-100 scarcity score} where:
      100 = very scarce (high demand, low supply) → opportunity
        0 = very crowded (low demand, high supply)
    Returns None for skills with no supply data.
    """
    if supply_df is None or supply_df.empty:
        return {s: None for s in demand_shares}

    month_supply = supply_df[supply_df["month"] == month]
    if month_supply.empty:
        return {s: None for s in demand_shares}

    supply_map = month_supply.set_index("skill")

    raw_saturations: dict[str, Any] = {}

    for skill, demand_share in demand_shares.items():
        if skill not in supply_map.index:
            raw_saturations[skill] = None
            continue

        row = supply_map.loc[skill]
        udemy = row.get("udemy_courses")
        stars = row.get("github_stars")
        nces  = row.get("nces_proxy")

        raw_saturations[skill] = {
            "udemy":  float(udemy) if pd.notna(udemy) else None,
            "stars":  float(stars) if pd.notna(stars) else None,
            "nces":   float(nces)  if pd.notna(nces)  else None,
            "demand": demand_share,
        }

    def _norm(values: list[Optional[float]]) -> list[Optional[float]]:
        valid = [v for v in values if v is not None]
        if not valid:
            return values
        lo, hi = min(valid), max(valid)
        span = hi - lo if hi != lo else 1.0
        return [None if v is None else (v - lo) / span for v in values]

    skills_with_data = [s for s, v in raw_saturations.items() if v is not None]
    if not skills_with_data:
        return {s: None for s in demand_shares}

    udemy_raw  = [raw_saturations[s]["udemy"]  for s in skills_with_data]
    stars_raw  = [raw_saturations[s]["stars"]  for s in skills_with_data]
    nces_raw   = [raw_saturations[s]["nces"]   for s in skills_with_data]
    demand_raw = [raw_saturations[s]["demand"] for s in skills_with_data]

    udemy_norm = _norm(udemy_raw)
    stars_norm = _norm(stars_raw)
    nces_norm  = _norm(nces_raw)
    # demand_raw kept as-is (raw share fractions) for the saturation ratio

    supply_scores: list[Optional[float]] = []
    for u, g, n in zip(udemy_norm, stars_norm, nces_norm):
        signals = [(u, 0.5), (n, 0.3), (g, 0.2)]
        available = [(v, w) for v, w in signals if v is not None]
        if not available:
            supply_scores.append(None)
            continue
        total_w = sum(w for _, w in available)
        supply_scores.append(sum(v * w for v, w in available) / total_w)

    # saturation = supply_norm / (raw_demand_share + ε) — high = crowded, low = scarce
    # Using raw demand shares (not normalised) to preserve absolute demand magnitude.
    # Flip to scarcity: scarcity = 1 - normalised_saturation → high = opportunity
    raw_sat: list[Optional[float]] = []
    for skill, sup in zip(skills_with_data, supply_scores):
        dem = demand_shares.get(skill, 0.0)
        if sup is None:
            raw_sat.append(None)
        else:
            raw_sat.append(sup / (dem + 1e-6))

    sat_norm = _norm(raw_sat)
    scarcity_scores = [None if v is None else round((1.0 - v) * 100, 1) for v in sat_norm]

    result: dict[str, Optional[float]] = {s: None for s in demand_shares}
    for skill, score in zip(skills_with_data, scarcity_scores):
        result[skill] = score
    return result


def build_index(df: pd.DataFrame, supply_df: "pd.DataFrame | None" = None) -> dict[str, Any]:
    """
    df: demand DataFrame with [month, skills (list)].
    supply_df: optional supply DataFrame with [skill, month, udemy_courses, github_stars, nces_proxy].
    """
    total_per_month: pd.Series = df.groupby("month").size()
    total_per_month = total_per_month[total_per_month >= MIN_POSTINGS_PER_MONTH]
    df = df[df["month"].isin(total_per_month.index)]
    months = sorted(total_per_month.index.tolist())

    demand_shares_by_month: dict[str, dict[str, float]] = {m: {} for m in months}

    skill_data: dict[str, Any] = {}

    for skill in SKILLS:
        mask = df["skills"].map(lambda s, sk=skill: sk in s)
        counts = df[mask].groupby("month").size().reindex(months, fill_value=0)
        totals = total_per_month.reindex(months, fill_value=1)
        raw_share = counts / totals

        for m in months:
            demand_shares_by_month[m][skill] = float(raw_share.get(m, 0))

        nonzero = raw_share[raw_share > 0]
        if nonzero.empty:
            series = [
                {"month": m, "price": 0.0, "share": 0.0, "count": int(counts[m]),
                 "mom_pct": None, "saturation": None}
                for m in months
            ]
            skill_data[skill] = {"series": series, "latest_momentum_pct": None, "latest_saturation": None}
            continue

        base_share = nonzero.iloc[0]
        price = (raw_share / base_share * 100).round(2)

        price_arr = price.tolist()
        mom_pct: list[Optional[float]] = [None]
        for i in range(1, len(price_arr)):
            prev, curr = price_arr[i - 1], price_arr[i]
            mom_pct.append(round((curr - prev) / prev * 100, 2) if prev else None)

        sat_scores_by_month: dict[str, Optional[float]] = {}
        for m in months:
            scores = _compute_saturation_scores(
                demand_shares_by_month[m],
                supply_df if supply_df is not None else pd.DataFrame(),
                m,
            )
            sat_scores_by_month[m] = scores.get(skill)

        series = [
            {
                "month": m,
                "price": float(price[m]),
                "share": round(float(raw_share[m]), 6),
                "count": int(counts[m]),
                "mom_pct": mom_pct[i],
                "saturation": sat_scores_by_month.get(m),
            }
            for i, m in enumerate(months)
        ]

        latest_mom = next((s["mom_pct"] for s in reversed(series) if s["mom_pct"] is not None), None)
        latest_sat = next((s["saturation"] for s in reversed(series) if s.get("saturation") is not None), None)

        skill_data[skill] = {
            "series": series,
            "latest_momentum_pct": latest_mom,
            "latest_saturation": latest_sat,
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
