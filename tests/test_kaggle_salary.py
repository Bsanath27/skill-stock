import sys, os, csv, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from ingest.kaggle_salary import fetch, SALARY_MIN, SALARY_MAX, MIN_SAMPLE


def _write_csv(path, rows, fieldnames):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def test_fetch_returns_empty_when_files_missing(tmp_path):
    result = fetch(
        postings_path=str(tmp_path / "nope.csv"),
        salaries_path=str(tmp_path / "nope2.csv"),
        cache_path=str(tmp_path / "cache.json"),
    )
    assert result == {}


def test_fetch_computes_percentiles(tmp_path):
    postings_path = str(tmp_path / "postings.csv")
    salaries_path = str(tmp_path / "salaries.csv")
    cache_path    = str(tmp_path / "cache.json")

    postings = [
        {"job_id": str(i), "description": "Python developer needed"}
        for i in range(15)
    ]
    salaries = [
        {"salary_id": str(i), "job_id": str(i),
         "med_salary": "100000", "min_salary": "", "max_salary": "",
         "pay_period": "YEARLY", "currency": "USD", "compensation_type": "BASE_SALARY"}
        for i in range(15)
    ]

    _write_csv(postings_path, postings, ["job_id", "description"])
    _write_csv(salaries_path, salaries,
               ["salary_id", "job_id", "med_salary", "min_salary", "max_salary",
                "pay_period", "currency", "compensation_type"])

    result = fetch(postings_path, salaries_path, cache_path)

    assert "Python" in result
    assert result["Python"]["median"] == 100000
    assert result["Python"]["n"] == 15


def test_fetch_filters_outlier_salaries(tmp_path):
    postings_path = str(tmp_path / "postings.csv")
    salaries_path = str(tmp_path / "salaries.csv")
    cache_path    = str(tmp_path / "cache.json")

    postings = [{"job_id": str(i), "description": "Python engineer"} for i in range(20)]
    salaries = [
        {"salary_id": str(i), "job_id": str(i),
         "med_salary": str(1000 if i < 5 else 600000 if i < 10 else 120000),
         "min_salary": "", "max_salary": "",
         "pay_period": "YEARLY", "currency": "USD", "compensation_type": "BASE_SALARY"}
        for i in range(20)
    ]

    _write_csv(postings_path, postings, ["job_id", "description"])
    _write_csv(salaries_path, salaries,
               ["salary_id", "job_id", "med_salary", "min_salary", "max_salary",
                "pay_period", "currency", "compensation_type"])

    result = fetch(postings_path, salaries_path, cache_path)
    # Only 10 valid salaries (filtered $1k and $600k out), all $120k
    assert "Python" in result
    assert result["Python"]["median"] == 120000
    assert result["Python"]["n"] == 10


def test_fetch_skips_skill_below_min_sample(tmp_path):
    postings_path = str(tmp_path / "postings.csv")
    salaries_path = str(tmp_path / "salaries.csv")
    cache_path    = str(tmp_path / "cache.json")

    # Only 5 rows — below MIN_SAMPLE=10
    postings = [{"job_id": str(i), "description": "Python developer"} for i in range(5)]
    salaries = [
        {"salary_id": str(i), "job_id": str(i),
         "med_salary": "100000", "min_salary": "", "max_salary": "",
         "pay_period": "YEARLY", "currency": "USD", "compensation_type": "BASE_SALARY"}
        for i in range(5)
    ]

    _write_csv(postings_path, postings, ["job_id", "description"])
    _write_csv(salaries_path, salaries,
               ["salary_id", "job_id", "med_salary", "min_salary", "max_salary",
                "pay_period", "currency", "compensation_type"])

    result = fetch(postings_path, salaries_path, cache_path)
    assert "Python" not in result


def test_fetch_uses_cache(tmp_path):
    cache_path = str(tmp_path / "cache.json")
    cached = {"Python": {"p25": 90000, "median": 120000, "p75": 150000, "n": 50}}
    with open(cache_path, "w") as f:
        json.dump(cached, f)
    result = fetch(
        postings_path=str(tmp_path / "nope.csv"),
        salaries_path=str(tmp_path / "nope2.csv"),
        cache_path=cache_path,
    )
    assert result == cached
