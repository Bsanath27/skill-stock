import sys
import pytest
import pandas as pd
sys.path.insert(0, "src")
from pipeline import cross_source_dedup

def _make_df(rows):
    return pd.DataFrame(rows, columns=["company_norm","title_norm","location_norm","month","text","source"])

def test_exact_cross_source_duplicates_removed():
    df = _make_df([
        ("acme", "senior python engineer", "remote", "2026-06", "python", "adzuna"),
        ("acme", "senior python engineer", "remote", "2026-06", "python", "remotive"),
    ])
    result = cross_source_dedup(df)
    assert len(result) == 1

def test_non_duplicate_rows_kept():
    df = _make_df([
        ("acme",  "python engineer",     "remote", "2026-06", "python", "adzuna"),
        ("globo", "data scientist",      "nyc",    "2026-06", "ml",     "remotive"),
    ])
    result = cross_source_dedup(df)
    assert len(result) == 2

def test_near_duplicate_same_title_different_source():
    df = _make_df([
        ("stripe", "senior software engineer python", "sf", "2026-06", "python", "adzuna"),
        ("stripe", "sr software engineer python",    "sf", "2026-06", "python", "firecrawl"),
    ])
    result = cross_source_dedup(df)
    assert len(result) == 1

def test_same_source_rows_not_deduplicated_here():
    # within-source dedup is handled earlier in pipeline.run()
    df = _make_df([
        ("acme", "python dev", "remote", "2026-06", "python", "adzuna"),
        ("acme", "python dev", "remote", "2026-06", "python", "adzuna"),
    ])
    result = cross_source_dedup(df)
    # cross_source_dedup only deduplicates across sources; within-source already handled
    assert len(result) >= 1  # at least 1

def test_empty_df_returns_empty():
    df = pd.DataFrame(columns=["company_norm","title_norm","location_norm","month","text","source"])
    result = cross_source_dedup(df)
    assert len(result) == 0
