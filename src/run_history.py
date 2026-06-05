"""
run_history.py — one-time historical backfill. Safe to re-run (all sources cache-first).

Usage:
  python src/run_history.py                          # full backfill
  python src/run_history.py --start 2022-01          # custom start month
  python src/run_history.py --hn-only                # skip SO survey download
  python src/run_history.py --no-salary              # skip Kaggle salary
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import date
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd

from ingest.raw_store import RawStore
from ingest import hn_hiring, stackoverflow_survey, kaggle_salary
import pipeline
import index_build

STORE    = RawStore()
OUT_PATH = os.environ.get("OUT_PATH", "public/index.json")


def _load_live_demand(month: str) -> pd.DataFrame:
    """Load cached live demand for month from disk. Returns empty DF if nothing cached."""
    frames: list[pd.DataFrame] = []

    cached = STORE.load("demand/adzuna", month)
    if cached:
        from ingest.adzuna import _to_df as _adzuna_df
        frames.append(_adzuna_df(cached, month))

    cached = STORE.load("demand/remotive", month)
    if cached:
        from ingest.remotive import _to_df as _remotive_df
        frames.append(_remotive_df(cached, month))

    fc_dir = STORE._base / "demand" / "firecrawl" / month
    if fc_dir.exists():
        fc_records = []
        for p in fc_dir.glob("*.json"):
            try:
                fc_records.extend(json.loads(p.read_text()))
            except Exception:
                pass
        if fc_records:
            from ingest.firecrawl_ats import _to_df as _fc_df
            frames.append(_fc_df(fc_records, month))

    if not frames:
        return pd.DataFrame()

    merged = pd.concat(frames, ignore_index=True)
    merged = pipeline.cross_source_dedup(merged)
    return pipeline.run(merged)


def main() -> None:
    parser = argparse.ArgumentParser(description="Historical backfill for Skill Stock.")
    parser.add_argument("--start",     default="2020-01", help="Start month YYYY-MM (default: 2020-01)")
    parser.add_argument("--end",       default="2025-12", help="End month YYYY-MM (default: 2025-12)")
    parser.add_argument("--hn-only",   action="store_true", help="Skip SO survey download")
    parser.add_argument("--no-salary", action="store_true", help="Skip Kaggle salary extraction")
    args = parser.parse_args()

    # 1. Kaggle salary (fast, local files only)
    salary_data: dict = {}
    if not args.no_salary:
        print("[history] Extracting Kaggle salary data ...")
        salary_data = kaggle_salary.fetch()

    # 2. Stack Overflow survey (downloads ZIPs — ~200MB total, cached after first run)
    so_data: dict | None = None
    if not args.hn_only:
        print("[history] Fetching Stack Overflow survey data ...")
        so_data = stackoverflow_survey.fetch_all()

    # 3. HN historical demand
    print(f"[history] Fetching HN Who's Hiring {args.start} → {args.end} ...")
    hn_raw = hn_hiring.fetch_range(args.start, args.end, STORE)

    hist_df = pd.DataFrame()
    if not hn_raw.empty:
        print("[history] Running pipeline on HN data ...")
        hist_df = pipeline.run(hn_raw)
        months_found = hist_df["month"].nunique()
        print(f"[history] HN: {len(hist_df):,} rows across {months_found} months")

    # 4. Load live demand from cache (avoids re-fetching Adzuna)
    current_month = date.today().strftime("%Y-%m")
    print(f"[history] Loading cached live demand for {current_month} ...")
    live_df = _load_live_demand(current_month)

    if live_df.empty and hist_df.empty:
        print("ERROR: no demand data available (no cache and no HN data)")
        sys.exit(1)

    # If live demand is empty, use HN data as the primary series
    if live_df.empty:
        print("[history] No live demand cache — using HN data as primary series")
        live_df = hist_df
        hist_df = pd.DataFrame()

    # 5. Build and write index
    print("[history] Building index ...")
    idx = index_build.build_index(
        live_df,
        supply_df=None,
        hist_df=hist_df if not hist_df.empty else None,
        so_data=so_data,
        salary_data=salary_data if salary_data else None,
    )
    index_build.write_index(idx, OUT_PATH)
    print(f"[history] Done. {idx['total_months']} months, {idx['total_postings']:,} postings.")


if __name__ == "__main__":
    main()
