# Historical Depth Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add multi-year historical demand series (HN Who's Hiring, 2020–2025), annual supply series (Stack Overflow Developer Survey, 2019–2024), and per-skill salary data (Kaggle LinkedIn 2024-04) — giving every skill chart 70+ data points and every modal a salary stat box and SO adoption overlay.

**Architecture:** Three new ingest modules feed a one-time backfill orchestrator (`run_history.py`). `index_build.py` merges the historical HN series with the live Adzuna series and appends two new fields (`so_series`, `salary`) to each skill in `index.json`. The frontend adds a salary stat card and a dashed SO adoption overlay to the modal chart. No backend changes — still a static site.

**Tech Stack:** Python (requests, pandas, csv), Algolia HN Search API (free, no auth), Stack Overflow survey CSVs (public download), existing Kaggle LinkedIn CSVs on disk, Chart.js dual-axis (already loaded), vanilla JS.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/ingest/hn_hiring.py` | Create | Algolia API → skill-mention rows per HN Who's Hiring month |
| `src/ingest/stackoverflow_survey.py` | Create | SO survey CSVs → annual `{skill: pct}` supply signal |
| `src/ingest/kaggle_salary.py` | Create | Kaggle postings + salaries CSVs → `p25/median/p75` per skill |
| `src/run_history.py` | Create | One-time backfill: HN 2020-01→2025-12 + SO 2019–2024 + Kaggle salary |
| `src/index_build.py` | Modify | Accept historical df, merge HN+Adzuna series, add `so_series`+`salary` fields |
| `src/run_all.py` | Modify | Add `--history` flag to run historical backfill before index build |
| `public/index.html` | Modify | 4th salary stat box in modal; SO adoption dashed overlay on modal chart |

---

## Data Pipeline

### Demand — HN Who's Hiring (`src/ingest/hn_hiring.py`)

**Source:** Hacker News Algolia Search API — `https://hn.algolia.com/api/v1/`

**Method:**
1. Query for all "Ask HN: Who is hiring?" monthly threads (title pattern `"Who is hiring? ("`):
   ```
   GET /search?query=Ask+HN+Who+is+hiring&tags=story&hitsPerPage=100
   ```
2. Filter to threads matching regex `Who is hiring\? \(\w+ \d{4}\)` to exclude "Who is hiring right now?" variants.
3. For each thread, fetch all top-level comments (the actual job posts) paginated:
   ```
   GET /search?tags=comment,story_{objectID}&hitsPerPage=1000&page=N
   ```
4. For each comment, run `SKILL_PATTERNS` regex over `comment_text` (HTML-decoded). Count one mention per skill per comment (not per occurrence — avoids keyword stuffing).
5. Output row per comment per skill detected: `{skill, month, title_norm="", company_norm="hn"}`.

**Cache:** `data/raw/demand/hn/{month}.json` — list of `{skill, month}` dicts. Cache hit skips API entirely.

**Coverage:** ~2020-01 to 2025-12 (≈70 months). Earlier threads exist but comment counts drop significantly pre-2020.

**Rate limiting:** 1 second sleep between thread fetches. No auth required. Algolia public API has generous limits.

---

### Supply — Stack Overflow Survey (`src/ingest/stackoverflow_survey.py`)

**Source:** Stack Overflow Annual Developer Survey public CSVs.

Download URLs (direct links, no auth):
```python
SO_SURVEY_URLS = {
    "2019": "https://survey.stackoverflow.co/datasets/stack-overflow-developer-survey-2019.zip",
    "2020": "https://survey.stackoverflow.co/datasets/stack-overflow-developer-survey-2020.zip",
    "2021": "https://survey.stackoverflow.co/datasets/stack-overflow-developer-survey-2021.zip",
    "2022": "https://survey.stackoverflow.co/datasets/stack-overflow-developer-survey-2022.zip",
    "2023": "https://survey.stackoverflow.co/datasets/stack-overflow-developer-survey-2023.zip",
    "2024": "https://survey.stackoverflow.co/datasets/stack-overflow-developer-survey-2024.zip",
}
```

**Method:**
1. Download + unzip each year's CSV to `data/raw/supply/stackoverflow/{year}/survey_results_public.csv`.
2. Parse the technology-usage columns. Column names vary by year — use this mapping:
   ```python
   YEAR_TECH_COLS = {
       "2019": ["LanguageWorkedWith", "DatabaseWorkedWith", "PlatformWorkedWith", "FrameworkWorkedWith"],
       "2020": ["LanguageWorkedWith", "DatabaseWorkedWith", "PlatformWorkedWith", "WebframeWorkedWith", "MiscTechWorkedWith"],
       "2021": ["LanguageHaveWorkedWith", "DatabaseHaveWorkedWith", "PlatformHaveWorkedWith", "WebframeHaveWorkedWith", "MiscTechHaveWorkedWith", "ToolsTechHaveWorkedWith"],
       "2022": ["LanguageHaveWorkedWith", "DatabaseHaveWorkedWith", "PlatformHaveWorkedWith", "WebframeHaveWorkedWith", "MiscTechHaveWorkedWith", "ToolsTechHaveWorkedWith"],
       "2023": ["LanguageHaveWorkedWith", "DatabaseHaveWorkedWith", "PlatformHaveWorkedWith", "WebframeHaveWorkedWith", "MiscTechHaveWorkedWith", "ToolsTechHaveWorkedWith"],
       "2024": ["LanguageHaveWorkedWith", "DatabaseHaveWorkedWith", "PlatformHaveWorkedWith", "WebframeHaveWorkedWith", "MiscTechHaveWorkedWith", "ToolsTechHaveWorkedWith"],
   }
   ```
3. Filter to respondents where `MainBranch` contains "professional developer" (2021+) or `Employment` contains "Employed" (pre-2021) to get professional devs only.
4. For each skill in `SKILLS`, count respondents who listed it in any tech column (semicolon-delimited values). Use `SO_SKILL_NAMES` mapping for SO's internal names vs our canonical names:
   ```python
   SO_SKILL_NAMES = {
       "Python": ["Python"],
       "SQL": ["SQL"],  # appears in LanguageWorkedWith
       "R": ["R"],
       "Rust": ["Rust"],
       "Scala": ["Scala"],
       "PyTorch": ["PyTorch"],
       "TensorFlow": ["TensorFlow"],
       "scikit-learn": ["Scikit-learn", "scikit-learn"],
       "Keras": ["Keras"],
       "JAX": [],  # not in SO survey — skip
       "Pandas": [],  # not in SO survey — skip
       "NumPy": [],  # not in SO survey — skip
       "Spark": ["Apache Spark", "Spark"],
       "Kafka": ["Apache Kafka", "Kafka"],
       "Airflow": ["Apache Airflow", "Airflow"],
       "dbt": ["dbt"],
       "Snowflake": ["Snowflake"],
       "Databricks": ["Databricks"],
       "MLflow": [],  # not in SO survey — skip
       "Weights & Biases": [],  # not in SO survey — skip
       "LangChain": [],  # not in SO survey — skip
       "Hugging Face": ["Hugging Face"],
       "Transformers": [],  # not in SO survey — skip
       "AWS": ["AWS", "Amazon Web Services"],
       "GCP": ["Google Cloud Platform", "GCP"],
       "Azure": ["Microsoft Azure"],
       "Docker": ["Docker"],
       "Kubernetes": ["Kubernetes"],
       "Terraform": ["Terraform"],
       "FastAPI": [],  # not in SO survey — skip
       "React": ["React", "React.js"],
       "TypeScript": ["TypeScript"],
       "Git": ["Git"],
       "CI/CD": [],  # not in SO survey — skip
   }
   ```
5. Output: `{skill: pct}` dict where `pct = count / total_respondents * 100`. Cached to `data/raw/supply/stackoverflow/{year}.json`.

**Note:** Skills with empty SO_SKILL_NAMES list get `pct = None` for all years — stored as `null` in JSON, displayed as "—" in UI.

---

### Salary — Kaggle LinkedIn (`src/ingest/kaggle_salary.py`)

**Source:** Existing files on disk:
- `data/raw/archive (1)/postings.csv` — 123,849 rows with `job_id`, `description`
- `data/raw/archive (1)/jobs/salaries.csv` — 40,785 rows with `job_id`, `med_salary`, `min_salary`, `max_salary`, `pay_period`, `currency`

**Method:**
1. Load `salaries.csv`, filter to `currency=USD`, `pay_period=YEARLY`, `compensation_type=BASE_SALARY`.
2. For rows missing `med_salary`: compute as `(min_salary + max_salary) / 2` if both present.
3. Filter to salary range $30,000–$500,000 (remove outliers/data errors).
4. Join to `postings.csv` on `job_id` (inner join — only postings with valid salary).
5. For each posting, run `SKILL_PATTERNS` on `description` field. Assign salary to each skill detected.
6. Per skill: compute `p25`, `median`, `p75` of yearly salaries and `n` (sample count).
7. Only include skills with `n >= 10` (statistical floor).
8. Output: `data/raw/supply/kaggle_salary.json` — `{skill: {p25, median, p75, n}}`.

---

## Index Build Changes (`src/index_build.py`)

### New output schema (per skill)

```python
{
  "series": [...],              # existing — now HN 2020-2025 + Adzuna 2026-06+
  "latest_momentum_pct": ...,   # existing
  "latest_saturation": ...,     # existing
  "so_series": [                # NEW
    {"year": "2019", "pct": 67.2},
    {"year": "2020", "pct": 66.7},
    ...
    {"year": "2024", "pct": 51.0}
  ],
  "salary": {                   # NEW — null if n < 10
    "p25": 110000,
    "median": 145000,
    "p75": 185000,
    "n": 342
  }
}
```

### Series merge logic

`build_index()` accepts new optional parameters:
```python
def build_index(
    df: pd.DataFrame,             # live demand (Adzuna + Remotive + Firecrawl)
    supply_df: pd.DataFrame | None = None,
    hist_df: pd.DataFrame | None = None,   # NEW — HN historical demand
    so_data: dict | None = None,           # NEW — {skill: [{year, pct}]}
    salary_data: dict | None = None,       # NEW — {skill: {p25, median, p75, n}}
) -> dict
```

When `hist_df` is provided:
1. Run `pipeline.run(hist_df)` separately to get historical price series (HN corpus, indexed to 100 at 2020-01).
2. Run `pipeline.run(df)` for live demand (Adzuna corpus, indexed to 100 at its first month).
3. Concatenate both series per skill, sorted by month. Null out `mom_pct` for the first live point (source boundary).
4. If only `hist_df` provided (no live `df`): use hist series only.

---

## `run_history.py`

```python
"""
One-time historical backfill. Safe to re-run — all sources are cache-first.

Usage:
  python src/run_history.py                  # HN + SO + Kaggle salary
  python src/run_history.py --hn-only        # skip SO survey download
  python src/run_history.py --months 24      # last 24 months of HN only
"""
```

Execution order:
1. `kaggle_salary.fetch()` → `data/raw/supply/kaggle_salary.json`
2. `stackoverflow_survey.fetch_all()` → one JSON per year (2019–2024)
3. `hn_hiring.fetch_range("2020-01", "2025-12", store)` → one JSON per month (~70 files)
4. Merge HN months into `hist_df`, SO years into `so_data`, salary into `salary_data`
5. Call `index_build.build_index(live_df, supply_df, hist_df, so_data, salary_data)`
6. Write `public/index.json`

`run_all.py --history` calls `run_history.py` first (to populate caches), then runs the normal pipeline.

---

## Frontend Changes (`public/index.html`)

### 1. Salary stat box in modal

The existing `.modal-stats` grid has 3 boxes (Price, MoM, Count). Add a 4th: **Median Salary**.

CSS change: `grid-template-columns: repeat(3, 1fr)` → `repeat(4, 1fr)` on desktop, `repeat(2, 1fr)` on mobile (already handled by existing media query adding `1fr 1fr`).

In `openModal()`:
```javascript
const salary = data.salary;
document.getElementById("stat-salary").textContent =
  salary ? `$${(salary.median / 1000).toFixed(0)}k` : "—";
```

### 2. SO adoption overlay in modal chart

Add a second dataset to the modal Chart.js config:

```javascript
// Build SO series aligned to modal chart x-axis
const soSeries = data.so_series || [];
const soLabels = soSeries.map(p => p.year + "-06");  // mid-year synthetic month
const soData = soSeries.map(p => p.pct);

datasets: [
  { /* existing price line */ },
  {
    label: "SO Adoption %",
    data: soData,
    // mapped to x-axis labels by matching year-06 to existing labels
    borderColor: "#f9a825",
    borderWidth: 1.5,
    borderDash: [4, 4],
    pointRadius: 3,
    tension: 0.3,
    fill: false,
    yAxisID: "y2",
  }
]
```

Second y-axis (`y2`): right side, 0–100 range, `%` suffix on tick labels, hidden gridlines.

Only rendered if `so_series` has at least 2 data points.

---

## Error Handling

- **SO survey download fails**: log warning, skip that year. Proceed with available years.
- **HN thread fetch fails**: log warning, skip that month. Cache partial results.
- **Kaggle files missing**: log warning, skip salary enrichment. `salary` field = `null` for all skills.
- **SO skill not in survey**: `pct = null` for that year — displayed as gap in chart (Chart.js skips null points with `spanGaps: false`).

---

## Testing

- `tests/test_hn_hiring.py` — mock Algolia API responses, verify skill extraction from raw comment HTML
- `tests/test_stackoverflow_survey.py` — mock CSV rows, verify pct calculation and column-name mapping
- `tests/test_kaggle_salary.py` — mock postings + salaries CSVs, verify p25/median/p75 with known inputs
- `tests/test_index_build_historical.py` — verify series merge logic: HN series + Adzuna series concat correctly, boundary mom_pct is null

---

## Self-Review

**Spec coverage:**
- ✅ HN demand ingest with caching
- ✅ SO survey supply ingest with year→column mapping
- ✅ Kaggle salary extraction with outlier filter
- ✅ `run_history.py` orchestrator (idempotent, cache-first)
- ✅ `index_build.py` signature extension with backward-compatible defaults
- ✅ Series merge with source-boundary momentum null
- ✅ Frontend: salary stat box + SO adoption overlay
- ✅ Error handling for each source

**Placeholder scan:** None. All column names, URL patterns, salary ranges, and API endpoints are specified.

**Internal consistency:** `build_index()` new parameters have defaults (`None`) so existing `run_all.py` calls without `--history` continue to work unchanged.

**Scope:** Single pipeline + single frontend file. Appropriate for one implementation plan.
