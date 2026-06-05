"""
fetch_adzuna.py — pull current-month job postings from Adzuna and append to index.json.

For each skill in SKILLS, queries Adzuna's search API (up to MAX_PAGES pages).
All results are deduped by Adzuna job ID, then fed through the same pipeline.py
and index_build.py functions used for the Kaggle data.

Environment variables required:
  ADZUNA_APP_ID   — your Adzuna application ID
  ADZUNA_APP_KEY  — your Adzuna API key

Usage:
  python src/fetch_adzuna.py
  python src/fetch_adzuna.py --country gb   # defaults to us
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime
from typing import Any

import requests
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import pipeline
import index_build
from skills import SKILLS

# ── Config ───────────────────────────────────────────────────────────────────

BASE_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
RESULTS_PER_PAGE = 50   # Adzuna max
MAX_PAGES = 2           # 100 results per skill — keeps API calls bounded
SLEEP_BETWEEN = 0.3     # seconds between requests (polite rate limiting)

OUT_PATH = os.environ.get("OUT_PATH", "public/index.json")


# ── Fetch ────────────────────────────────────────────────────────────────────

def fetch_skill_jobs(
    skill: str,
    app_id: str,
    app_key: str,
    country: str,
    month: str,
) -> list[dict[str, Any]]:
    """Fetch up to MAX_PAGES * RESULTS_PER_PAGE Adzuna results for one skill."""
    all_results = []
    for page in range(1, MAX_PAGES + 1):
        url = BASE_URL.format(country=country, page=page)
        params = {
            "app_id": app_id,
            "app_key": app_key,
            "what": skill,
            "results_per_page": RESULTS_PER_PAGE,
            "content-type": "application/json",
        }
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"    [warn] {skill} page {page}: {e}")
            break

        results = data.get("results", [])
        all_results.extend(results)

        if len(results) < RESULTS_PER_PAGE:
            break   # no more pages

        time.sleep(SLEEP_BETWEEN)

    return all_results


def fetch_all(app_id: str, app_key: str, country: str) -> pd.DataFrame:
    """
    Fetch jobs for every skill, deduplicate by Adzuna job ID,
    and return a DataFrame matching the pipeline input schema.
    """
    month = date.today().strftime("%Y-%m")
    seen_ids: set[str] = set()
    rows: list[dict[str, Any]] = []

    for i, skill in enumerate(SKILLS, 1):
        print(f"  [{i:2d}/{len(SKILLS)}] Fetching: {skill}")
        results = fetch_skill_jobs(skill, app_id, app_key, country, month)

        for r in results:
            job_id = str(r.get("id", ""))
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            company = r.get("company", {}).get("display_name", "")
            title = r.get("title", "")
            location = r.get("location", {}).get("display_name", "")
            description = r.get("description", "")
            created = r.get("created", "")

            rows.append({
                "company_norm": pipeline.normalise_text(company),
                "title_norm": pipeline.normalise_text(title),
                "location_norm": pipeline.normalise_text(location),
                "month": month,
                "text": f"{title} {description}",
            })

        time.sleep(SLEEP_BETWEEN)

    print(f"  Unique jobs fetched: {len(rows):,}")
    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["company_norm", "title_norm", "location_norm", "month", "text"]
    )


# ── Append to index.json ──────────────────────────────────────────────────────

def append_month(new_index: dict, month: str) -> None:
    """
    Load existing index.json, replace or append the new month's data points
    for each skill, then write back.
    """
    if not os.path.exists(OUT_PATH):
        print(f"  No existing {OUT_PATH} — writing fresh index.")
        index_build.write_index(new_index, OUT_PATH)
        return

    with open(OUT_PATH) as f:
        existing = json.load(f)

    for skill, data in new_index["skills"].items():
        if skill not in existing["skills"]:
            existing["skills"][skill] = data
            continue

        # Find the new month point
        new_pt = next((s for s in data["series"] if s["month"] == month), None)
        if not new_pt:
            continue

        old_series = existing["skills"][skill]["series"]

        # Rebase the new share onto the existing price scale.
        # Existing series: price = (share / base_share) * 100 where
        # base_share = share of the first non-zero point.
        # So: new_price = (new_share / base_share) * 100.
        base_pts = [s for s in old_series if s.get("share", 0) > 0]
        if base_pts:
            base_share = base_pts[0]["share"]
            new_price = round((new_pt["share"] / base_share * 100) if base_share else 0.0, 2)
        else:
            new_price = new_pt["price"]  # nothing to rebase against

        # Tag the new point as Adzuna so the UI can annotate it.
        # Null out mom_pct — cross-source momentum isn't meaningful (different
        # corpus composition: Adzuna is tech-biased, Kaggle is full market).
        new_pt = {**new_pt, "price": new_price, "source": "adzuna", "mom_pct": None}

        # Replace if month already exists, else append
        months_in_old = [s["month"] for s in old_series]
        if month in months_in_old:
            idx = months_in_old.index(month)
            old_series[idx] = new_pt
        else:
            old_series.append(new_pt)
            old_series.sort(key=lambda s: s["month"])

        # Recalculate momentum only within same source
        for i in range(1, len(old_series)):
            cur = old_series[i]
            prev = old_series[i - 1]
            same_source = cur.get("source", "kaggle") == prev.get("source", "kaggle")
            if same_source and prev["price"]:
                cur["mom_pct"] = round((cur["price"] - prev["price"]) / prev["price"] * 100, 2)
            else:
                cur["mom_pct"] = None  # cross-source gap — not comparable
        old_series[0].setdefault("mom_pct", None)

        existing["skills"][skill]["series"] = old_series
        existing["skills"][skill]["latest_momentum_pct"] = next(
            (s["mom_pct"] for s in reversed(old_series) if s.get("mom_pct") is not None),
            None,
        )

    existing["data_through"] = max(existing["data_through"], month)
    existing["generated_at"] = str(date.today())
    existing["total_postings"] = existing.get("total_postings", 0)  # keep old count

    with open(OUT_PATH, "w") as f:
        json.dump(existing, f, separators=(",", ":"))
    size_kb = os.path.getsize(OUT_PATH) / 1024
    print(f"  Updated {OUT_PATH} ({size_kb:.1f} KB) — appended month {month}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--country", default="us", help="Adzuna country code (default: us)")
    args = parser.parse_args()

    app_id  = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")

    if not app_id or not app_key:
        print("ERROR: Set ADZUNA_APP_ID and ADZUNA_APP_KEY environment variables.")
        sys.exit(1)

    month = date.today().strftime("%Y-%m")
    print(f"Fetching Adzuna data for {month} (country={args.country}) ...")
    raw_df = fetch_all(app_id, app_key, args.country)

    if raw_df.empty:
        print("No data returned — aborting.")
        sys.exit(1)

    print("Running pipeline ...")
    clean_df = pipeline.run(raw_df)

    print("Building index for new month ...")
    new_index = index_build.build_index(clean_df)

    append_month(new_index, month)
    print("Done.")


if __name__ == "__main__":
    main()
