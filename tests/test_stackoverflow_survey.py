import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import csv
import io
import json
import pytest
from unittest.mock import patch, MagicMock

from ingest.stackoverflow_survey import fetch, fetch_all, _is_professional, SO_SKILL_NAMES


def test_is_professional_2021_plus():
    assert _is_professional({"MainBranch": "I am a developer by profession"}, "2021") is True
    assert _is_professional({"MainBranch": "I am learning to code"}, "2021") is False


def test_is_professional_pre_2021():
    # 2019 and 2020 also have MainBranch with the "profession" value
    assert _is_professional({"MainBranch": "I am a developer by profession"}, "2020") is True
    assert _is_professional({"MainBranch": "I code primarily as a hobby"}, "2020") is False
    assert _is_professional({}, "2020") is False


def test_so_skill_names_has_no_duplicates():
    from skills import SKILLS
    for skill in SKILLS:
        assert skill in SO_SKILL_NAMES, f"{skill} missing from SO_SKILL_NAMES"


def _make_survey_csv(rows: list[dict], columns: list[str]) -> str:
    """Helper: build a fake survey CSV."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def test_fetch_counts_python_correctly(tmp_path):
    columns = ["MainBranch", "LanguageHaveWorkedWith", "DatabaseHaveWorkedWith",
               "PlatformHaveWorkedWith", "WebframeHaveWorkedWith",
               "MiscTechHaveWorkedWith", "ToolsTechHaveWorkedWith"]
    rows = [
        {"MainBranch": "I am a developer by profession",
         "LanguageHaveWorkedWith": "Python;JavaScript", "DatabaseHaveWorkedWith": "",
         "PlatformHaveWorkedWith": "", "WebframeHaveWorkedWith": "",
         "MiscTechHaveWorkedWith": "", "ToolsTechHaveWorkedWith": ""},
        {"MainBranch": "I am a developer by profession",
         "LanguageHaveWorkedWith": "JavaScript", "DatabaseHaveWorkedWith": "",
         "PlatformHaveWorkedWith": "", "WebframeHaveWorkedWith": "",
         "MiscTechHaveWorkedWith": "", "ToolsTechHaveWorkedWith": ""},
        {"MainBranch": "I am not a developer",
         "LanguageHaveWorkedWith": "Python", "DatabaseHaveWorkedWith": "",
         "PlatformHaveWorkedWith": "", "WebframeHaveWorkedWith": "",
         "MiscTechHaveWorkedWith": "", "ToolsTechHaveWorkedWith": ""},
    ]
    csv_text = _make_survey_csv(rows, columns)

    with patch("ingest.stackoverflow_survey.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.content = csv_text.encode("utf-8")
        mock_resp.raise_for_status = lambda: None
        mock_get.return_value = mock_resp

        result = fetch("2021", cache_dir=str(tmp_path))

    # 2 professional devs, 1 uses Python -> 50.0%
    assert result["Python"] == pytest.approx(50.0, rel=0.01)
    # JAX not in SO survey -> None
    assert result["JAX"] is None


def test_fetch_uses_cache(tmp_path):
    cache = {"Python": 60.0, "JAX": None}
    cache_file = tmp_path / "2022.json"
    cache_file.write_text(json.dumps(cache))
    result = fetch("2022", cache_dir=str(tmp_path))
    assert result["Python"] == 60.0
