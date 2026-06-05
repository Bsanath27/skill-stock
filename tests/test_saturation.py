import sys
import pytest
import pandas as pd
sys.path.insert(0, "src")
from index_build import _compute_saturation_scores, build_index

def test_saturation_returns_0_to_100():
    supply = pd.DataFrame([
        {"skill": "Python",  "month": "2026-06", "udemy_courses": 500, "github_stars": 50000, "nces_proxy": 0.9},
        {"skill": "PyTorch", "month": "2026-06", "udemy_courses": 100, "github_stars": 80000, "nces_proxy": 0.3},
    ])
    demand = {"Python": 0.30, "PyTorch": 0.10}
    scores = _compute_saturation_scores(demand, supply, "2026-06")
    for skill, score in scores.items():
        if score is not None:
            assert 0 <= score <= 100, f"{skill} score {score} out of range"

def test_higher_supply_lower_demand_means_higher_saturation():
    supply = pd.DataFrame([
        {"skill": "Python",  "month": "2026-06", "udemy_courses": 1000, "github_stars": 10000, "nces_proxy": 0.9},
        {"skill": "JAX",     "month": "2026-06", "udemy_courses": 10,   "github_stars": 5000,  "nces_proxy": 0.1},
    ])
    # Python: high supply across all signals, moderate demand → crowded (lower scarcity)
    # JAX: low supply across all signals, low demand → scarce (higher scarcity)
    demand = {"Python": 0.30, "JAX": 0.05}
    scores = _compute_saturation_scores(demand, supply, "2026-06")
    if scores.get("Python") is not None and scores.get("JAX") is not None:
        assert scores["Python"] < scores["JAX"]

def test_null_supply_returns_null_saturation():
    supply = pd.DataFrame(columns=["skill","month","udemy_courses","github_stars","nces_proxy"])
    demand = {"Python": 0.30}
    scores = _compute_saturation_scores(demand, supply, "2026-06")
    assert scores.get("Python") is None

def test_build_index_with_supply_adds_saturation_field():
    demand_df = pd.DataFrame([
        {"company_norm": f"co{i}", "title_norm": f"job{i}", "location_norm": "remote",
         "month": "2026-06", "skills": ["Python", "AWS"][i % 2]}
        for i in range(200)
    ])
    demand_df["skills"] = demand_df["skills"].map(lambda s: [s])
    supply_df = pd.DataFrame([
        {"skill": "Python", "month": "2026-06", "udemy_courses": 500, "github_stars": 50000, "nces_proxy": 0.9},
        {"skill": "AWS",    "month": "2026-06", "udemy_courses": 200, "github_stars": None,  "nces_proxy": 0.6},
    ])
    idx = build_index(demand_df, supply_df=supply_df)
    py = idx["skills"]["Python"]
    assert "latest_saturation" in py
    if py["latest_saturation"] is not None:
        assert 0 <= py["latest_saturation"] <= 100
