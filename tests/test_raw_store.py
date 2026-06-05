import json
import sys
import pytest
sys.path.insert(0, "src")
from ingest.raw_store import RawStore

def test_exists_false_on_empty(tmp_path):
    store = RawStore(str(tmp_path))
    assert not store.exists("adzuna", "2026-06")

def test_save_then_load_roundtrip(tmp_path):
    store = RawStore(str(tmp_path))
    data = [{"job_id": "1", "title": "ML Engineer"}]
    store.save("adzuna", "2026-06", data)
    assert store.exists("adzuna", "2026-06")
    loaded = store.load("adzuna", "2026-06")
    assert loaded == data

def test_load_returns_none_when_missing(tmp_path):
    store = RawStore(str(tmp_path))
    assert store.load("adzuna", "2026-06") is None

def test_save_creates_nested_dirs(tmp_path):
    store = RawStore(str(tmp_path))
    store.save("firecrawl/demand", "2026-06/stripe", {"results": []})
    assert store.exists("firecrawl/demand", "2026-06/stripe")

def test_path_is_json(tmp_path):
    store = RawStore(str(tmp_path))
    p = store.path("adzuna", "2026-06")
    assert str(p).endswith(".json")
