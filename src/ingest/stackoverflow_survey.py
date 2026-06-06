"""src/ingest/stackoverflow_survey.py — Stack Overflow Developer Survey supply signal."""
from __future__ import annotations
import csv
import io
import json
import os
import sys
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests

from skills import SKILLS

# 2025 survey has very long free-text fields
csv.field_size_limit(10_000_000)

# Data moved from ZIP downloads to the StackExchange/Survey GitHub repo
SO_SURVEY_URLS: dict[str, str] = {
    "2019": "https://github.com/StackExchange/Survey/raw/refs/heads/main/packages/archive/2019/results.csv",
    "2020": "https://github.com/StackExchange/Survey/raw/refs/heads/main/packages/archive/2020/results.csv",
    "2021": "https://github.com/StackExchange/Survey/raw/refs/heads/main/packages/archive/2021/results.csv",
    "2022": "https://github.com/StackExchange/Survey/raw/refs/heads/main/packages/archive/2022/results.csv",
    "2023": "https://github.com/StackExchange/Survey/raw/refs/heads/main/packages/archive/2023/results.csv",
    "2024": "https://github.com/StackExchange/Survey/raw/refs/heads/main/packages/archive/2024/results.csv",
    "2025": "https://github.com/StackExchange/Survey/raw/refs/heads/main/packages/archive/2025/results.csv",
}

YEAR_TECH_COLS: dict[str, list[str]] = {
    "2019": ["LanguageWorkedWith", "DatabaseWorkedWith", "PlatformWorkedWith", "WebframeWorkedWith", "MiscTechWorkedWith"],
    "2020": ["LanguageWorkedWith", "DatabaseWorkedWith", "PlatformWorkedWith", "WebframeWorkedWith", "MiscTechWorkedWith"],
    "2021": ["LanguageHaveWorkedWith", "DatabaseHaveWorkedWith", "PlatformHaveWorkedWith", "WebframeHaveWorkedWith", "MiscTechHaveWorkedWith", "ToolsTechHaveWorkedWith"],
    "2022": ["LanguageHaveWorkedWith", "DatabaseHaveWorkedWith", "PlatformHaveWorkedWith", "WebframeHaveWorkedWith", "MiscTechHaveWorkedWith", "ToolsTechHaveWorkedWith"],
    "2023": ["LanguageHaveWorkedWith", "DatabaseHaveWorkedWith", "PlatformHaveWorkedWith", "WebframeHaveWorkedWith", "MiscTechHaveWorkedWith", "ToolsTechHaveWorkedWith"],
    "2024": ["LanguageHaveWorkedWith", "DatabaseHaveWorkedWith", "PlatformHaveWorkedWith", "WebframeHaveWorkedWith", "MiscTechHaveWorkedWith", "ToolsTechHaveWorkedWith"],
    "2025": ["LanguageHaveWorkedWith", "DatabaseHaveWorkedWith", "PlatformHaveWorkedWith", "WebframeHaveWorkedWith", "MiscTechHaveWorkedWith", "ToolsTechHaveWorkedWith"],
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
    # All years 2019+ have MainBranch with "I am a developer by profession"
    return "profession" in row.get("MainBranch", "").lower()


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
        resp = requests.get(url, timeout=120, allow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [so] warn: could not download {year}: {e}")
        return {skill: None for skill in SKILLS}

    tech_cols = YEAR_TECH_COLS.get(year, [])
    total = 0
    skill_counts: dict[str, int] = {s: 0 for s in SKILLS}

    reader = csv.DictReader(io.StringIO(resp.content.decode("utf-8", errors="replace")))
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
        skill: (
            round(skill_counts[skill] / total * 100, 2)
            if total > 0 and SO_SKILL_NAMES.get(skill)
            else None
        )
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
