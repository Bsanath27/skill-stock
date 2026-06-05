"""
run_all.py — orchestrate all demand sources → pipeline → index.json.

Phase 3 (demand only):
  python src/run_all.py

Phase 4 (demand + supply — after Tasks 8-12):
  python src/run_all.py --supply
"""
from __future__ import annotations
import argparse
import os
import sys
from datetime import date
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd

from ingest.raw_store import RawStore
from ingest import adzuna, remotive, firecrawl_ats
import pipeline
import index_build

STORE = RawStore()
OUT_PATH = os.environ.get("OUT_PATH", "public/index.json")


def run_demand(month: str) -> pd.DataFrame:
    """Fetch all demand sources, merge, cross-source dedup, run pipeline."""
    frames = []

    # Adzuna (requires ADZUNA_APP_ID + ADZUNA_APP_KEY)
    if os.environ.get("ADZUNA_APP_ID"):
        print("[demand] Fetching Adzuna ...")
        frames.append(adzuna.fetch(month, STORE))
    else:
        print("[demand] Skipping Adzuna — ADZUNA_APP_ID not set")

    # Remotive (no auth)
    print("[demand] Fetching Remotive ...")
    frames.append(remotive.fetch(month, STORE))

    # Firecrawl ATS (requires FIRECRAWL_API_KEY)
    if os.environ.get("FIRECRAWL_API_KEY"):
        print("[demand] Fetching Firecrawl ATS ...")
        frames.append(firecrawl_ats.fetch(month, STORE))
    else:
        print("[demand] Skipping Firecrawl — FIRECRAWL_API_KEY not set")

    if not frames:
        print("ERROR: no demand sources available")
        sys.exit(1)

    merged = pd.concat(frames, ignore_index=True)
    print(f"[demand] Merged rows: {len(merged):,}")

    print("[demand] Cross-source dedup ...")
    merged = pipeline.cross_source_dedup(merged)
    print(f"[demand] After cross-source dedup: {len(merged):,}")

    print("[demand] Running pipeline ...")
    return pipeline.run(merged)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", default=date.today().strftime("%Y-%m"))
    parser.add_argument("--supply", action="store_true", help="Also fetch supply sources (Phase 4)")
    args = parser.parse_args()

    print(f"Running for month: {args.month}")
    clean_df = run_demand(args.month)

    supply_df = None
    if args.supply:
        supply_df = _run_supply(args.month)

    print("[index] Building index ...")
    idx = index_build.build_index(clean_df, supply_df=supply_df)
    index_build.write_index(idx, OUT_PATH)
    print("Done.")


def _run_supply(month: str) -> pd.DataFrame | None:
    """Phase 4 — added in Task 12. Stub for now."""
    print("[supply] Phase 4 supply sources not yet wired (run after Task 12)")
    return None


if __name__ == "__main__":
    main()
