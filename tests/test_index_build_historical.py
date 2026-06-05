import sys
sys.path.insert(0, "src")

import pandas as pd
import pytest
from index_build import build_index


def _make_df(month: str, n: int = 60, skill: str = "Python") -> pd.DataFrame:
    """Make a minimal demand DataFrame with n rows for one month and one skill."""
    rows = [
        {"company_norm": f"co{i}", "title_norm": f"job{i}", "location_norm": "remote",
         "month": month, "skills": [skill]}
        for i in range(n)
    ]
    return pd.DataFrame(rows)


def test_build_index_without_hist_backward_compatible():
    """Existing call signature still works."""
    df = _make_df("2026-06")
    idx = build_index(df)
    assert "Python" in idx["skills"]
    py = idx["skills"]["Python"]
    assert "series" in py
    assert "so_series" in py
    assert "salary" in py
    assert py["so_series"] == []
    assert py["salary"] is None


def test_build_index_merges_hist_and_live_series():
    """Historical + live series are concatenated and sorted by month."""
    hist_df = _make_df("2020-06")
    live_df = _make_df("2026-06")
    idx = build_index(live_df, hist_df=hist_df)
    py = idx["skills"]["Python"]
    months = [p["month"] for p in py["series"]]
    assert "2020-06" in months
    assert "2026-06" in months
    assert months == sorted(months)


def test_source_boundary_nulls_mom_pct():
    """First live data point has mom_pct=None when hist is also present."""
    hist_df = _make_df("2020-06")
    live_df = _make_df("2026-06")
    idx = build_index(live_df, hist_df=hist_df)
    py = idx["skills"]["Python"]
    live_point = next(p for p in py["series"] if p["month"] == "2026-06")
    assert live_point["mom_pct"] is None


def test_so_data_attached_to_skill():
    """so_series from so_data is present in output skill data."""
    live_df = _make_df("2026-06")
    so_data = {"Python": [{"year": "2023", "pct": 49.3}, {"year": "2024", "pct": 51.0}]}
    idx = build_index(live_df, so_data=so_data)
    py = idx["skills"]["Python"]
    assert py["so_series"] == [{"year": "2023", "pct": 49.3}, {"year": "2024", "pct": 51.0}]


def test_salary_data_attached_to_skill():
    """salary from salary_data appears in output skill data."""
    live_df = _make_df("2026-06")
    salary_data = {"Python": {"p25": 110000, "median": 145000, "p75": 185000, "n": 342}}
    idx = build_index(live_df, salary_data=salary_data)
    py = idx["skills"]["Python"]
    assert py["salary"]["median"] == 145000


def test_total_postings_includes_hist():
    """total_postings counts both hist and live rows."""
    hist_df = _make_df("2020-06", n=60)
    live_df = _make_df("2026-06", n=60)
    idx = build_index(live_df, hist_df=hist_df)
    assert idx["total_postings"] == 120
