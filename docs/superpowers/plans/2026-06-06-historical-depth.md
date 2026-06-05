# Historical Depth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 70+ months of HN Who's Hiring demand history, 6-year Stack Overflow supply signal, and per-skill salary data from Kaggle — turning one-point sparklines into real time series and enriching every skill modal with salary and adoption data.

**Architecture:** Three new cache-first ingest modules (hn_hiring, stackoverflow_survey, kaggle_salary) feed a one-time backfill orchestrator (run_history.py). index_build.py is refactored to accept historical + live series and merge them with a source-boundary momentum null. The frontend adds a 4th stat box (salary) and a dashed SO adoption overlay on the modal chart.

**Tech Stack:** Python, requests, pandas, csv, zipfile, Chart.js dual-axis (already loaded), vanilla JS, Algolia HN API (free/no auth), Stack Overflow public CSV downloads.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/ingest/hn_hiring.py` | Create | Algolia API → comment rows per HN Who's Hiring month |
| `src/ingest/stackoverflow_survey.py` | Create | Download + parse SO survey ZIPs → annual `{skill: pct}` |
| `src/ingest/kaggle_salary.py` | Create | Join Kaggle postings + salaries → `{skill: {p25,median,p75,n}}` |
| `src/run_history.py` | Create | One-time orchestrator: HN range + SO all years + Kaggle salary |
| `src/index_build.py` | Modify | Extract `_build_skill_series`, extend `build_index` with hist/SO/salary params |
| `src/run_all.py` | Modify | Add `--history` flag that calls `run_history.main()` |
| `public/index.html` | Modify | 4th salary stat box; SO adoption dashed overlay on modal chart |
| `tests/test_hn_hiring.py` | Create | Unit tests for HN ingest |
| `tests/test_stackoverflow_survey.py` | Create | Unit tests for SO survey parser |
| `tests/test_kaggle_salary.py` | Create | Unit tests for salary extractor |
| `tests/test_index_build_historical.py` | Create | Unit tests for series merge logic |

---

## Task 1: HN Who's Hiring ingest

**Files:**
- Create: `src/ingest/hn_hiring.py`
- Create: `tests/test_hn_hiring.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_hn_hiring.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from ingest.hn_hiring import _clean_html, _thread_month, _to_df, fetch
from ingest.raw_store import RawStore


def test_clean_html_decodes_entities():
    assert _clean_html("I&#x27;m hiring") == "I'm hiring"


def test_clean_html_strips_tags():
    result = _clean_html("<p>Hello <b>World</b></p>")
    assert "Hello" in result and "World" in result
    assert "<" not in result


def test_thread_month_parses_title():
    assert _thread_month("Ask HN: Who is hiring? (June 2024)", "") == "2024-06"


def test_thread_month_falls_back_to_created_at():
    assert _thread_month("Not a hiring thread", "2024-05-01") == "2024-05"


def test_to_df_returns_empty_with_correct_columns():
    df = _to_df([])
    assert df.empty
    assert set(["company_norm", "title_norm", "location_norm", "month", "text"]).issubset(df.columns)


def test_to_df_populates_rows():
    records = [{"text": "Stripe | Remote | Python Engineer\nWe need Python.", "month": "2024-06"}]
    df = _to_df(records)
    assert len(df) == 1
    assert df.iloc[0]["month"] == "2024-06"
    assert "stripe" in df.iloc[0]["title_norm"]


def test_fetch_uses_cache(tmp_path):
    store = RawStore(str(tmp_path))
    records = [{"text": "Acme | NYC | Engineer\nPython required.", "month": "2024-06"}]
    store.save("demand/hn", "2024-06", records)
    df = fetch("2024-06", store)
    assert len(df) == 1
    assert df.iloc[0]["month"] == "2024-06"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/sanathbs/03_Dev_Lab/projects/Personal/stockskill
python -m pytest tests/test_hn_hiring.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'ingest.hn_hiring'`

- [ ] **Step 3: Create `src/ingest/hn_hiring.py`**

```python
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

    print(f"  [hn] fetching thread list ...")
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_hn_hiring.py -v
```

Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add src/ingest/hn_hiring.py tests/test_hn_hiring.py
git commit -m "feat: HN Who's Hiring ingest via Algolia API"
```

---

## Task 2: Stack Overflow survey ingest

**Files:**
- Create: `src/ingest/stackoverflow_survey.py`
- Create: `tests/test_stackoverflow_survey.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_stackoverflow_survey.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import csv
import io
import json
import zipfile
import pytest
from unittest.mock import patch, MagicMock

from ingest.stackoverflow_survey import fetch, fetch_all, _is_professional, SO_SKILL_NAMES


def test_is_professional_2021_plus():
    assert _is_professional({"MainBranch": "I am a developer by profession"}, "2021") is True
    assert _is_professional({"MainBranch": "I am learning to code"}, "2021") is False


def test_is_professional_pre_2021():
    assert _is_professional({"Employment": "Employed, full-time"}, "2020") is True
    assert _is_professional({"Employment": ""}, "2020") is False


def test_so_skill_names_has_no_duplicates():
    # Every skill in SKILLS should have an entry in SO_SKILL_NAMES
    from skills import SKILLS
    for skill in SKILLS:
        assert skill in SO_SKILL_NAMES, f"{skill} missing from SO_SKILL_NAMES"


def _make_survey_zip(rows: list[dict], columns: list[str]) -> bytes:
    """Helper: build a fake survey ZIP with survey_results_public.csv."""
    buf = io.BytesIO()
    csv_buf = io.StringIO()
    writer = csv.DictWriter(csv_buf, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("survey_results_public.csv", csv_buf.getvalue())
    return buf.getvalue()


def test_fetch_counts_python_correctly(tmp_path):
    columns = ["MainBranch", "LanguageHaveWorkedWith", "DatabaseHaveWorkedWith",
               "PlatformHaveWorkedWith", "WebframeHaveWorkedWith",
               "MiscTechHaveWorkedWith", "ToolsTechHaveWorkedWith"]
    rows = [
        {"MainBranch": "I am a developer by profession",
         "LanguageHaveWorkedWith": "Python;JavaScript", "DatabaseHaveWorkedWith": "",
         "PlatformHaveWorkedWith": "", "WebframeHaveWorkedWith": "",
         "MiscTechHaveWorkedWith": "", "ToolsTechHaveWorkedWith": ""},
        {"MainBranch": "I am a developer by profession",
         "LanguageHaveWorkedWith": "JavaScript", "DatabaseHaveWorkedWith": "",
         "PlatformHaveWorkedWith": "", "WebframeHaveWorkedWith": "",
         "MiscTechHaveWorkedWith": "", "ToolsTechHaveWorkedWith": ""},
        {"MainBranch": "I am not a developer",
         "LanguageHaveWorkedWith": "Python", "DatabaseHaveWorkedWith": "",
         "PlatformHaveWorkedWith": "", "WebframeHaveWorkedWith": "",
         "MiscTechHaveWorkedWith": "", "ToolsTechHaveWorkedWith": ""},
    ]
    zip_bytes = _make_survey_zip(rows, columns)

    with patch("ingest.stackoverflow_survey.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.content = zip_bytes
        mock_resp.raise_for_status = lambda: None
        mock_get.return_value = mock_resp

        result = fetch("2021", cache_dir=str(tmp_path))

    # 2 professional devs, 1 uses Python → 50.0%
    assert result["Python"] == pytest.approx(50.0, rel=0.01)
    # JAX not in SO survey → None
    assert result["JAX"] is None


def test_fetch_uses_cache(tmp_path):
    cache = {"Python": 60.0, "JAX": None}
    cache_file = tmp_path / "2022.json"
    cache_file.write_text(json.dumps(cache))
    result = fetch("2022", cache_dir=str(tmp_path))
    assert result["Python"] == 60.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_stackoverflow_survey.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'ingest.stackoverflow_survey'`

- [ ] **Step 3: Create `src/ingest/stackoverflow_survey.py`**

```python
"""src/ingest/stackoverflow_survey.py — Stack Overflow Developer Survey supply signal."""
from __future__ import annotations
import csv
import io
import json
import os
import sys
import time
import zipfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests

from skills import SKILLS

SO_SURVEY_URLS: dict[str, str] = {
    "2019": "https://survey.stackoverflow.co/datasets/stack-overflow-developer-survey-2019.zip",
    "2020": "https://survey.stackoverflow.co/datasets/stack-overflow-developer-survey-2020.zip",
    "2021": "https://survey.stackoverflow.co/datasets/stack-overflow-developer-survey-2021.zip",
    "2022": "https://survey.stackoverflow.co/datasets/stack-overflow-developer-survey-2022.zip",
    "2023": "https://survey.stackoverflow.co/datasets/stack-overflow-developer-survey-2023.zip",
    "2024": "https://survey.stackoverflow.co/datasets/stack-overflow-developer-survey-2024.zip",
}

YEAR_TECH_COLS: dict[str, list[str]] = {
    "2019": ["LanguageWorkedWith", "DatabaseWorkedWith", "PlatformWorkedWith", "FrameworkWorkedWith"],
    "2020": ["LanguageWorkedWith", "DatabaseWorkedWith", "PlatformWorkedWith", "WebframeWorkedWith", "MiscTechWorkedWith"],
    "2021": ["LanguageHaveWorkedWith", "DatabaseHaveWorkedWith", "PlatformHaveWorkedWith", "WebframeHaveWorkedWith", "MiscTechHaveWorkedWith", "ToolsTechHaveWorkedWith"],
    "2022": ["LanguageHaveWorkedWith", "DatabaseHaveWorkedWith", "PlatformHaveWorkedWith", "WebframeHaveWorkedWith", "MiscTechHaveWorkedWith", "ToolsTechHaveWorkedWith"],
    "2023": ["LanguageHaveWorkedWith", "DatabaseHaveWorkedWith", "PlatformHaveWorkedWith", "WebframeHaveWorkedWith", "MiscTechHaveWorkedWith", "ToolsTechHaveWorkedWith"],
    "2024": ["LanguageHaveWorkedWith", "DatabaseHaveWorkedWith", "PlatformHaveWorkedWith", "WebframeHaveWorkedWith", "MiscTechHaveWorkedWith", "ToolsTechHaveWorkedWith"],
}

SO_SKILL_NAMES: dict[str, list[str]] = {
    "Python": ["Python"],
    "SQL": ["SQL"],
    "R": ["R"],
    "Rust": ["Rust"],
    "Scala": ["Scala"],
    "PyTorch": ["PyTorch"],
    "TensorFlow": ["TensorFlow"],
    "scikit-learn": ["Scikit-learn", "scikit-learn"],
    "Keras": ["Keras"],
    "JAX": [],
    "Pandas": [],
    "NumPy": [],
    "Spark": ["Apache Spark", "Spark"],
    "Kafka": ["Apache Kafka", "Kafka"],
    "Airflow": ["Apache Airflow", "Airflow"],
    "dbt": ["dbt"],
    "Snowflake": ["Snowflake"],
    "Databricks": ["Databricks"],
    "MLflow": [],
    "Weights & Biases": [],
    "LangChain": [],
    "Hugging Face": ["Hugging Face"],
    "Transformers": [],
    "AWS": ["AWS", "Amazon Web Services"],
    "GCP": ["Google Cloud Platform", "GCP"],
    "Azure": ["Microsoft Azure"],
    "Docker": ["Docker"],
    "Kubernetes": ["Kubernetes"],
    "Terraform": ["Terraform"],
    "FastAPI": [],
    "React": ["React", "React.js"],
    "TypeScript": ["TypeScript"],
    "Git": ["Git"],
    "CI/CD": [],
}


def _is_professional(row: dict, year: str) -> bool:
    if int(year) >= 2021:
        return "professional" in row.get("MainBranch", "").lower()
    return bool(row.get("Employment", "").strip())


def fetch(year: str, cache_dir: str = "data/raw/supply/stackoverflow") -> dict[str, float | None]:
    """Download + parse SO survey for one year. Returns {skill: pct_using | None}."""
    cache_path = os.path.join(cache_dir, f"{year}.json")
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            print(f"  [so] cache hit {year}")
            return json.load(f)

    url = SO_SURVEY_URLS.get(year)
    if not url:
        raise ValueError(f"No survey URL for {year}")

    print(f"  [so] downloading {year} survey ...")
    try:
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [so] warn: could not download {year}: {e}")
        return {skill: None for skill in SKILLS}

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        csv_name = next(
            (n for n in zf.namelist() if n.endswith("survey_results_public.csv")), None
        )
        if csv_name is None:
            print(f"  [so] warn: no survey_results_public.csv in {year} ZIP")
            return {skill: None for skill in SKILLS}

        with zf.open(csv_name) as raw:
            reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", errors="replace"))
            tech_cols = YEAR_TECH_COLS.get(year, [])
            total = 0
            skill_counts: dict[str, int] = {s: 0 for s in SKILLS}

            for row in reader:
                if not _is_professional(row, year):
                    continue
                total += 1
                all_values: set[str] = set()
                for col in tech_cols:
                    for item in (row.get(col) or "").split(";"):
                        item = item.strip()
                        if item:
                            all_values.add(item)
                for skill in SKILLS:
                    if SO_SKILL_NAMES.get(skill) and any(n in all_values for n in SO_SKILL_NAMES[skill]):
                        skill_counts[skill] += 1

    result: dict[str, float | None] = {
        skill: (round(skill_counts[skill] / total * 100, 2) if total > 0 and SO_SKILL_NAMES.get(skill) else None)
        for skill in SKILLS
    }

    os.makedirs(cache_dir, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(result, f, separators=(",", ":"))

    print(f"  [so] {year}: {total} professional devs, Python={result.get('Python')}%")
    return result


def fetch_all(
    years: list[str] | None = None,
    cache_dir: str = "data/raw/supply/stackoverflow",
) -> dict[str, list[dict]]:
    """
    Fetch all survey years. Returns {skill: [{year, pct}, ...]} sorted by year.
    pct is None for skills not tracked in SO survey.
    """
    if years is None:
        years = sorted(SO_SURVEY_URLS.keys())

    per_year: list[tuple[str, dict]] = []
    for year in years:
        data = fetch(year, cache_dir)
        per_year.append((year, data))
        time.sleep(0.3)

    result: dict[str, list[dict]] = {skill: [] for skill in SKILLS}
    for year, data in per_year:
        for skill in SKILLS:
            result[skill].append({"year": year, "pct": data.get(skill)})
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_stackoverflow_survey.py -v
```

Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add src/ingest/stackoverflow_survey.py tests/test_stackoverflow_survey.py
git commit -m "feat: Stack Overflow annual survey supply ingest"
```

---

## Task 3: Kaggle salary ingest

**Files:**
- Create: `src/ingest/kaggle_salary.py`
- Create: `tests/test_kaggle_salary.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_kaggle_salary.py
import sys, os, csv, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from ingest.kaggle_salary import fetch, SALARY_MIN, SALARY_MAX, MIN_SAMPLE


def _write_csv(path, rows, fieldnames):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def test_fetch_returns_empty_when_files_missing(tmp_path):
    result = fetch(
        postings_path=str(tmp_path / "nope.csv"),
        salaries_path=str(tmp_path / "nope2.csv"),
        cache_path=str(tmp_path / "cache.json"),
    )
    assert result == {}


def test_fetch_computes_percentiles(tmp_path):
    # Create 15 postings all mentioning Python with salary $100k
    postings_path = str(tmp_path / "postings.csv")
    salaries_path = str(tmp_path / "salaries.csv")
    cache_path    = str(tmp_path / "cache.json")

    postings = [
        {"job_id": str(i), "description": "Python developer needed"}
        for i in range(15)
    ]
    salaries = [
        {"salary_id": str(i), "job_id": str(i),
         "med_salary": "100000", "min_salary": "", "max_salary": "",
         "pay_period": "YEARLY", "currency": "USD", "compensation_type": "BASE_SALARY"}
        for i in range(15)
    ]

    _write_csv(postings_path, postings, ["job_id", "description"])
    _write_csv(salaries_path, salaries,
               ["salary_id", "job_id", "med_salary", "min_salary", "max_salary",
                "pay_period", "currency", "compensation_type"])

    result = fetch(postings_path, salaries_path, cache_path)

    assert "Python" in result
    assert result["Python"]["median"] == 100000
    assert result["Python"]["n"] == 15


def test_fetch_filters_outlier_salaries(tmp_path):
    postings_path = str(tmp_path / "postings.csv")
    salaries_path = str(tmp_path / "salaries.csv")
    cache_path    = str(tmp_path / "cache.json")

    postings = [{"job_id": str(i), "description": "Python engineer"} for i in range(20)]
    salaries = [
        {"salary_id": str(i), "job_id": str(i),
         "med_salary": str(1000 if i < 5 else 600000 if i < 10 else 120000),
         "min_salary": "", "max_salary": "",
         "pay_period": "YEARLY", "currency": "USD", "compensation_type": "BASE_SALARY"}
        for i in range(20)
    ]

    _write_csv(postings_path, postings, ["job_id", "description"])
    _write_csv(salaries_path, salaries,
               ["salary_id", "job_id", "med_salary", "min_salary", "max_salary",
                "pay_period", "currency", "compensation_type"])

    result = fetch(postings_path, salaries_path, cache_path)
    # Only 10 valid salaries (filtered $1k and $600k out), all $120k
    assert "Python" in result
    assert result["Python"]["median"] == 120000
    assert result["Python"]["n"] == 10


def test_fetch_skips_skill_below_min_sample(tmp_path):
    postings_path = str(tmp_path / "postings.csv")
    salaries_path = str(tmp_path / "salaries.csv")
    cache_path    = str(tmp_path / "cache.json")

    # Only 5 rows — below MIN_SAMPLE=10
    postings = [{"job_id": str(i), "description": "Python developer"} for i in range(5)]
    salaries = [
        {"salary_id": str(i), "job_id": str(i),
         "med_salary": "100000", "min_salary": "", "max_salary": "",
         "pay_period": "YEARLY", "currency": "USD", "compensation_type": "BASE_SALARY"}
        for i in range(5)
    ]

    _write_csv(postings_path, postings, ["job_id", "description"])
    _write_csv(salaries_path, salaries,
               ["salary_id", "job_id", "med_salary", "min_salary", "max_salary",
                "pay_period", "currency", "compensation_type"])

    result = fetch(postings_path, salaries_path, cache_path)
    assert "Python" not in result


def test_fetch_uses_cache(tmp_path):
    cache_path = str(tmp_path / "cache.json")
    cached = {"Python": {"p25": 90000, "median": 120000, "p75": 150000, "n": 50}}
    with open(cache_path, "w") as f:
        json.dump(cached, f)
    result = fetch(
        postings_path=str(tmp_path / "nope.csv"),
        salaries_path=str(tmp_path / "nope2.csv"),
        cache_path=cache_path,
    )
    assert result == cached
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_kaggle_salary.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'ingest.kaggle_salary'`

- [ ] **Step 3: Create `src/ingest/kaggle_salary.py`**

```python
"""src/ingest/kaggle_salary.py — per-skill annual salary stats from Kaggle LinkedIn dataset."""
from __future__ import annotations
import csv
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline import extract_skills

POSTINGS_PATH = "data/raw/archive (1)/postings.csv"
SALARIES_PATH = "data/raw/archive (1)/jobs/salaries.csv"
CACHE_PATH    = "data/raw/supply/kaggle_salary.json"

SALARY_MIN = 30_000
SALARY_MAX = 500_000
MIN_SAMPLE = 10


def _percentile(vals: list[float], p: float) -> int:
    s = sorted(vals)
    k = (len(s) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return int(round(s[lo] + (s[hi] - s[lo]) * (k - lo)))


def fetch(
    postings_path: str = POSTINGS_PATH,
    salaries_path: str = SALARIES_PATH,
    cache_path: str = CACHE_PATH,
) -> dict[str, dict]:
    """
    Extract per-skill annual salary percentiles from Kaggle LinkedIn data.
    Returns {skill: {p25, median, p75, n}} for skills with n >= MIN_SAMPLE.
    Returns {} if Kaggle files are not present.
    """
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            print("  [salary] cache hit")
            return json.load(f)

    if not os.path.exists(postings_path) or not os.path.exists(salaries_path):
        print("  [salary] warn: Kaggle files not found, skipping")
        return {}

    # Load valid USD yearly salaries
    salary_map: dict[str, float] = {}
    with open(salaries_path, newline="") as f:
        for row in csv.DictReader(f):
            if row.get("currency") != "USD":
                continue
            if row.get("pay_period") != "YEARLY":
                continue
            if row.get("compensation_type") != "BASE_SALARY":
                continue
            sal: float | None = None
            if row.get("med_salary"):
                try:
                    sal = float(row["med_salary"])
                except ValueError:
                    pass
            if sal is None and row.get("min_salary") and row.get("max_salary"):
                try:
                    sal = (float(row["min_salary"]) + float(row["max_salary"])) / 2
                except ValueError:
                    pass
            if sal is None or not (SALARY_MIN <= sal <= SALARY_MAX):
                continue
            salary_map[row["job_id"]] = sal

    print(f"  [salary] {len(salary_map):,} valid salary rows")

    skill_salaries: dict[str, list[float]] = {}
    matched = 0
    with open(postings_path, newline="") as f:
        for row in csv.DictReader(f):
            job_id = row.get("job_id", "")
            if job_id not in salary_map:
                continue
            for skill in extract_skills(row.get("description", "") or ""):
                skill_salaries.setdefault(skill, []).append(salary_map[job_id])
            matched += 1

    print(f"  [salary] {matched:,} postings matched to salary")

    result: dict[str, dict] = {}
    for skill, salaries in skill_salaries.items():
        if len(salaries) < MIN_SAMPLE:
            continue
        result[skill] = {
            "p25":    _percentile(salaries, 25),
            "median": _percentile(salaries, 50),
            "p75":    _percentile(salaries, 75),
            "n":      len(salaries),
        }

    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(result, f, separators=(",", ":"))

    print(f"  [salary] {len(result)} skills with salary data (n≥{MIN_SAMPLE})")
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_kaggle_salary.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add src/ingest/kaggle_salary.py tests/test_kaggle_salary.py
git commit -m "feat: Kaggle salary percentile extraction per skill"
```

---

## Task 4: Refactor index_build.py — historical merge + SO/salary fields

**Files:**
- Modify: `src/index_build.py`
- Create: `tests/test_index_build_historical.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_index_build_historical.py
import sys
sys.path.insert(0, "src")

import pandas as pd
import pytest
from index_build import build_index


def _make_df(month: str, n: int = 60, skill: str = "Python") -> pd.DataFrame:
    """Make a minimal demand DataFrame with n rows for one month and one skill."""
    rows = [
        {"company_norm": f"co{i}", "title_norm": f"job{i}", "location_norm": "remote",
         "month": month, "skills": [skill]}
        for i in range(n)
    ]
    return pd.DataFrame(rows)


def test_build_index_without_hist_backward_compatible():
    """Existing call signature still works."""
    df = _make_df("2026-06")
    idx = build_index(df)
    assert "Python" in idx["skills"]
    py = idx["skills"]["Python"]
    assert "series" in py
    assert "so_series" in py    # new field present even when so_data=None
    assert "salary" in py       # new field present even when salary_data=None
    assert py["so_series"] == []
    assert py["salary"] is None


def test_build_index_merges_hist_and_live_series():
    """Historical + live series are concatenated and sorted by month."""
    hist_df = _make_df("2020-06")
    live_df = _make_df("2026-06")
    idx = build_index(live_df, hist_df=hist_df)
    py = idx["skills"]["Python"]
    months = [p["month"] for p in py["series"]]
    assert "2020-06" in months
    assert "2026-06" in months
    assert months == sorted(months)


def test_source_boundary_nulls_mom_pct():
    """First live data point has mom_pct=None when hist is also present."""
    hist_df = _make_df("2020-06")
    live_df = _make_df("2026-06")
    idx = build_index(live_df, hist_df=hist_df)
    py = idx["skills"]["Python"]
    live_point = next(p for p in py["series"] if p["month"] == "2026-06")
    assert live_point["mom_pct"] is None


def test_so_data_attached_to_skill():
    """so_series from so_data is present in output skill data."""
    live_df = _make_df("2026-06")
    so_data = {"Python": [{"year": "2023", "pct": 49.3}, {"year": "2024", "pct": 51.0}]}
    idx = build_index(live_df, so_data=so_data)
    py = idx["skills"]["Python"]
    assert py["so_series"] == [{"year": "2023", "pct": 49.3}, {"year": "2024", "pct": 51.0}]


def test_salary_data_attached_to_skill():
    """salary from salary_data appears in output skill data."""
    live_df = _make_df("2026-06")
    salary_data = {"Python": {"p25": 110000, "median": 145000, "p75": 185000, "n": 342}}
    idx = build_index(live_df, salary_data=salary_data)
    py = idx["skills"]["Python"]
    assert py["salary"]["median"] == 145000


def test_total_postings_includes_hist():
    """total_postings counts both hist and live rows."""
    hist_df = _make_df("2020-06", n=60)
    live_df = _make_df("2026-06", n=60)
    idx = build_index(live_df, hist_df=hist_df)
    assert idx["total_postings"] == 120
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_index_build_historical.py -v 2>&1 | head -30
```

Expected: tests fail because `build_index` doesn't yet accept `hist_df`, `so_data`, `salary_data` and doesn't output `so_series`/`salary` fields.

- [ ] **Step 3: Refactor `src/index_build.py`**

Replace the full file with:

```python
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
    hist_df:      optional HN historical demand. If provided, price series are built
                  separately for each corpus then concatenated per skill. mom_pct is
                  nulled at the source boundary (first live data point).
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
```

- [ ] **Step 4: Run all tests to verify they pass**

```bash
python -m pytest tests/ -v
```

Expected: all existing tests + new tests pass. Specifically confirm:
- `tests/test_saturation.py` — all 4 still pass (backward compatibility)
- `tests/test_index_build_historical.py` — all 6 pass

- [ ] **Step 5: Commit**

```bash
git add src/index_build.py tests/test_index_build_historical.py
git commit -m "feat: extend index_build with historical series merge, SO supply, salary fields"
```

---

## Task 5: `run_history.py` orchestrator

**Files:**
- Create: `src/run_history.py`

- [ ] **Step 1: Create `src/run_history.py`**

```python
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
import os
import sys
from datetime import date
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd

from ingest.raw_store import RawStore
from ingest import hn_hiring, stackoverflow_survey, kaggle_salary
import pipeline
import index_build

STORE   = RawStore()
OUT_PATH = os.environ.get("OUT_PATH", "public/index.json")


def _load_live_demand(month: str) -> pd.DataFrame:
    """Load cached live demand for month from disk. Returns empty DF if nothing cached."""
    frames: list[pd.DataFrame] = []

    # Adzuna
    cached = STORE.load("demand/adzuna", month)
    if cached:
        from ingest.adzuna import _to_df as _adzuna_df
        frames.append(_adzuna_df(cached, month))

    # Remotive
    cached = STORE.load("demand/remotive", month)
    if cached:
        from ingest.remotive import _to_df as _remotive_df
        frames.append(_remotive_df(cached, month))

    # Firecrawl ATS
    from ingest import firecrawl_ats as _fc
    fc_records = []
    fc_dir = STORE._base / "demand" / "firecrawl" / month
    if fc_dir.exists():
        import json
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

    # If live demand is empty, use the latest HN month as the live series
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
```

- [ ] **Step 2: Verify the script runs (dry-run with cached data)**

```bash
cd /Users/sanathbs/03_Dev_Lab/projects/Personal/stockskill
python src/run_history.py --hn-only --no-salary --start 2025-11 --end 2025-11
```

Expected: script runs, fetches HN Nov 2025 thread (or cache hit), writes `public/index.json`.
If the HN thread exists but no Adzuna cache is present for 2026-06, it will use HN data as primary.

- [ ] **Step 3: Commit**

```bash
git add src/run_history.py
git commit -m "feat: run_history.py one-time historical backfill orchestrator"
```

---

## Task 6: Add `--history` flag to `run_all.py`

**Files:**
- Modify: `src/run_all.py`

- [ ] **Step 1: Add `--history` flag**

Find in `src/run_all.py`:
```python
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", default=date.today().strftime("%Y-%m"))
    parser.add_argument("--supply", action="store_true", help="Also fetch supply sources (Phase 4)")
    args = parser.parse_args()
```

Replace with:
```python
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", default=date.today().strftime("%Y-%m"))
    parser.add_argument("--supply", action="store_true", help="Also fetch supply sources (Phase 4)")
    parser.add_argument("--history", action="store_true",
                        help="Run historical backfill (HN 2020-2025 + SO survey + Kaggle salary) before building index")
    args = parser.parse_args()
```

- [ ] **Step 2: Add history branch in `main()`**

Find in `src/run_all.py`:
```python
    print(f"Running for month: {args.month}")
    clean_df = run_demand(args.month)
```

Replace with:
```python
    print(f"Running for month: {args.month}")

    if args.history:
        print("[run_all] --history flag set: running historical backfill first ...")
        import run_history
        run_history.main()
        return  # run_history writes its own index.json

    clean_df = run_demand(args.month)
```

- [ ] **Step 3: Verify the flag is wired**

```bash
python src/run_all.py --help
```

Expected output includes `--history` in the options list.

- [ ] **Step 4: Commit**

```bash
git add src/run_all.py
git commit -m "feat: add --history flag to run_all.py for one-command historical backfill"
```

---

## Task 7: Frontend — salary stat box + SO adoption chart overlay

**Files:**
- Modify: `public/index.html`

- [ ] **Step 1: Update `.modal-stats` CSS grid**

Find:
```css
  .modal-stats {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 10px;
    margin-bottom: 24px;
  }
```

Replace with:
```css
  .modal-stats {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 10px;
    margin-bottom: 24px;
  }
```

Also find in the `@media (max-width: 640px)` block:
```css
    .modal-stats { grid-template-columns: 1fr 1fr; }
```

This line already handles mobile — no change needed.

- [ ] **Step 2: Add salary stat box in modal HTML**

Find:
```html
      <div class="stat-box">
        <div class="stat-label">Latest Month Count</div>
        <div id="stat-count" class="stat-val"></div>
      </div>
    </div>
```

Replace with:
```html
      <div class="stat-box">
        <div class="stat-label">Latest Month Count</div>
        <div id="stat-count" class="stat-val"></div>
      </div>
      <div class="stat-box">
        <div class="stat-label">Median Salary</div>
        <div id="stat-salary" class="stat-val"></div>
      </div>
    </div>
```

- [ ] **Step 3: Add salary display in `openModal()`**

Find in `openModal()`:
```javascript
  document.getElementById("stat-count").textContent =
    pt?.count != null ? pt.count.toLocaleString() : "—";
```

Add immediately after it:
```javascript
  const salary = data.salary;
  document.getElementById("stat-salary").textContent =
    salary ? `$${Math.round(salary.median / 1000)}k` : "—";
```

- [ ] **Step 4: Add SO adoption overlay to modal chart**

Find in `openModal()` the Chart.js `datasets` array opening — it looks like:

```javascript
      datasets: [{
        label: skill,
        data: series.map(p => p.price),
```

Replace the entire `new Chart(ctx, { ... })` call with:

```javascript
  // Build SO adoption sparse overlay (one point per year at YYYY-06 label)
  const soSeries = data.so_series || [];
  const chartLabels = series.map(p => p.month);
  const soPoints = chartLabels.map(label => {
    const match = soSeries.find(p => label === p.year + "-06");
    return (match && match.pct !== null) ? match.pct : null;
  });
  const hasSoData = soPoints.some(v => v !== null);

  if (modalChart) modalChart.destroy();
  const ctx = document.getElementById("modal-chart").getContext("2d");
  const color = mom == null ? "#4a6741" : mom > 0 ? "#00e676" : "#ff5252";
  modalChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: chartLabels,
      datasets: [
        {
          label: skill,
          data: series.map(p => p.price),
          borderColor: color,
          backgroundColor: color + "18",
          borderWidth: 2,
          pointRadius: series.length < 30 ? 3 : 0,
          pointHoverRadius: 5,
          tension: 0.35,
          fill: true,
          yAxisID: "y",
        },
        ...(hasSoData ? [{
          label: "SO Adoption %",
          data: soPoints,
          borderColor: "#f9a825",
          backgroundColor: "transparent",
          borderWidth: 1.5,
          borderDash: [4, 4],
          pointRadius: 3,
          pointHoverRadius: 4,
          tension: 0.3,
          fill: false,
          yAxisID: "y2",
          spanGaps: false,
        }] : []),
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: hasSoData },
        tooltip: {
          mode: "index",
          intersect: false,
          backgroundColor: "#0a0e0a",
          borderColor: "#1e2e1e",
          borderWidth: 1,
          titleColor: "#c8e6c9",
          bodyColor: "#7cb87c",
          callbacks: {
            label: ctx => ctx.dataset.yAxisID === "y2"
              ? ` SO Adoption: ${ctx.parsed.y?.toFixed(1)}%`
              : ` Price: ${ctx.parsed.y.toFixed(2)}`,
          }
        }
      },
      scales: {
        x: {
          ticks: { color: "#4a6741", font: { family: "'JetBrains Mono', monospace", size: 10 }, maxTicksLimit: 12 },
          grid:  { color: "#1a2a1a" },
        },
        y: {
          ticks: { color: "#4a6741", font: { family: "'JetBrains Mono', monospace", size: 10 } },
          grid:  { color: "#1a2a1a" },
        },
        y2: {
          display: hasSoData,
          position: "right",
          min: 0,
          max: 100,
          ticks: {
            color: "#f9a82588",
            font: { family: "'JetBrains Mono', monospace", size: 9 },
            callback: v => `${v}%`,
          },
          grid: { display: false },
        },
      },
      interaction: { mode: "nearest", axis: "x", intersect: false }
    }
  });
```

Remove the old `if (modalChart) modalChart.destroy();` and `const ctx = ...` lines that were before the old `new Chart(...)` call — they are now included in the replacement block above.

- [ ] **Step 5: Verify locally**

```bash
# Ensure local server is running
lsof -ti:8787 | head -1 || (cd public && python3 -m http.server 8787 &)
```

Open http://localhost:8787 and click any skill modal. Verify:
- 4 stat boxes appear: Price, MoM, Count, Median Salary
- Salary shows "$—" (data not yet backfilled — that's fine for now)
- Chart renders without JS errors in console

- [ ] **Step 6: Commit**

```bash
git add public/index.html
git commit -m "feat: salary stat box and SO adoption overlay in skill modal"
```

---

## Task 8: Run the full historical backfill + push

**Files:**
- `public/index.json` (regenerated)

- [ ] **Step 1: Run full test suite to confirm everything passes**

```bash
python -m pytest tests/ -v
```

Expected: all tests pass (existing + new).

- [ ] **Step 2: Run the historical backfill**

```bash
cd /Users/sanathbs/03_Dev_Lab/projects/Personal/stockskill
python src/run_history.py 2>&1 | tee /tmp/history_run.log
```

This will:
1. Extract Kaggle salary (~2 min)
2. Download SO survey ZIPs for 2019–2024 (~5 min, ~200MB total, cached after)
3. Fetch ~70 HN Who's Hiring threads via Algolia (~5–10 min with 1s sleep)
4. Build and write `public/index.json`

Watch for any `[so] warn` or `[hn] warn` lines — these indicate failed months/years (non-fatal).

- [ ] **Step 3: Verify index.json quality**

```bash
python3 -c "
import json
with open('public/index.json') as f:
    idx = json.load(f)
print('Months:', idx['total_months'])
print('Postings:', idx['total_postings'])
print('Data through:', idx['data_through'])

py = idx['skills']['Python']
print('Python series points:', len(py['series']))
print('Python SO series:', py['so_series'][:2])
print('Python salary:', py['salary'])
print('Earliest month:', py['series'][0]['month'] if py['series'] else 'none')
"
```

Expected:
- `total_months` ≥ 30 (should have many HN months)
- `Python series points` ≥ 30
- `Python SO series` shows 6 entries with pct values
- `Python salary` shows median around $120k–$150k
- `Earliest month` is around 2020-01

- [ ] **Step 4: Push to GitHub**

```bash
git add public/index.json
git commit -m "data: historical backfill — HN 2020-2025 + SO survey 2019-2024 + Kaggle salary"
git push
```

Netlify deploys automatically. Open the live URL and verify:
- Sparklines in the table now show a real trend line (70+ points)
- Clicking any skill opens a modal with multi-year chart
- Salary stat box shows values for mainstream skills (Python, SQL, AWS, etc.)
- SO adoption dashed overlay appears as amber dots at annual intervals

---

## Self-Review

**Spec coverage:**
- ✅ HN demand ingest (Task 1) — Algolia API, comment parsing, cache-first, fetch_range
- ✅ SO survey supply (Task 2) — ZIP download, year→column mapping, professional filter, fetch_all
- ✅ Kaggle salary (Task 3) — USD/YEARLY filter, percentile computation, MIN_SAMPLE guard
- ✅ index_build refactor (Task 4) — _build_skill_series extracted, new params, series merge, boundary null
- ✅ run_history.py (Task 5) — full orchestrator, loads live cache, handles empty live/hist
- ✅ run_all.py --history (Task 6) — delegates to run_history.main()
- ✅ Frontend salary stat (Task 7) — 4th stat box, openModal wired
- ✅ Frontend SO overlay (Task 7) — sparse points at YYYY-06, dual y-axis, hasSoData guard
- ✅ Backfill execution (Task 8) — run + verify + push

**Placeholder scan:** None. All API URLs, column names, constants, and code blocks are fully specified.

**Type consistency:**
- `_build_skill_series` returns `(dict[str, Any], list[str])` — consumed correctly in `build_index`
- `so_data` shape: `{skill: [{year, pct}]}` — produced by `fetch_all`, consumed by `build_index` and frontend
- `salary_data` shape: `{skill: {p25, median, p75, n}}` — produced by `kaggle_salary.fetch`, consumed by `build_index` and frontend
- `hist_df` shape: standard pipeline DataFrame (company_norm, title_norm, location_norm, month, skills) — same as live `df`
