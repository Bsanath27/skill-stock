# Skill Stock — Phase 3 + Phase 4 Design

**Date:** 2026-06-05
**Status:** Approved
**Scope:** Unified multi-source demand pipeline (Phase 3) + saturation index (Phase 4)

---

## Goal

Make the data richer and more honest by:
1. Expanding demand-side sources (Phase 3): wider Adzuna, Firecrawl ATS scraping, Remotive aggregator
2. Adding supply-side signals (Phase 4): Udemy course counts, NCES graduation data, GitHub repo activity
3. Cross-source deduplication with MinHash/LSH
4. Computing a saturation/scarcity score per skill per month
5. Showing saturation in the frontend alongside the existing price chart

All raw data is saved to local disk before processing. No credit is ever spent twice.

---

## Architecture

### Unified data layer

```
data/
  raw/
    demand/
      adzuna/       {YYYY-MM}.json          saved before processing
      firecrawl/    {YYYY-MM}/              one file per company
      remotive/     {YYYY-MM}.json
    supply/
      udemy/        {YYYY-MM}.json
      nces/         {YYYY}.csv              manual annual download
      github/       {YYYY-MM}.json

src/
  ingest/
    __init__.py
    adzuna.py
    firecrawl.py
    remotive.py
    udemy.py
    nces.py
    github_stats.py
  pipeline.py        unchanged
  index_build.py     extended — emits saturation alongside price
  run_all.py         orchestrator
```

### Ingest module contract

Every ingest module implements:

```python
def fetch(month: str, cache_dir: str) -> tuple[Path, pd.DataFrame]:
    # 1. Return cached file if already exists (idempotent)
    # 2. Fetch from source
    # 3. Save raw data to disk BEFORE any transformation
    # 4. Return (raw_path, normalised_dataframe)
```

`run_all.py` calls each module, checks cache first, merges all demand DataFrames, runs MinHash/LSH dedup, calls `index_build.py` once with the full merged set.

---

## Source Modules

### Demand sources

| Module | Source | Method | Cache path |
|--------|--------|---------|------------|
| `adzuna.py` | Adzuna API | Wider queries (broader titles + GB market), up to 5 pages/skill | `demand/adzuna/{YYYY-MM}.json` |
| `firecrawl.py` | Greenhouse/Lever/Workday ATS | Firecrawl scrapes ~25 hand-picked tech company career pages | `demand/firecrawl/{YYYY-MM}/{company}.json` |
| `remotive.py` | Remotive public API | Free, no auth, returns tech listings | `demand/remotive/{YYYY-MM}.json` |

All three normalise to the same DataFrame schema: `[company_norm, title_norm, location_norm, month, text]`

### Supply sources

| Module | Source | Method | Cache path | Cadence |
|--------|--------|---------|------------|---------|
| `udemy.py` | Udemy public search | Course count per skill keyword (no auth) | `supply/udemy/{YYYY-MM}.json` | Monthly |
| `nces.py` | NCES IPEDS data | Parse annual CSV — CS + DS + Stats degrees awarded | `supply/nces/{YYYY}.csv` | Annual (manual download) |
| `github_stats.py` | GitHub REST API | Stars + forks for one canonical repo per skill | `supply/github/{YYYY-MM}.json` | Monthly |

Supply sources do NOT go through `pipeline.py` dedup — they are aggregated separately.

### Company list for Firecrawl (`src/ingest/companies.py`)

~25 hand-picked tech companies with Greenhouse/Lever/Workday ATS pages:
Stripe, Airbnb, Notion, Linear, Vercel, Databricks, Hugging Face, OpenAI, Anthropic,
Figma, Cloudflare, Plaid, Brex, Rippling, Scale AI, Cohere, Mistral, Weights & Biases,
Modal, Anyscale, Together AI, Replicate, LlamaIndex, Langfuse, dbt Labs.

---

## Deduplication

### Within-source (existing)
- Exact hash dedup on `(company_norm, title_norm, location_norm, month)`
- Near-dup title collapse with rapidfuzz within same company+month

### Cross-source (new — MinHash/LSH)
After merging all demand DataFrames:
- Tokenise `title_norm + company_norm` into shingles
- Build MinHash signatures (128 permutations)
- LSH with threshold 0.7 — collapse duplicates, keep first-seen
- Library: `datasketch`

---

## Saturation Formula

```
demand_share[skill][month] = postings mentioning skill / total postings

supply_score[skill][month] = weighted composite of normalised signals:
    0.5 × norm(udemy_course_count)
    0.3 × norm(nces_grad_volume_proxy)   CS+DS+Stats degrees, mapped per skill
    0.2 × norm(github_stars_delta)       MoM star growth as ecosystem proxy

saturation[skill][month] = supply_score / (demand_share + ε)
  normalised to 0–100 scale across all skills in same month
```

- **High saturation (→100):** many learners relative to jobs → crowded
- **Low saturation (→0):** few learners relative to jobs → scarce/opportunity
- NCES is annual — supply_score interpolates linearly between years for monthly points
- Skills with missing supply data get `saturation: null` — never fabricated

### Skill → NCES degree mapping

| Skill cluster | NCES CIP codes |
|---|---|
| Python, SQL, Pandas, NumPy, scikit-learn, etc. | 11.0701 (CS), 30.7001 (Data Science) |
| AWS, GCP, Azure, Docker, Kubernetes | 11.0901 (Network/Systems) |
| React, TypeScript, FastAPI | 11.0201 (Web/Multimedia) |
| R, Spark, dbt, Airflow | 27.0501 (Statistics) |

---

## index.json Schema (extended)

Backward compatible — old fields unchanged, new fields added:

```json
{
  "generated_at": "2026-06-05",
  "data_through": "2026-06",
  "skills": {
    "PyTorch": {
      "series": [
        {
          "month": "2024-03",
          "price": 100.0,
          "share": 0.041,
          "count": 312,
          "mom_pct": null,
          "source": "kaggle",
          "saturation": 42.3,
          "supply": {
            "udemy_courses": 184,
            "github_stars_delta": 2100,
            "nces_proxy": 0.31
          }
        }
      ],
      "latest_momentum_pct": 12.4,
      "latest_saturation": 42.3
    }
  }
}
```

---

## Frontend Changes

Two additions to `public/index.html`. Nothing rewritten.

### 1. Scarcity meter in skill modal
Horizontal bar below the price chart:
- Green end = scarce (low saturation score)
- Red end = crowded (high saturation score)
- Label: *"Scarcity score: 68 — more jobs than learners"*
- Hidden if `saturation` is null for that skill

### 2. Saturation dot in skills table
New column replaces empty right padding:
- 🟢 scarce (0–33)
- 🟡 balanced (34–66)
- 🔴 crowded (67–100)

Movers grid and ticker tape are unchanged — momentum stays the headline number.

---

## Orchestration (run_all.py)

```
run_all.py
  1. For each demand source: fetch(month) → cache check → merge DataFrame
  2. MinHash/LSH cross-source dedup on merged demand DataFrame
  3. pipeline.run(merged_df) → clean_df
  4. For each supply source: fetch(month/year) → cache check → supply_df
  5. index_build.build_index(clean_df, supply_df) → index
  6. index_build.write_index(index, public/index.json)
```

Idempotent: re-running the same month uses cached raw files and produces the same output.

---

## GitHub Actions update

Add supply sources to the existing monthly cron:

```yaml
env:
  ADZUNA_APP_ID:      ${{ secrets.ADZUNA_APP_ID }}
  ADZUNA_APP_KEY:     ${{ secrets.ADZUNA_APP_KEY }}
  FIRECRAWL_API_KEY:  ${{ secrets.FIRECRAWL_API_KEY }}
  GITHUB_TOKEN:       ${{ secrets.GITHUB_TOKEN }}
```

Remotive and Udemy require no auth. NCES is an annual manual download — cron skips it if current year CSV is already cached.

---

## New dependencies

```
datasketch>=1.6    # MinHash/LSH cross-source dedup
firecrawl-py>=1.0  # Firecrawl SDK
```

---

## What is NOT built

- Salary modeling (deferred to README Future Work)
- Embedding-based skill inference (out of scope — verbatim match only)
- User accounts, watchlists, alerts (Phase 6)
- Regional breakdowns / EU lens (Phase 7)
- Forecasting (Phase 5)
