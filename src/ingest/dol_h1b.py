"""
src/ingest/dol_h1b.py — DOL H-1B/LCA Disclosure Data for tech salary enrichment.

Downloads quarterly H-1B Labor Condition Application disclosure files from the
Department of Labor (public, no auth). Filters to certified tech occupations
(SOC 15-xxxx), normalises wages to annual, and saves a compact JSON cache.

FY runs Oct–Sep: FY2024 = Oct 2023 – Sep 2024.

Usage:
    python src/ingest/dol_h1b.py                        # FY2023 Q4 only (demo)
    python src/ingest/dol_h1b.py --fy 2022 2023 2024    # specific years
    python src/ingest/dol_h1b.py --all                  # FY2020-FY2024 all quarters
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import io
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
import pandas as pd

CACHE_DIR = "data/raw/government/dol_h1b"

# Available quarters per fiscal year
QUARTERS = ["Q1", "Q2", "Q3", "Q4"]

# FY2025 only has Q1-Q2 so far; handle gracefully via HTTP 404
FISCAL_YEARS = ["2020", "2021", "2022", "2023", "2024", "2025"]

def _url(fy: str, q: str) -> str:
    return (
        f"https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/"
        f"LCA_Disclosure_Data_FY{fy}_{q}.xlsx"
    )


# Wage unit → annual multiplier
_WAGE_MULT: dict[str, float] = {
    "hour":       2080.0,
    "week":       52.0,
    "bi-weekly":  26.0,
    "month":      12.0,
    "year":       1.0,
}

# Skill keywords to extract from job title / SOC title
_SKILL_KEYWORDS: dict[str, list[str]] = {
    "Python":       ["python"],
    "Java":         ["java"],
    "JavaScript":   ["javascript", "js developer", "node.js", "nodejs", "frontend", "react", "angular", "vue"],
    "TypeScript":   ["typescript"],
    "SQL":          ["sql", "database", "dba", "data engineer"],
    "R":            [" r developer", "r programmer", "statistician"],
    "Scala":        ["scala"],
    "Rust":         ["rust developer", "rust engineer"],
    "Go":           ["golang", "go developer", "go engineer"],
    "C++":          ["c++ ", "cpp", "c/c++"],
    "AWS":          ["aws", "amazon web services", "cloud engineer", "cloud architect"],
    "GCP":          ["gcp", "google cloud"],
    "Azure":        ["azure", "microsoft cloud"],
    "Docker":       ["docker", "container"],
    "Kubernetes":   ["kubernetes", "k8s", "devops"],
    "Terraform":    ["terraform", "infrastructure"],
    "React":        ["react", "frontend developer", "front-end developer"],
    "Machine Learning": ["machine learning", "ml engineer", "ai engineer", "deep learning"],
    "Data Science": ["data scientist", "data science"],
    "Data Engineering": ["data engineer", "data pipeline", "etl"],
    "Cybersecurity": ["security engineer", "security analyst", "cybersecurity", "infosec"],
}

# Tech SOC prefixes (Computer & Math = 15, Tech managers = 11-3)
_TECH_SOC = ("15-", "11-3")


def _to_annual(wage: float, unit: str) -> float | None:
    unit_clean = str(unit).lower().strip()
    for key, mult in _WAGE_MULT.items():
        if key in unit_clean:
            return wage * mult
    return None


def _extract_skills(title: str, soc_title: str) -> list[str]:
    text = (str(title) + " " + str(soc_title)).lower()
    found = []
    for skill, keywords in _SKILL_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            found.append(skill)
    return found


def fetch_quarter(
    fy: str,
    quarter: str,
    cache_dir: str = CACHE_DIR,
) -> dict | None:
    """
    Download + process one DOL H-1B quarter. Cache-first.
    Returns {skill: {count, wages: [...]}} or None if not available.
    """
    cache_path = os.path.join(cache_dir, f"FY{fy}_{quarter}.json")
    if os.path.exists(cache_path):
        print(f"  [h1b] cache hit FY{fy}_{quarter}")
        with open(cache_path) as f:
            return json.load(f)

    url = _url(fy, quarter)
    print(f"  [h1b] downloading FY{fy}_{quarter} (~60-90MB) ...")
    try:
        resp = requests.get(url, timeout=300, stream=True)
        if resp.status_code == 404:
            print(f"  [h1b] not available: FY{fy}_{quarter}")
            return None
        resp.raise_for_status()
        content = resp.content
    except Exception as e:
        print(f"  [h1b] warn FY{fy}_{quarter}: {e}")
        return None

    print(f"  [h1b] parsing FY{fy}_{quarter} ({len(content)//1_000_000}MB) ...")
    try:
        df = pd.read_excel(io.BytesIO(content), engine="openpyxl")
    except Exception as e:
        print(f"  [h1b] parse error FY{fy}_{quarter}: {e}")
        return None

    # Normalise column names (differ slightly across years)
    df.columns = [c.upper().strip() for c in df.columns]

    # Filter: certified cases only
    status_col = next((c for c in df.columns if "CASE_STATUS" in c), None)
    if status_col:
        df = df[df[status_col].astype(str).str.upper().str.contains("CERTIFIED")]

    # Filter: tech SOC codes
    soc_col = next((c for c in df.columns if c in ("SOC_CODE", "SOC_CD")), None)
    if soc_col:
        df = df[df[soc_col].astype(str).str.startswith(_TECH_SOC)]

    if df.empty:
        print(f"  [h1b] no tech rows in FY{fy}_{quarter}")
        return {}

    # Find wage columns
    wage_col = next((c for c in df.columns if "WAGE_RATE_OF_PAY_FROM" in c
                     or c == "PREVAILING_WAGE"), None)
    unit_col = next((c for c in df.columns if "WAGE_UNIT" in c), None)
    title_col = next((c for c in df.columns if c in ("JOB_TITLE", "POSITION_TITLE")), None)
    soc_title_col = next((c for c in df.columns if "SOC_TITLE" in c), None)
    employer_col = next((c for c in df.columns if "EMPLOYER_NAME" in c), None)
    start_col = next((c for c in df.columns if "PERIOD_OF_EMPLOYMENT_START_DATE" in c
                      or c == "BEGIN_DATE"), None)

    # Build skill → wages mapping
    skill_wages: dict[str, list[float]] = {s: [] for s in _SKILL_KEYWORDS}

    for _, row in df.iterrows():
        # Annual wage
        try:
            raw_wage = float(str(row.get(wage_col, 0) or 0).replace(",", "").replace("$", ""))
        except (ValueError, TypeError):
            continue
        unit = str(row.get(unit_col, "year")) if unit_col else "year"
        annual = _to_annual(raw_wage, unit)
        if annual is None or not (30_000 <= annual <= 800_000):
            continue

        job_title = str(row.get(title_col, "")) if title_col else ""
        soc_title = str(row.get(soc_title_col, "")) if soc_title_col else ""
        skills = _extract_skills(job_title, soc_title)

        # If no specific skill matched, bucket by SOC code
        if not skills:
            soc = str(row.get(soc_col, "")) if soc_col else ""
            if soc.startswith("15-1252"):
                skills = ["Python", "JavaScript"]
            elif soc.startswith("15-2051"):
                skills = ["Machine Learning", "Data Science"]
            elif soc.startswith("15-12"):
                skills = ["Python"]

        for skill in skills:
            if skill in skill_wages:
                skill_wages[skill].append(annual)

    # Aggregate to percentiles
    result: dict = {}
    for skill, wages in skill_wages.items():
        if len(wages) < 10:
            continue
        wages_s = sorted(wages)
        n = len(wages_s)
        def pct(p: float) -> int:
            k = (n - 1) * p
            lo, hi = int(k), min(int(k) + 1, n - 1)
            return int(wages_s[lo] + (wages_s[hi] - wages_s[lo]) * (k - lo))
        result[skill] = {
            "n":      n,
            "p25":    pct(0.25),
            "median": pct(0.50),
            "p75":    pct(0.75),
            "p90":    pct(0.90),
            "mean":   int(sum(wages_s) / n),
            "fy":     fy,
            "quarter": quarter,
        }

    print(f"  [h1b] FY{fy}_{quarter}: {len(df):,} tech rows, {len(result)} skills with salary data")

    os.makedirs(cache_dir, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(result, f, indent=2)
    return result


def fetch_all(
    fiscal_years: list[str] | None = None,
    quarters: list[str] | None = None,
    cache_dir: str = CACHE_DIR,
) -> dict[str, dict[str, list[dict]]]:
    """
    Fetch multiple FY/quarters. Returns {skill: [{fy, quarter, median, p25, p75, n}, ...]}.
    """
    if fiscal_years is None:
        fiscal_years = FISCAL_YEARS
    if quarters is None:
        quarters = QUARTERS

    by_skill: dict[str, list[dict]] = {}
    for fy in fiscal_years:
        for q in quarters:
            data = fetch_quarter(fy, q, cache_dir)
            if not data:
                continue
            for skill, sal in data.items():
                if skill not in by_skill:
                    by_skill[skill] = []
                by_skill[skill].append(sal)

    return by_skill


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch DOL H-1B salary data for tech occupations.")
    parser.add_argument("--fy",  nargs="+", default=["2023"], help="Fiscal year(s) e.g. 2023 2024")
    parser.add_argument("--quarter", nargs="+", default=["Q4"], help="Quarter(s) e.g. Q3 Q4")
    parser.add_argument("--all", action="store_true", help="Fetch all available quarters FY2020-FY2024")
    args = parser.parse_args()

    if args.all:
        data = fetch_all(fiscal_years=["2020","2021","2022","2023","2024"])
    else:
        data = fetch_all(fiscal_years=args.fy, quarters=args.quarter)

    if not data:
        print("No data — check network connection.")
        sys.exit(1)

    # Print summary
    print(f"\n{'Skill':<22} {'n':>7} {'P25':>9} {'Median':>9} {'P75':>9} {'P90':>9}")
    print("-" * 68)
    for skill, entries in sorted(data.items(), key=lambda x: -(x[1][0].get("median") or 0)):
        e = entries[-1]  # most recent
        print(
            f"{skill:<22} {e.get('n',0):>7,}"
            f" {e.get('p25',0):>9,}"
            f" {e.get('median',0):>9,}"
            f" {e.get('p75',0):>9,}"
            f" {e.get('p90',0):>9,}"
        )
