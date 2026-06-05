# Skill Stock — Job Market Ticker

> A Spurious Correlations–style static site that treats job-market skills like tradeable stocks.
> For entertainment purposes. Not career advice.

**Live site:** [skill-stock.netlify.app](https://skill-stock.netlify.app) _(or your deployment URL)_

---

## What it is

Skill prices are a **demand-led index** — each skill's "price" is its share of distinct
deduplicated job postings in a given month, indexed to 100 at its first appearance.
The tone is playful and self-aware. Please do not make career decisions based on a chart
shaped like a hockey stick.

---

## Phase 1: Running the pipeline

### 1. Get the data

Download the **LinkedIn Job Postings** dataset from Kaggle:  
https://www.kaggle.com/datasets/arshkon/linkedin-job-postings

Place `job_postings.csv` (and optionally `job_skills.csv` + `skills.csv`) in `data/raw/`.

```
data/raw/
  job_postings.csv    ← required
  job_skills.csv      ← optional (improves skill matching)
  skills.csv          ← optional (maps abbr → name)
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run

```bash
python src/run_pipeline.py
```

This writes `public/index.json`. Open `public/index.html` in a browser (or `npx serve public`).

---

## Deploying (Netlify / GitHub Pages / Cloudflare Pages)

The `public/` folder is a fully static site. Point your host at it:

- **Netlify drop:** drag `public/` onto netlify.com/drop
- **GitHub Pages:** set Pages source to `public/` on `main`
- **Cloudflare Pages:** build command `python src/run_pipeline.py`, output dir `public/`

Commit `public/index.json` before deploying (it is gitignored by default — remove the comment in `.gitignore` once the pipeline runs cleanly).

---

## Customising the skill list

Edit the `SKILLS` list in `src/skills.py`. Regex aliases (e.g. `wandb` → `Weights & Biases`)
live in `_ALIASES`. Re-run the pipeline after any change.

---

## Future Work (not built)

- **Multi-source freshness (Phase 2):** Adzuna API, monthly GitHub Actions cron
- **Saturation overlay:** supply-side proxy via LinkedIn member skills data
- **Salary index:** normalised salary per skill per month
- **Auto-taxonomy:** NLP-based skill extraction instead of curated list
- **Large-scale dedup:** LSH or embedding similarity across sources

These are listed here so they are not accidentally built during Phase 1.

---

## Data notes

| Field | Value |
|-------|-------|
| Source | LinkedIn Job Postings (Kaggle, arshkon) |
| Coverage | 2023–2024 (dataset-dependent) |
| Methodology | Distinct deduplicated postings per skill per month, indexed to 100 |
| Dedup | Exact hash on (company, title, location, month) + near-dup title collapse |
| Skill match | Word-boundary regex, curated aliases, verbatim only |

Data through date is displayed in the site footer.
