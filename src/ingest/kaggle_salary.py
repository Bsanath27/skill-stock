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

    print(f"  [salary] {len(result)} skills with salary data (n>={MIN_SAMPLE})")
    return result
