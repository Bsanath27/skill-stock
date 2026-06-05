"""src/ingest/hn_hiring.py — HN Who's Hiring demand ingest via Algolia API."""
from __future__ import annotations
import html
import re
import sys
import os
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
import pandas as pd

from ingest.raw_store import RawStore
from pipeline import normalise_text

ALGOLIA_BASE = "https://hn.algolia.com/api/v1"
THREAD_RE = re.compile(r"Who is hiring\? \(\w+ \d{4}\)", re.I)
SLEEP = 1.0

_MONTH_MAP = {
    "January": "01", "February": "02", "March": "03", "April": "04",
    "May": "05", "June": "06", "July": "07", "August": "08",
    "September": "09", "October": "10", "November": "11", "December": "12",
}


def _clean_html(text: str) -> str:
    """Decode HTML entities and strip tags."""
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _thread_month(title: str, created_at: str) -> str:
    """Return YYYY-MM from thread title like 'Ask HN: Who is hiring? (June 2024)'."""
    m = re.search(r"\((\w+) (\d{4})\)", title)
    if m:
        mm = _MONTH_MAP.get(m.group(1).capitalize())
        if mm:
            return f"{m.group(2)}-{mm}"
    return created_at[:7]


def _fetch_threads() -> list[dict]:
    """Return [{objectID, title, month}] for all monthly Who's Hiring threads."""
    resp = requests.get(
        f"{ALGOLIA_BASE}/search",
        params={"query": "Ask HN Who is hiring", "tags": "story", "hitsPerPage": 1000},
        timeout=15,
    )
    resp.raise_for_status()
    threads = []
    for h in resp.json().get("hits", []):
        title = h.get("title", "")
        if THREAD_RE.search(title):
            threads.append({
                "objectID": h["objectID"],
                "title": title,
                "month": _thread_month(title, h.get("created_at", "")[:7]),
            })
    return threads


def _fetch_comments(thread_id: str) -> list[str]:
    """Return cleaned text of all top-level job-post comments in a thread."""
    texts = []
    page = 0
    while True:
        resp = requests.get(
            f"{ALGOLIA_BASE}/search",
            params={"tags": f"comment,story_{thread_id}", "hitsPerPage": 1000, "page": page},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        hits = data.get("hits", [])
        if not hits:
            break
        for h in hits:
            if str(h.get("parent_id", "")) == thread_id:
                raw = h.get("comment_text", "")
                if raw:
                    texts.append(_clean_html(raw))
        if len(hits) < 1000:
            break
        page += 1
    return texts


def _to_df(records: list[dict]) -> pd.DataFrame:
    """Convert cached records [{text, month}] to pipeline-compatible DataFrame."""
    if not records:
        return pd.DataFrame(columns=["company_norm", "title_norm", "location_norm", "month", "text"])
    rows = []
    for r in records:
        text = r.get("text", "")
        first_line = text.split("\n")[0][:120] if text else ""
        rows.append({
            "company_norm": "hn",
            "title_norm": normalise_text(first_line),
            "location_norm": "",
            "month": r["month"],
            "text": text[:8000],
        })
    return pd.DataFrame(rows)


def fetch(month: str, store: RawStore) -> pd.DataFrame:
    """Fetch HN Who's Hiring comments for one month. Cache-first."""
    cached = store.load("demand/hn", month)
    if cached is not None:
        print(f"  [hn] cache hit {month} ({len(cached)} comments)")
        return _to_df(cached)

    print("  [hn] fetching thread list ...")
    threads = _fetch_threads()
    thread = next((t for t in threads if t["month"] == month), None)
    if thread is None:
        print(f"  [hn] no thread for {month}")
        store.save("demand/hn", month, [])
        return _to_df([])

    print(f"  [hn] fetching {thread['title']} ...")
    texts = _fetch_comments(thread["objectID"])
    records = [{"text": t, "month": month} for t in texts]
    store.save("demand/hn", month, records)
    print(f"  [hn] {month}: {len(records)} comments")
    time.sleep(SLEEP)
    return _to_df(records)


def fetch_range(start_month: str, end_month: str, store: RawStore) -> pd.DataFrame:
    """Fetch all HN months in [start_month, end_month] inclusive. Cache-first."""
    print("[hn] Fetching thread list ...")
    threads = _fetch_threads()
    thread_map = {t["month"]: t for t in threads}

    months = (
        pd.period_range(start=start_month, end=end_month, freq="M")
        .strftime("%Y-%m")
        .tolist()
    )

    frames: list[pd.DataFrame] = []
    for month in months:
        cached = store.load("demand/hn", month)
        if cached is not None:
            print(f"  [hn] cache hit {month} ({len(cached)} comments)")
            frames.append(_to_df(cached))
            continue

        thread = thread_map.get(month)
        if thread is None:
            print(f"  [hn] no thread for {month}, skipping")
            store.save("demand/hn", month, [])
            continue

        print(f"  [hn] fetching {month}: {thread['title']} ...")
        try:
            texts = _fetch_comments(thread["objectID"])
            records = [{"text": t, "month": month} for t in texts]
            store.save("demand/hn", month, records)
            print(f"  [hn] {month}: {len(records)} comments")
            frames.append(_to_df(records))
        except Exception as e:
            print(f"  [hn] warn: {month}: {e}")
        time.sleep(SLEEP)

    if not frames:
        return pd.DataFrame(columns=["company_norm", "title_norm", "location_norm", "month", "text"])
    return pd.concat(frames, ignore_index=True)
