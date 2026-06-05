# Skill Stock — Project Brief

## What we're building
A "Spurious Correlations"–style static website that treats job-market skills like
tradeable stocks. Each skill has a "price" derived from its share of job postings
over time, rendered as ticker-style price charts. The tone is playful and
self-aware — a curiosity object, NOT an authoritative career tool.

## Hard scope rules (read first, do not violate)
- **Phase 1 is the deliverable.** Ship a working static site on Kaggle data before
  doing anything else. Do not start Phase 2 until Phase 1 is fully working and committed.
- **Static-site only.** No live backend, no database server. Pipeline runs offline,
  output is a single `index.json` consumed by a static frontend.
- **Curated, not exhaustive.** ~30 hand-picked skills. Do NOT build a giant
  auto-extracted taxonomy.
- **Monthly buckets.** Time series is monthly points, never real-time.
- **Honesty over precision.** This is a demand-led index with rough estimates.
  Label data dates clearly. Do not let the UI imply it's real career advice.
- If you find yourself reaching for multi-source scraping, ML-based dedup, salary
  modeling, or a large taxonomy — STOP. Add it to a "Future Work" section in the
  README instead of building it.

## Decisions locked before coding
- **Skill list (~30):** ML/data/eng cluster — e.g. Python, PyTorch, TensorFlow,
  scikit-learn, SQL, Spark, Kafka, Airflow, dbt, FastAPI, Docker, Kubernetes, AWS,
  GCP, Azure, Terraform, MLflow, Weights & Biases, LangChain, Hugging Face,
  Transformers, Pandas, NumPy, Git, CI/CD, React, TypeScript, Snowflake, Databricks,
  Rust. (Finalize this list in a single `SKILLS` constant — easy to edit.)
- **Price formula (v1, keep simple):**
  `price[skill][month] = (distinct postings mentioning skill / total distinct postings that month)`
  Then index each skill to 100 at its first month so charts are comparable.
- **Momentum:** month-over-month % change in price.
- **Saturation overlay:** defer to Phase 1.5 (optional). Do not build first.

---

## Phase 1 — Demo on Kaggle data (build this now)

### Step 1: Data
- Use a Kaggle job-postings dataset that includes **posting date** and ideally
  **parsed skills** (the large LinkedIn postings dataset with skills + dates is ideal
  because it spans time, giving real history for the charts).
- Place the raw file(s) in `data/raw/`. Read locally; do not hit any network in Phase 1.

### Step 2: Clean + dedup pipeline (`src/pipeline.py`)
Write this as **reusable functions** — Phase 2 will feed the same code with Adzuna data.
- Normalize fields: lowercase + strip titles, standardize company names, parse dates to
  month buckets (`YYYY-MM`).
- **Exact dedup:** hash a canonical key `(company_norm, title_norm, location_norm, month)`,
  drop duplicates.
- **Near-dup catch (lightweight):** for postings sharing company+month, collapse highly
  similar titles (simple token Jaccard or rapidfuzz ratio over a threshold). Keep it cheap —
  no embeddings, no LSH in Phase 1.
- **Skill extraction AFTER dedup:** match each `SKILLS` entry against the posting
  description/skills field using word-boundary regex (case-insensitive, normalize back to
  canonical casing). Verbatim matches only — never infer skills not present in text.
- **Count distinct postings, not mentions** — increment a skill once per deduplicated job.

### Step 3: Compute index (`src/index_build.py`)
- For each skill × month: distinct posting count, share, indexed price (base 100),
  MoM momentum, and salary stats if the dataset has salary (else null).
- Write everything to a single `public/index.json` shaped for the frontend, e.g.:
  ```json
  {
    "generated_at": "2026-06-05",
    "data_through": "YYYY-MM",
    "skills": {
      "PyTorch": {
        "series": [{"month": "2024-01", "price": 100, "share": 0.041, "count": 312}, ...],
        "latest_momentum_pct": 12.4
      }
    }
  }
  ```

### Step 4: Frontend (`public/`)
- Plain static HTML/CSS/JS (or a single-file React if preferred). Load `index.json`,
  no backend calls.
- Stock-ticker aesthetic: monospace/terminal vibe, green/red movers, a price chart per
  skill (use a lightweight charting lib).
- **Landing view:** "Today's Biggest Movers" (top gainers/losers by momentum) + a
  searchable list of all skill "stocks."
- **Detail view:** the skill's price chart over time + a one-line dry caption
  (e.g. "PyTorch up 340% this quarter. Analysts remain baffled.").
- Footer must state: data source, `data_through` date, and a clear "this is for fun"
  disclaimer.

### Step 5: Ship
- Host static on GitHub Pages / Netlify / Cloudflare Pages.
- README: what it is, the playful framing, data source + date, and a "Future Work"
  section (multi-source, saturation index, auto-refresh) — explicitly NOT built yet.

**Phase 1 is DONE when the static site loads real charts from Kaggle data and is deployed.**

---

## Phase 2 — Light Adzuna freshness (ONLY after Phase 1 ships)
- Get a free Adzuna developer API key. Store as an env var / GitHub Actions secret —
  never commit it.
- Add `src/fetch_adzuna.py`: pull current-month postings for the ~30 `SKILLS`,
  normalize into the SAME schema the Kaggle loader produces, then run the SAME
  `pipeline.py` + `index_build.py` functions. Append one new month to `index.json`.
- Wire a monthly GitHub Actions cron that runs the fetch, rebuilds `index.json`,
  and auto-commits. Must be set-and-forget — it should not break silently.
- Keep it monthly and capped to the curated skill list. No scaling, no extra sources.

---

## Agent navigation — read before deciding what to do next

Use this to figure out where you are and what you're allowed to touch. Do not skip
ahead. Each gate must be fully true before the next phase begins.

**Where am I?** Check `public/index.json` and the deploy status:
- No `index.json` or it doesn't load in the frontend → you are in **Phase 1**. Work only on Phase 1.
- Phase 1 gate passed but no `fetch_adzuna.py` / no cron → you may begin **Phase 2**.
- Phase 2 working → STOP. Everything beyond is "Future Work" (see below). Do not build it
  unless the user explicitly names a phase and tells you to start.

**Phase 1 gate (all must be true to call Phase 1 done):**
- [ ] A Kaggle dataset with posting dates is loaded and read offline (no network).
- [ ] `pipeline.py` cleans, dedups (exact + cheap near-dup), and matches verbatim skills.
- [ ] Skills are counted once per deduplicated posting, never per mention.
- [ ] `index_build.py` writes a valid `public/index.json` with per-skill monthly series.
- [ ] Static frontend loads that JSON, shows movers + per-skill charts, with a visible
      data-date and "for fun" disclaimer.
- [ ] Site is deployed to a static host.

**Phase 2 gate:**
- [ ] Adzuna fetch normalizes into the SAME schema and reuses `pipeline.py` + `index_build.py`.
- [ ] Monthly cron rebuilds and commits `index.json` without manual steps.
- [ ] No secrets committed.

**When stuck or tempted to expand scope:** do not invent a bigger architecture. Either
(a) ask the user a single specific question, or (b) write the idea into the README's
"Future Work" section and continue with the current phase. Reaching for embeddings,
multi-source scraping, forecasting, or a large taxonomy is the signal to stop, not proceed.

---

## Future Work / Vision (DO NOT BUILD — capture in README only)

> These phases are intentionally **not** part of the build. They exist so the vision is
> recorded and reads well to a reader of the repo. An agent must never start any of these
> without an explicit, phase-named instruction from the user. If unsure, treat as off-limits.

Ordered by phase number, but note the **real value ordering** at the end — it differs.

- **Phase 3 — Multi-source + real dedup.** Broaden sources (wider Adzuna coverage, a cheap
  aggregator tier, Firecrawl against friendly ATS career pages). Upgrade dedup from rapidfuzz
  to embeddings + MinHash/LSH for cross-source duplicates. *Pure infrastructure — more accurate
  charts, not more interesting ones. Diminishing returns without traction.*

- **Phase 4 — Saturation index (the actual differentiator).** Add the supply side:
  course-enrollment proxies, certification counts, GitHub/Stack Overflow activity per
  technology, new-grad pipeline estimates. Compute the demand–supply gap so a skill reads as
  "hot but crowded" (closing window) vs "hot but undersupplied" (durable scarcity) — the
  "P/E ratio" analog. *Most interesting metric, least defensible data. The playful framing is
  what makes shipping it honest.*

- **Phase 5 — Leading indicators / light forecasting.** With ~2 years of history, flag skills
  before they peak via simple trend/seasonality models. *Highest honesty risk — a forecast
  implies confidence the data can't back. Label as entertainment only, if built at all.*

- **Phase 6 — Personal portfolio layer.** User enters their skills; site renders a personal
  "portfolio" vs the market — what's appreciating, depreciating, gaps, what to "buy."
  *Highest usefulness-per-effort and needs no new data — just UI on top of Phase 4 output.
  If anything post-Phase-2 gets built, this is it.*

- **Phase 7 — Surfaces and reach.** Embeddable ticker widgets, read-only public API, regional
  breakdowns, and a Germany/EU lens (German market data, EUR salary modeling). *Distribution
  moves — only sensible once there's an audience. The EU lens is the one personally useful bit.*

**Real value ordering (not phase order):** Phase 1 → Phase 6 (sticky, no new data) →
Phase 4 (the real idea, hardest data) → the rest only with traction. Phases 3/5/7 are
infrastructure / vanity / distribution respectively.

---

## Repo layout
```
skill-stock/
  data/raw/            # Kaggle dump (gitignored if large)
  src/
    pipeline.py        # clean + dedup + skill match (reusable)
    index_build.py     # compute price/momentum -> index.json
    fetch_adzuna.py    # Phase 2 only
  public/
    index.json         # generated artifact
    index.html / app   # static frontend
  .github/workflows/   # Phase 2 cron
  README.md            # incl. "Future Work" section (vision only, not built)
```

## Tech constraints
- Python for the pipeline (pandas, rapidfuzz for near-dup; nothing heavier in Phase 1).
- Frontend lightweight and static. No localStorage/sessionStorage if built as an artifact.
- Keep secrets out of the repo.

## Definition of success
A shareable, honest, good-looking static site that makes someone want to screenshot it —
built on a clean dedup pipeline that proves real data-engineering, with freshness as an
optional bonus and not a maintenance trap.
