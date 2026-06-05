"""NCES IPEDS supply ingest — graduation counts by CIP code, mapped to skills."""
from __future__ import annotations
import os
import sys
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
from skills import SKILLS

# CIP codes relevant to tech skills: 11=CS, 27=Math/Stats, 30.70=Data Science
RELEVANT_CIPS = {"11", "27", "30.70", "14"}  # 14=Engineering

# Which skills proxy to which degree cluster (0.0-1.0 weight)
SKILL_CIP_WEIGHT: dict[str, dict[str, float]] = {
    "Python":       {"11": 0.6, "27": 0.2, "30.70": 0.2},
    "SQL":          {"11": 0.5, "27": 0.3, "30.70": 0.2},
    "R":            {"27": 0.7, "30.70": 0.3},
    "Rust":         {"11": 0.8, "14": 0.2},
    "Scala":        {"11": 0.8, "14": 0.2},
    "PyTorch":      {"11": 0.4, "27": 0.3, "30.70": 0.3},
    "TensorFlow":   {"11": 0.4, "27": 0.3, "30.70": 0.3},
    "scikit-learn": {"11": 0.3, "27": 0.4, "30.70": 0.3},
    "Keras":        {"11": 0.4, "27": 0.3, "30.70": 0.3},
    "JAX":          {"11": 0.4, "27": 0.4, "30.70": 0.2},
    "Pandas":       {"11": 0.5, "27": 0.3, "30.70": 0.2},
    "NumPy":        {"11": 0.4, "27": 0.4, "30.70": 0.2},
    "Spark":        {"11": 0.6, "27": 0.2, "30.70": 0.2},
    "Kafka":        {"11": 0.8, "14": 0.2},
    "Airflow":      {"11": 0.8, "14": 0.2},
    "dbt":          {"11": 0.6, "27": 0.3, "30.70": 0.1},
    "Snowflake":    {"11": 0.7, "27": 0.2, "30.70": 0.1},
    "Databricks":   {"11": 0.5, "27": 0.2, "30.70": 0.3},
    "MLflow":       {"11": 0.4, "27": 0.3, "30.70": 0.3},
    "Weights & Biases": {"11": 0.4, "27": 0.3, "30.70": 0.3},
    "LangChain":    {"11": 0.6, "27": 0.2, "30.70": 0.2},
    "Hugging Face": {"11": 0.5, "27": 0.2, "30.70": 0.3},
    "Transformers": {"11": 0.4, "27": 0.3, "30.70": 0.3},
    "AWS":          {"11": 0.8, "14": 0.2},
    "GCP":          {"11": 0.8, "14": 0.2},
    "Azure":        {"11": 0.8, "14": 0.2},
    "Docker":       {"11": 0.9, "14": 0.1},
    "Kubernetes":   {"11": 0.9, "14": 0.1},
    "Terraform":    {"11": 0.9, "14": 0.1},
    "FastAPI":      {"11": 1.0},
    "React":        {"11": 1.0},
    "TypeScript":   {"11": 1.0},
    "Git":          {"11": 0.9, "14": 0.1},
    "CI/CD":        {"11": 0.9, "14": 0.1},
}

NCES_DIR = Path("data/raw/supply/nces")


def load_latest() -> pd.DataFrame | None:
    """Load most recent NCES CSV. Returns None if no file found."""
    csvs = sorted(NCES_DIR.glob("*.csv"), reverse=True)
    if not csvs:
        print("  [nces] no CSV found in data/raw/supply/nces/ — skipping")
        return None
    path = csvs[0]
    print(f"  [nces] loading {path.name}")
    df = pd.read_csv(path, dtype=str, low_memory=False)
    return df


def compute_grad_proxies(year: int | None = None) -> dict[str, float]:
    """
    Returns {skill: normalised_grad_proxy} where proxy is a weighted
    sum of relevant CIP-code degree counts, normalised to [0,1].
    """
    raw = load_latest()
    if raw is None:
        return {}

    raw.columns = [c.upper() for c in raw.columns]

    if "CIPCODE" not in raw.columns or "CTOTALT" not in raw.columns:
        print("  [nces] unexpected CSV format — expected CIPCODE, CTOTALT columns")
        return {}

    raw["cip_prefix"] = raw["CIPCODE"].str.split(".").str[0]
    raw["cip_2digit"] = raw["CIPCODE"].str[:5]  # e.g. "30.70"
    raw["count"] = pd.to_numeric(raw["CTOTALT"], errors="coerce").fillna(0)

    cip_totals: dict[str, float] = {}
    for prefix in RELEVANT_CIPS:
        if "." in prefix:
            mask = raw["cip_2digit"] == prefix
        else:
            mask = raw["cip_prefix"] == prefix
        cip_totals[prefix] = float(raw[mask]["count"].sum())

    raw_proxies: dict[str, float] = {}
    for skill in SKILLS:
        weights = SKILL_CIP_WEIGHT.get(skill, {"11": 1.0})
        proxy = sum(cip_totals.get(cip, 0) * w for cip, w in weights.items())
        raw_proxies[skill] = proxy

    max_proxy = max(raw_proxies.values()) if raw_proxies else 1.0
    if max_proxy == 0:
        return {s: 0.0 for s in SKILLS}
    return {s: round(v / max_proxy, 6) for s, v in raw_proxies.items()}


def fetch(month: str) -> pd.DataFrame:
    """Return DataFrame with [skill, month, nces_proxy]. Annual data — same value every month in a year."""
    proxies = compute_grad_proxies()
    rows = [{"skill": s, "month": month, "nces_proxy": proxies.get(s)} for s in SKILLS]
    return pd.DataFrame(rows)
