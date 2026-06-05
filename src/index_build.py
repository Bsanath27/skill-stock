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


MIN_POSTINGS_PER_MONTH = 50


def _compute_saturation_scores(
    demand_shares: dict[str, float],
    supply_df: "pd.DataFrame",
    month: str,
) -> dict[str, Optional[float]]:
    """
    Compute saturation score per skill for a given month.
    Returns {skill: 0-100 scarcity score} where 100=scarce, 0=crowded.
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
        raw_saturations[skill] = {
            "udemy":  float(row.get("udemy_courses")) if pd.notna(row.get("udemy_courses")) else None,
            "stars":  float(row.get("github_stars"))  if pd.notna(row.get("github_stars"))  else None,
            "nces":   float(row.get("nces_proxy"))    if pd.notna(row.get("nces_proxy"))    else None,
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

    udemy_norm = _norm([raw_saturations[s]["udemy"]  for s in skills_with_data])
    stars_norm = _norm([raw_saturations[s]["stars"]  for s in skills_with_data])
    nces_norm  = _norm([raw_saturations[s]["nces"]   for s in skills_with_data])

    supply_scores: list[Optional[float]] = []
    for u, g, n in zip(udemy_norm, stars_norm, nces_norm):
        available = [(v, w) for v, w in [(u, 0.5), (n, 0.3), (g, 0.2)] if v is not None]
        if not available:
            supply_scores.append(None)
            continue
        total_w = sum(w for _, w in available)
        supply_scores.append(sum(v * w for v, w in available) / total_w)

    raw_sat: list[Optional[float]] = []
    for skill, sup in zip(skills_with_data, supply_scores):
        dem = demand_shares.get(skill, 0.0)
        raw_sat.append(None if sup is None else sup / (dem + 1e-6))

    sat_norm = _norm(raw_sat)
    scarcity = [None if v is None else round((1.0 - v) * 100, 1) for v in sat_norm]

    result: dict[str, Optional[float]] = {s: None for s in demand_shares}
    for skill, score in zip(skills_with_data, scarcity):
        result[skill] = score
    return result


def _build_skill_series(
    df: pd.DataFrame,
    supply_df: "pd.DataFrame | None" = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Build price series for one corpus. Returns (skill_data, months).
    skill_data: {skill: {series, latest_momentum_pct, latest_saturation}}
    """
    total_per_month: pd.Series = df.groupby("month").size()
    total_per_month = total_per_month[total_per_month >= MIN_POSTINGS_PER_MONTH]
    df = df[df["month"].isin(total_per_month.index)]
    months = sorted(total_per_month.index.tolist())

    if not months:
        empty: dict[str, Any] = {
            s: {"series": [], "latest_momentum_pct": None, "latest_saturation": None}
            for s in SKILLS
        }
        return empty, []

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

        sat_by_month: dict[str, Optional[float]] = {}
        for m in months:
            scores = _compute_saturation_scores(
                demand_shares_by_month[m],
                supply_df if supply_df is not None else pd.DataFrame(),
                m,
            )
            sat_by_month[m] = scores.get(skill)

        series = [
            {
                "month": m,
                "price": float(price[m]),
                "share": round(float(raw_share[m]), 6),
                "count": int(counts[m]),
                "mom_pct": mom_pct[i],
                "saturation": sat_by_month.get(m),
            }
            for i, m in enumerate(months)
        ]

        latest_mom = next((s["mom_pct"] for s in reversed(series) if s["mom_pct"] is not None), None)
        latest_sat = next((s["saturation"] for s in reversed(series) if s.get("saturation") is not None), None)
        skill_data[skill] = {"series": series, "latest_momentum_pct": latest_mom, "latest_saturation": latest_sat}

    return skill_data, months


def build_index(
    df: pd.DataFrame,
    supply_df: "pd.DataFrame | None" = None,
    hist_df: "pd.DataFrame | None" = None,
    so_data: "dict | None" = None,
    salary_data: "dict | None" = None,
) -> dict[str, Any]:
    """
    Build the full skill index.

    df:           live demand (Adzuna + Remotive + Firecrawl) — required.
    supply_df:    optional Udemy/GitHub/NCES supply signals for the live months.
    hist_df:      optional HN historical demand. Price series are built separately
                  for each corpus then concatenated. mom_pct is nulled at the
                  source boundary (first live data point).
    so_data:      optional {skill: [{year, pct}, ...]} from SO survey.
    salary_data:  optional {skill: {p25, median, p75, n}} from Kaggle.
    """
    live_skill_data, _ = _build_skill_series(df, supply_df)

    hist_skill_data: dict[str, Any] = {}
    if hist_df is not None and not hist_df.empty:
        hist_skill_data, _ = _build_skill_series(hist_df)

    merged_skill_data: dict[str, Any] = {}
    for skill in SKILLS:
        live = live_skill_data.get(
            skill, {"series": [], "latest_momentum_pct": None, "latest_saturation": None}
        )
        hist_series = hist_skill_data.get(skill, {}).get("series", [])
        live_series = list(live.get("series", []))

        # Null out mom_pct at source boundary (first live point after historical)
        if live_series and hist_series:
            live_series[0] = {**live_series[0], "mom_pct": None}

        merged_series = sorted(hist_series + live_series, key=lambda p: p["month"])

        merged_skill_data[skill] = {
            "series": merged_series,
            "latest_momentum_pct": live.get("latest_momentum_pct"),
            "latest_saturation": live.get("latest_saturation"),
            "so_series": (so_data or {}).get(skill, []),
            "salary": (salary_data or {}).get(skill),
        }

    all_months = sorted({p["month"] for s in merged_skill_data.values() for p in s["series"]})
    total_postings = len(df) + (len(hist_df) if hist_df is not None else 0)

    return {
        "generated_at": str(date.today()),
        "data_through": all_months[-1] if all_months else "unknown",
        "total_months": len(all_months),
        "total_postings": total_postings,
        "skills": merged_skill_data,
    }


def write_index(index: dict[str, Any], out_path: str = "public/index.json") -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(index, f, separators=(",", ":"))
    size_kb = os.path.getsize(out_path) / 1024
    print(f"  Wrote {out_path} ({size_kb:.1f} KB)")
