"""Adzuna demand ingest — wider queries, US + GB, 5 pages per skill."""
from __future__ import annotations
import os
import time
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
import pandas as pd

from ingest.raw_store import RawStore
from pipeline import normalise_text
from skills import SKILLS

BASE_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
RESULTS_PER_PAGE = 50
MAX_PAGES = 5
SLEEP = 0.3
COUNTRIES = ["us", "gb"]


def fetch(month: str, store: RawStore,
          app_id: str | None = None,
          app_key: str | None = None) -> pd.DataFrame:
    """Fetch Adzuna job postings for all skills. Returns normalised demand DataFrame."""
    app_id  = app_id  or os.environ["ADZUNA_APP_ID"]
    app_key = app_key or os.environ["ADZUNA_APP_KEY"]

    cache_key = month
    cached = store.load("demand/adzuna", cache_key)
    if cached is not None:
        print(f"  [adzuna] cache hit for {month} ({len(cached)} records)")
        return _to_df(cached, month)

    all_results: list[dict] = []
    seen_ids: set[str] = set()

    for country in COUNTRIES:
        for skill in SKILLS:
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
                    results = resp.json().get("results", [])
                except Exception as e:
                    print(f"    [adzuna] warn: {country}/{skill} p{page}: {e}")
                    break

                for r in results:
                    jid = f"{country}:{r.get('id', '')}"
                    if jid not in seen_ids:
                        seen_ids.add(jid)
                        r["_country"] = country
                        all_results.append(r)

                if len(results) < RESULTS_PER_PAGE:
                    break
                time.sleep(SLEEP)

    store.save("demand/adzuna", cache_key, all_results)
    print(f"  [adzuna] fetched {len(all_results)} unique records for {month}")
    return _to_df(all_results, month)


def _to_df(records: list[dict], month: str) -> pd.DataFrame:
    rows = []
    for r in records:
        rows.append({
            "company_norm": normalise_text(r.get("company", {}).get("display_name", "")),
            "title_norm":   normalise_text(r.get("title", "")),
            "location_norm": normalise_text(r.get("location", {}).get("display_name", "")),
            "month":        month,
            "text":         f"{r.get('title','')} {r.get('description','')}",
            "source":       "adzuna",
        })
    if not rows:
        return pd.DataFrame(columns=["company_norm","title_norm","location_norm","month","text","source"])
    return pd.DataFrame(rows)
