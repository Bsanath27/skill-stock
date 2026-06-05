"""Firecrawl ATS scraper — crawls career pages of known tech companies."""
from __future__ import annotations
import os
import re
import sys
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
from firecrawl import FirecrawlApp

from ingest.raw_store import RawStore
from ingest.companies import COMPANIES
from pipeline import normalise_text

SLEEP = 1.0  # seconds between Firecrawl requests


def fetch(month: str, store: RawStore, api_key: str | None = None) -> pd.DataFrame:
    """Scrape all company ATS pages. Returns normalised demand DataFrame."""
    api_key = api_key or os.environ["FIRECRAWL_API_KEY"]
    app = FirecrawlApp(api_key=api_key)
    all_rows: list[dict] = []

    for slug, url in COMPANIES:
        cache_key = f"{month}/{slug}"
        cached = store.load("demand/firecrawl", cache_key)

        if cached is not None:
            print(f"  [firecrawl] cache hit: {slug}")
            all_rows.extend(cached)
            continue

        try:
            result = app.scrape_url(url, formats=["markdown"])
            markdown = result.markdown if hasattr(result, "markdown") else (result.get("markdown") or "")
            jobs = _parse_jobs(markdown, slug)
            store.save("demand/firecrawl", cache_key, jobs)
            all_rows.extend(jobs)
            print(f"  [firecrawl] scraped {slug}: {len(jobs)} jobs")
        except Exception as e:
            print(f"  [firecrawl] warn: {slug}: {e}")
            store.save("demand/firecrawl", cache_key, [])  # cache empty so we don't retry

        time.sleep(SLEEP)

    return _to_df(all_rows, month)


def _parse_jobs(markdown: str, company_slug: str) -> list[dict]:
    """Extract job titles from scraped markdown. Heuristic: lines that look like job titles."""
    jobs = []
    for line in markdown.splitlines():
        line = line.strip().lstrip("#").strip()
        # Job title heuristics: 4-80 chars, not a URL, not mostly numbers
        if 4 < len(line) < 80 and not line.startswith("http") and not re.match(r"^\d", line):
            if any(kw in line.lower() for kw in [
                "engineer", "scientist", "developer", "analyst", "manager",
                "architect", "lead", "specialist", "researcher", "intern",
            ]):
                jobs.append({"company": company_slug, "title": line})
    return jobs


def _to_df(records: list[dict], month: str) -> pd.DataFrame:
    rows = []
    for r in records:
        rows.append({
            "company_norm":  normalise_text(r.get("company", "")),
            "title_norm":    normalise_text(r.get("title", "")),
            "location_norm": "unknown",
            "month":         month,
            "text":          r.get("title", ""),
            "source":        "firecrawl",
        })
    if not rows:
        return pd.DataFrame(columns=["company_norm","title_norm","location_norm","month","text","source"])
    return pd.DataFrame(rows)
