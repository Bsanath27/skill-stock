"""Canonical skill list. Edit SKILLS to change coverage."""

SKILLS = [
    # Languages & core data
    "Python", "SQL", "R", "Rust", "Scala",
    # ML frameworks
    "PyTorch", "TensorFlow", "scikit-learn", "Keras", "JAX",
    # Data ecosystem
    "Pandas", "NumPy", "Spark", "Kafka", "Airflow", "dbt", "Snowflake", "Databricks",
    # MLOps / LLMOps
    "MLflow", "Weights & Biases", "LangChain", "Hugging Face", "Transformers",
    # Cloud & infra
    "AWS", "GCP", "Azure", "Docker", "Kubernetes", "Terraform",
    # Web / API
    "FastAPI", "React", "TypeScript",
    # Dev tooling
    "Git", "CI/CD",
]

# Word-boundary patterns for each skill (pre-compiled on import)
import re

_ALIASES: dict[str, list[str]] = {
    "Weights & Biases": ["Weights & Biases", "wandb", "W&B"],
    "Hugging Face": ["Hugging Face", "HuggingFace"],
    "scikit-learn": ["scikit-learn", "sklearn"],
    "CI/CD": ["CI/CD", "CI CD", "continuous integration", "continuous delivery"],
    "Databricks": ["Databricks", "Databrick"],
}

SKILL_PATTERNS: dict[str, re.Pattern] = {}
for skill in SKILLS:
    aliases = _ALIASES.get(skill, [skill])
    pattern_parts = [re.escape(a) for a in aliases]
    SKILL_PATTERNS[skill] = re.compile(
        r"(?i)\b(?:" + "|".join(pattern_parts) + r")\b"
    )
