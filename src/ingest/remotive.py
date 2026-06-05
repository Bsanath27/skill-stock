"""Remotive demand ingest — free public API, tech-focused listings."""
from __future__ import annotations
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
import pandas as pd

from ingest.raw_store import RawStore
from pipeline import normalise_text

REMOTIVE_URL = "https://remotive.com/api/remote-jobs"
CATEGORIES = ["software-dev", "data", "devops-sysadmin", "product"]


def fetch(month: str, store: RawStore) -> pd.DataFrame:
    """Fetch Remotive listings. month is used as cache key; API has no date filter."""
    cached = store.load("demand/remotive", month)
    if cached is not None:
        print(f"  [remotive] cache hit for {month} ({len(cached)} records)")
        return _to_df(cached, month)

    all_jobs: list[dict] = []
    seen_ids: set[str] = set()

    for cat in CATEGORIES:
        try:
            resp = requests.get(REMOTIVE_URL, params={"category": cat}, timeout=15)
            resp.raise_for_status()
            jobs = resp.json().get("jobs", [])
        except Exception as e:
            print(f"  [remotive] warn: {cat}: {e}")
            continue

        for j in jobs:
            jid = str(j.get("id", ""))
            if jid not in seen_ids:
                seen_ids.add(jid)
                all_jobs.append(j)

    store.save("demand/remotive", month, all_jobs)
    print(f"  [remotive] fetched {len(all_jobs)} unique records for {month}")
    return _to_df(all_jobs, month)


def _to_df(records: list[dict], month: str) -> pd.DataFrame:
    rows = []
    for r in records:
        rows.append({
            "company_norm":  normalise_text(r.get("company_name", "")),
            "title_norm":    normalise_text(r.get("title", "")),
            "location_norm": normalise_text(r.get("candidate_required_location", "remote")),
            "month":         month,
            "text":          f"{r.get('title','')} {r.get('description','')}",
            "source":        "remotive",
        })
    if not rows:
        return pd.DataFrame(columns=["company_norm","title_norm","location_norm","month","text","source"])
    return pd.DataFrame(rows)
