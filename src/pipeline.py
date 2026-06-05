"""
pipeline.py — clean, dedup, and skill-match job postings.

Reusable functions: Phase 2 (Adzuna) feeds the same interface.
Input:  raw DataFrame with columns [job_id, company, title, location, month, text]
Output: deduplicated DataFrame with a skills column (list of matched canonical names)
"""

from __future__ import annotations

import hashlib
import re
from typing import Optional

import pandas as pd

try:
    from rapidfuzz import fuzz
    _HAVE_RAPIDFUZZ = True
except ImportError:
    _HAVE_RAPIDFUZZ = False

from skills import SKILL_PATTERNS, SKILLS


# ── Constants ────────────────────────────────────────────────────────────────

NEAR_DUP_THRESHOLD = 0.80   # Jaccard threshold for title near-dup collapse
RAPIDFUZZ_THRESHOLD = 82    # token_set_ratio threshold if rapidfuzz available


# ── Field normalisation ───────────────────────────────────────────────────────

def normalise_text(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", str(s).lower().strip())


def parse_month(raw_date) -> Optional[str]:
    """Return 'YYYY-MM' or None. Accepts timestamps, ISO strings, or epoch ints."""
    if pd.isna(raw_date):
        return None
    try:
        ts = pd.to_datetime(raw_date, unit="ms", errors="ignore")
        if pd.isna(ts):
            ts = pd.to_datetime(raw_date, errors="coerce")
        if pd.isna(ts):
            return None
        return ts.strftime("%Y-%m")
    except Exception:
        return None


# ── Deduplication ─────────────────────────────────────────────────────────────

def _canonical_key(row: pd.Series) -> str:
    parts = "|".join([
        str(row.get("company_norm", "")),
        str(row.get("title_norm", "")),
        str(row.get("location_norm", "")),
        str(row.get("month", "")),
    ])
    return hashlib.md5(parts.encode()).hexdigest()


def _jaccard(a: str, b: str) -> float:
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _similar_title(a: str, b: str) -> bool:
    if _HAVE_RAPIDFUZZ:
        return fuzz.token_set_ratio(a, b) >= RAPIDFUZZ_THRESHOLD
    return _jaccard(a, b) >= NEAR_DUP_THRESHOLD


def exact_dedup(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows with identical (company_norm, title_norm, location_norm, month)."""
    df["_key"] = df.apply(_canonical_key, axis=1)
    df = df.drop_duplicates(subset="_key").drop(columns="_key")
    return df.reset_index(drop=True)


def near_dup_dedup(df: pd.DataFrame) -> pd.DataFrame:
    """
    Within each (company_norm, month) group collapse near-duplicate titles.
    Keeps the first occurrence; lightweight — O(n²) per group but groups are small.
    """
    keep_flags = [True] * len(df)
    grouped = df.groupby(["company_norm", "month"], sort=False)

    for _, grp in grouped:
        idxs = grp.index.tolist()
        titles = grp["title_norm"].tolist()
        for i in range(len(idxs)):
            if not keep_flags[idxs[i]]:
                continue
            for j in range(i + 1, len(idxs)):
                if not keep_flags[idxs[j]]:
                    continue
                if _similar_title(titles[i], titles[j]):
                    keep_flags[idxs[j]] = False

    return df[keep_flags].reset_index(drop=True)


# ── Skill extraction ──────────────────────────────────────────────────────────

def extract_skills(text: str) -> list[str]:
    """Return sorted list of canonical skill names found in text (word-boundary match)."""
    if not text:
        return []
    found = [skill for skill, pat in SKILL_PATTERNS.items() if pat.search(text)]
    return sorted(found)


def add_skills_column(df: pd.DataFrame, text_col: str = "text") -> pd.DataFrame:
    """Add a 'skills' column (list) after dedup."""
    df["skills"] = df[text_col].map(extract_skills)
    return df


# ── LinkedIn Kaggle loader ────────────────────────────────────────────────────

def load_linkedin(postings_path: str, skills_path: str | None = None) -> pd.DataFrame:
    """
    Load the LinkedIn Job Postings Kaggle dataset.
    postings_path: path to job_postings.csv
    skills_path:   optional path to job_skills.csv (will merge skill names into text)
    """
    df = pd.read_csv(postings_path, low_memory=False)

    # Detect date column (dataset has several candidates)
    date_col = next(
        (c for c in ["original_listed_time", "listed_time", "posting_date", "scraped_at"]
         if c in df.columns),
        None,
    )
    if date_col is None:
        raise ValueError(f"No date column found. Columns: {df.columns.tolist()}")

    # Build normalised fields
    df["month"] = df[date_col].map(parse_month)
    df = df.dropna(subset=["month"])

    df["company_norm"] = df.get("company_id", df.get("company", "")).astype(str).map(normalise_text)
    df["title_norm"] = df.get("title", "").astype(str).map(normalise_text)
    df["location_norm"] = df.get("location", "").astype(str).map(normalise_text)

    # Combine text fields for skill matching
    text_parts = []
    for col in ["description", "skills_desc", "title"]:
        if col in df.columns:
            text_parts.append(df[col].fillna("").astype(str))
    df["text"] = pd.concat(text_parts, axis=1).apply(lambda r: " ".join(r), axis=1)

    # Optionally append explicit skill names from job_skills.csv
    if skills_path:
        try:
            sk = pd.read_csv(skills_path, low_memory=False)
            # skills.csv may map skill_abr -> skill_name
            skills_meta_path = skills_path.replace("job_skills", "skills")
            try:
                sk_meta = pd.read_csv(skills_meta_path, low_memory=False)
                sk = sk.merge(sk_meta, on="skill_abr", how="left")
                sk["skill_name"] = sk["skill_name"].fillna(sk["skill_abr"])
            except FileNotFoundError:
                if "skill_name" not in sk.columns:
                    sk["skill_name"] = sk.get("skill_abr", "")

            skill_text = (
                sk.groupby("job_id")["skill_name"]
                .apply(lambda x: " ".join(x.dropna()))
                .reset_index()
                .rename(columns={"skill_name": "_skill_text"})
            )
            if "job_id" in df.columns:
                df = df.merge(skill_text, on="job_id", how="left")
                df["text"] = df["text"] + " " + df["_skill_text"].fillna("")
                df = df.drop(columns=["_skill_text"])
        except FileNotFoundError:
            pass

    return df[["company_norm", "title_norm", "location_norm", "month", "text"]].copy()


# ── Main pipeline entry point ─────────────────────────────────────────────────

def run(raw_df: pd.DataFrame) -> pd.DataFrame:
    """
    Full pipeline: normalise → exact dedup → near-dup collapse → skill extract.
    Input must already have [company_norm, title_norm, location_norm, month, text].
    """
    print(f"  Raw rows:        {len(raw_df):,}")
    df = exact_dedup(raw_df)
    print(f"  After exact-dup: {len(df):,}")
    df = near_dup_dedup(df)
    print(f"  After near-dup:  {len(df):,}")
    df = add_skills_column(df)
    return df
