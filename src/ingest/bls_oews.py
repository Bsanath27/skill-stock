"""
src/ingest/bls_oews.py — BLS Occupational Employment and Wage Statistics (OEWS).

Fetches annual employment counts + wage percentiles for 13 tech SOC codes.
Requires BLS_API_KEY env var (free registration at api.bls.gov).

Usage:
    python src/ingest/bls_oews.py              # fetch 2020-2023, print summary
    python src/ingest/bls_oews.py --start 2019 --end 2023
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests

BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
CACHE_DIR    = "data/raw/government/bls_oews"

# SOC 2018 codes for tech occupations (6-digit, no dash)
TECH_OCCUPATIONS: dict[str, str] = {
    "151252": "Software Developers",
    "152051": "Data Scientists",
    "151211": "Computer Systems Analysts",
    "151212": "Information Security Analysts",
    "151244": "Network and Computer Systems Administrators",
    "151241": "Computer Network Architects",
    "151254": "Web Developers",
    "151253": "Software Quality Assurance Analysts",
    "152031": "Operations Research Analysts",
    "151221": "Computer and Information Research Scientists",
    "151243": "Database Architects",
    "151299": "Computer Occupations All Other",
    "151232": "Computer User Support Specialists",
}

# BLS OEWS data type codes
DATA_TYPES: dict[str, str] = {
    "01": "employment",        # employment in thousands
    "04": "annual_mean",       # annual mean wage
    "09": "annual_p25",        # annual 25th percentile wage
    "10": "annual_median",     # annual median wage (50th pct)
    "11": "annual_p75",        # annual 75th percentile wage
    "12": "annual_p90",        # annual 90th percentile wage
}

# SOC code → skills that commonly appear in this occupation
SOC_TO_SKILLS: dict[str, list[str]] = {
    "151252": ["Python", "JavaScript", "TypeScript", "React", "Git", "Docker", "CI/CD"],
    "152051": ["Python", "R", "TensorFlow", "PyTorch", "scikit-learn", "Pandas", "NumPy", "SQL", "Spark"],
    "151211": ["SQL", "Python", "AWS", "Azure", "Docker"],
    "151212": ["Python", "Docker", "Kubernetes", "Terraform", "AWS"],
    "151244": ["AWS", "Azure", "GCP", "Docker", "Kubernetes", "Terraform"],
    "151241": ["AWS", "Azure", "GCP", "Terraform", "Kubernetes"],
    "151254": ["JavaScript", "TypeScript", "React", "FastAPI", "Git"],
    "151253": ["Python", "Git", "CI/CD", "Docker"],
    "152031": ["Python", "R", "SQL", "Pandas", "NumPy"],
    "151221": ["Python", "R", "TensorFlow", "PyTorch", "JAX"],
    "151243": ["SQL", "PostgreSQL", "Databricks", "Snowflake"],
    "151299": ["Python", "SQL", "Docker", "Git"],
    "151232": ["Python", "SQL", "Git"],
}


def _series_id(occ_code: str, data_type: str) -> str:
    # Format: OEUN + area(7) + industry(6) + occ(6) + datatype(2)
    # OEUN = national OEWS, 0000000 = all areas, 000000 = all industries
    return f"OEUN0000000000000{occ_code}{data_type}"


def _parse_series_id(series_id: str) -> tuple[str, str]:
    """Return (occ_code, data_type) from series ID."""
    # OEUN(4) + area(7) + industry(6) + occ(6) + dtype(2) = 25 chars
    occ_code  = series_id[17:23]
    data_type = series_id[23:25]
    return occ_code, data_type


def _build_all_series() -> list[str]:
    ids = []
    for occ_code in TECH_OCCUPATIONS:
        for data_type in DATA_TYPES:
            ids.append(_series_id(occ_code, data_type))
    return ids


def _query_bls(series_ids: list[str], start_year: int, end_year: int, api_key: str) -> dict[str, list]:
    """Query BLS API in batches of 50. Returns {series_id: [data_points]}."""
    raw: dict[str, list] = {}
    batch_size = 50

    for i in range(0, len(series_ids), batch_size):
        batch = series_ids[i : i + batch_size]
        payload = {
            "seriesid":       batch,
            "startyear":      str(start_year),
            "endyear":        str(end_year),
            "registrationkey": api_key,
        }
        try:
            resp = requests.post(BLS_API_URL, json=payload, timeout=30)
            resp.raise_for_status()
        except Exception as e:
            print(f"  [bls] warn: request failed for batch {i//batch_size + 1}: {e}")
            continue

        body = resp.json()
        if body.get("status") != "REQUEST_SUCCEEDED":
            msgs = body.get("message", [])
            print(f"  [bls] warn: API error — {msgs}")
            continue

        for series in body.get("Results", {}).get("series", []):
            raw[series["seriesID"]] = series.get("data", [])

        if i + batch_size < len(series_ids):
            time.sleep(0.5)   # stay within rate limits

    return raw


def _parse_raw(raw: dict[str, list]) -> dict[str, dict[str, dict[str, float | None]]]:
    """
    Parse raw BLS response into:
      {occupation_name: {year_str: {metric_name: value}}}
    """
    result: dict[str, dict[str, dict[str, float | None]]] = {}

    for series_id, data_points in raw.items():
        if len(series_id) < 25:
            continue
        occ_code, data_type = _parse_series_id(series_id)
        occ_name = TECH_OCCUPATIONS.get(occ_code)
        metric   = DATA_TYPES.get(data_type)
        if not occ_name or not metric:
            continue

        if occ_name not in result:
            result[occ_name] = {}

        for pt in data_points:
            year   = pt.get("year", "")
            raw_val = pt.get("value", "")
            try:
                val: float | None = float(str(raw_val).replace(",", ""))
            except (ValueError, TypeError):
                val = None

            if year not in result[occ_name]:
                result[occ_name][year] = {}
            result[occ_name][year][metric] = val

    return result


def fetch(
    start_year: int = 2020,
    end_year:   int = 2023,
    cache_dir:  str = CACHE_DIR,
    api_key:    str | None = None,
) -> dict:
    """
    Fetch BLS OEWS wage + employment data for tech occupations.
    Cache-first: safe to re-run. Returns structured dict.
    """
    cache_path = os.path.join(cache_dir, f"{start_year}-{end_year}.json")
    if os.path.exists(cache_path):
        print(f"  [bls] cache hit {start_year}-{end_year}")
        with open(cache_path) as f:
            return json.load(f)

    if api_key is None:
        api_key = os.environ.get("BLS_API_KEY", "")
    if not api_key:
        print("  [bls] warn: BLS_API_KEY not set — skipping")
        return {}

    series_ids = _build_all_series()
    print(f"  [bls] querying {len(series_ids)} series for {start_year}-{end_year} ...")
    raw = _query_bls(series_ids, start_year, end_year, api_key)
    print(f"  [bls] received {len(raw)} series back from API")

    structured = _parse_raw(raw)

    os.makedirs(cache_dir, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(structured, f, indent=2)
    print(f"  [bls] saved → {cache_path}")
    return structured


def skills_salary_from_bls(bls_data: dict, year: str) -> dict[str, dict]:
    """
    Derive per-skill salary estimates from BLS occupation data.
    Averages wage percentiles across all occupations that list the skill.
    Returns {skill: {median, p25, p75, p90, n_occupations}}.
    """
    from skills import SKILLS

    skill_wages: dict[str, list[dict]] = {s: [] for s in SKILLS}

    for occ_code, skills in SOC_TO_SKILLS.items():
        occ_name = TECH_OCCUPATIONS.get(occ_code, "")
        occ_data = bls_data.get(occ_name, {}).get(year, {})
        if not occ_data:
            continue
        for skill in skills:
            if skill in skill_wages:
                skill_wages[skill].append(occ_data)

    result: dict[str, dict] = {}
    for skill, rows in skill_wages.items():
        rows = [r for r in rows if r.get("annual_median")]
        if not rows:
            continue
        def _avg(key: str) -> int | None:
            vals = [r[key] for r in rows if r.get(key)]
            return int(sum(vals) / len(vals)) if vals else None
        result[skill] = {
            "median":       _avg("annual_median"),
            "p25":          _avg("annual_p25"),
            "p75":          _avg("annual_p75"),
            "p90":          _avg("annual_p90"),
            "n_occupations": len(rows),
            "source":        "BLS OEWS",
        }

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch BLS OEWS tech occupation data.")
    parser.add_argument("--start", type=int, default=2020)
    parser.add_argument("--end",   type=int, default=2023)
    args = parser.parse_args()

    data = fetch(args.start, args.end)

    if not data:
        print("No data returned — check BLS_API_KEY and network.")
        sys.exit(1)

    print(f"\n{'Occupation':<45} {'Year':<6} {'Median':>10} {'P25':>10} {'P75':>10} {'Empl (k)':>10}")
    print("-" * 95)
    for occ, years in sorted(data.items()):
        for year in sorted(years, reverse=True):
            row = years[year]
            print(
                f"{occ:<45} {year:<6}"
                f" {row.get('annual_median', '—'):>10}"
                f" {row.get('annual_p25', '—'):>10}"
                f" {row.get('annual_p75', '—'):>10}"
                f" {row.get('employment', '—'):>10}"
            )

    print("\n--- Derived skill salaries (most recent year) ---")
    latest_year = str(args.end)
    skill_sal = skills_salary_from_bls(data, latest_year)
    for skill, sal in sorted(skill_sal.items(), key=lambda x: x[1].get("median") or 0, reverse=True):
        print(f"  {skill:<25} median=${sal['median']:,}  p25=${sal['p25']:,}  p75=${sal['p75']:,}")
