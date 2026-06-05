"""Udemy supply ingest — course count per skill via Firecrawl scrape."""
from __future__ import annotations
import os
import re
import sys
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
from firecrawl import FirecrawlApp

from ingest.raw_store import RawStore
from skills import SKILLS

SLEEP = 0.5


def fetch(month: str, store: RawStore, api_key: str | None = None) -> pd.DataFrame:
    """Return DataFrame with columns [skill, month, udemy_courses]."""
    api_key = api_key or os.environ.get("FIRECRAWL_API_KEY")
    if not api_key:
        print("  [udemy] FIRECRAWL_API_KEY not set — skipping")
        return _empty_df()

    cached = store.load("supply/udemy", month)
    if cached is not None:
        print(f"  [udemy] cache hit for {month}")
        return pd.DataFrame(cached)

    app = FirecrawlApp(api_key=api_key)
    rows = []

    for skill in SKILLS:
        query = skill.replace("&", "").replace("/", " ").strip()
        url = f"https://www.udemy.com/courses/search/?q={query.replace(' ', '+')}&sort=relevance&lang=en"
        try:
            result = app.scrape_url(url, formats=["markdown"])
            md = result.markdown if hasattr(result, "markdown") else (result.get("markdown") or "")
            count = _extract_count(md)
            rows.append({"skill": skill, "month": month, "udemy_courses": count})
            print(f"  [udemy] {skill}: {count} courses")
        except Exception as e:
            print(f"  [udemy] warn: {skill}: {e}")
            rows.append({"skill": skill, "month": month, "udemy_courses": None})
        time.sleep(SLEEP)

    store.save("supply/udemy", month, rows)
    return pd.DataFrame(rows)


def _extract_count(markdown: str) -> int | None:
    """Parse course result count from Udemy search page markdown."""
    # Udemy typically renders: "1,234 results for" or "1234 courses"
    patterns = [
        r"([\d,]+)\s+results?\s+for",
        r"([\d,]+)\s+courses?",
        r"Showing\s+([\d,]+)",
    ]
    for pat in patterns:
        m = re.search(pat, markdown, re.IGNORECASE)
        if m:
            return int(m.group(1).replace(",", ""))
    return None


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["skill", "month", "udemy_courses"])
