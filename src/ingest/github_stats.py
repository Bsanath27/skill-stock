"""GitHub supply ingest — star/fork deltas for canonical repos per skill."""
from __future__ import annotations
import os
import sys
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
import pandas as pd

from ingest.raw_store import RawStore
from skills import SKILLS

# One canonical repo per skill. None = no repo proxy for this skill.
SKILL_REPOS: dict[str, str | None] = {
    "Python":           "python/cpython",
    "SQL":              None,
    "R":                "wch/r-source",
    "Rust":             "rust-lang/rust",
    "Scala":            "scala/scala",
    "PyTorch":          "pytorch/pytorch",
    "TensorFlow":       "tensorflow/tensorflow",
    "scikit-learn":     "scikit-learn/scikit-learn",
    "Keras":            "keras-team/keras",
    "JAX":              "google/jax",
    "Pandas":           "pandas-dev/pandas",
    "NumPy":            "numpy/numpy",
    "Spark":            "apache/spark",
    "Kafka":            "apache/kafka",
    "Airflow":          "apache/airflow",
    "dbt":              "dbt-labs/dbt-core",
    "Snowflake":        None,
    "Databricks":       None,
    "MLflow":           "mlflow/mlflow",
    "Weights & Biases": "wandb/wandb",
    "LangChain":        "langchain-ai/langchain",
    "Hugging Face":     "huggingface/transformers",
    "Transformers":     "huggingface/transformers",
    "AWS":              None,
    "GCP":              None,
    "Azure":            None,
    "Docker":           "moby/moby",
    "Kubernetes":       "kubernetes/kubernetes",
    "Terraform":        "hashicorp/terraform",
    "FastAPI":          "fastapi/fastapi",
    "React":            "facebook/react",
    "TypeScript":       "microsoft/TypeScript",
    "Git":              None,
    "CI/CD":            None,
}

SLEEP = 0.2
GH_API = "https://api.github.com/repos/{repo}"


def fetch(month: str, store: RawStore, token: str | None = None) -> pd.DataFrame:
    """Return DataFrame with [skill, month, github_stars, github_forks]."""
    token = token or os.environ.get("GITHUB_TOKEN")
    headers = {"Authorization": f"token {token}"} if token else {}

    cached = store.load("supply/github", month)
    if cached is not None:
        print(f"  [github] cache hit for {month}")
        return pd.DataFrame(cached)

    rows = []
    for skill in SKILLS:
        repo = SKILL_REPOS.get(skill)
        if not repo:
            rows.append({"skill": skill, "month": month, "github_stars": None, "github_forks": None})
            continue
        try:
            resp = requests.get(GH_API.format(repo=repo), headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            rows.append({
                "skill":         skill,
                "month":         month,
                "github_stars":  data.get("stargazers_count"),
                "github_forks":  data.get("forks_count"),
            })
            print(f"  [github] {skill}: ★{data.get('stargazers_count', 0):,}")
        except Exception as e:
            print(f"  [github] warn: {skill}/{repo}: {e}")
            rows.append({"skill": skill, "month": month, "github_stars": None, "github_forks": None})
        time.sleep(SLEEP)

    store.save("supply/github", month, rows)
    return pd.DataFrame(rows)
