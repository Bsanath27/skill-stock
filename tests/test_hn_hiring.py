import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from ingest.hn_hiring import _clean_html, _thread_month, _to_df, fetch
from ingest.raw_store import RawStore


def test_clean_html_decodes_entities():
    assert _clean_html("I&#x27;m hiring") == "I'm hiring"


def test_clean_html_strips_tags():
    result = _clean_html("<p>Hello <b>World</b></p>")
    assert "Hello" in result and "World" in result
    assert "<" not in result


def test_thread_month_parses_title():
    assert _thread_month("Ask HN: Who is hiring? (June 2024)", "") == "2024-06"


def test_thread_month_falls_back_to_created_at():
    assert _thread_month("Not a hiring thread", "2024-05-01") == "2024-05"


def test_to_df_returns_empty_with_correct_columns():
    df = _to_df([])
    assert df.empty
    assert set(["company_norm", "title_norm", "location_norm", "month", "text"]).issubset(df.columns)


def test_to_df_populates_rows():
    records = [{"text": "Stripe | Remote | Python Engineer\nWe need Python.", "month": "2024-06"}]
    df = _to_df(records)
    assert len(df) == 1
    assert df.iloc[0]["month"] == "2024-06"
    assert "stripe" in df.iloc[0]["title_norm"]


def test_fetch_uses_cache(tmp_path):
    store = RawStore(str(tmp_path))
    records = [{"text": "Acme | NYC | Engineer\nPython required.", "month": "2024-06"}]
    store.save("demand/hn", "2024-06", records)
    df = fetch("2024-06", store)
    assert len(df) == 1
    assert df.iloc[0]["month"] == "2024-06"
