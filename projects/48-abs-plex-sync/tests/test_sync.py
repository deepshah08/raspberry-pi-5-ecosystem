import pytest
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sync_daemon import AudiobookshelfClient, PlexClient, ProgressHarmonizer

@pytest.fixture
def mock_abs_client():
    client = AudiobookshelfClient("http://fake-abs", "fake_token")
    return client

@pytest.fixture
def mock_plex_client():
    client = PlexClient("http://fake-plex", "fake_token")
    return client

@pytest.fixture
def harmonizer(mock_abs_client, mock_plex_client):
    return ProgressHarmonizer(mock_abs_client, mock_plex_client)

def test_initialization(harmonizer):
    assert harmonizer.abs_client is not None
    assert harmonizer.plex_client is not None
    assert harmonizer.dry_run is False
    assert harmonizer.force_direction is None

def test_fuzzy_match_title(harmonizer):
    assert harmonizer.fuzzy_match_title("The Lord of the Rings", "Lord of the Rings") is True
    assert harmonizer.fuzzy_match_title("Dune (1965)", "Dune") is True
    assert harmonizer.fuzzy_match_title("Harry Potter", "Percy Jackson") is False
    assert harmonizer.fuzzy_match_title("  Foundation  ", "Foundation") is True

def test_resolve_conflict_abs_wins(harmonizer):
    abs_progress = {"updatedAt": 1600000100}
    plex_progress = {"updatedAt": 1600000000}
    direction = harmonizer.resolve_conflict(abs_progress, plex_progress)
    assert direction == "abs-to-plex"

def test_resolve_conflict_plex_wins(harmonizer):
    abs_progress = {"updatedAt": 1600000000}
    plex_progress = {"updatedAt": 1600000100}
    direction = harmonizer.resolve_conflict(abs_progress, plex_progress)
    assert direction == "plex-to-abs"

def test_resolve_conflict_force_direction(harmonizer):
    harmonizer.force_direction = "plex-to-abs"
    abs_progress = {"updatedAt": 1600000100}
    plex_progress = {"updatedAt": 1600000000}
    direction = harmonizer.resolve_conflict(abs_progress, plex_progress)
    assert direction == "plex-to-abs"

def test_sync_dry_run_no_exception(harmonizer, caplog):
    import logging
    caplog.set_level(logging.INFO)
    harmonizer.dry_run = True

    plex_mock_response = MagicMock()
    plex_mock_response.json.return_value = {"MediaContainer": {"Metadata": [{"ratingKey": "2", "title": "Dune (1965)", "viewOffset": 50, "updatedAt": 50}]}}

    def side_effect(url, **kwargs):
        if "library/metadata" in url:
            return plex_mock_response
        elif "status/sessions" in url:
            return plex_mock_response
        elif "/api/items/" in url and "/play" in url:
            m = MagicMock()
            m.json.return_value = {"progress": 100, "updatedAt": 100}
            return m
        elif "/api/items/" in url:
            m = MagicMock()
            m.json.return_value = {"mediaProgress": {"isFinished": False}}
            return m
        elif "listening-sessions" in url:
            m = MagicMock()
            m.json.return_value = {"sessions": [{"id": "1", "title": "Dune", "progress": 100, "updatedAt": 100}]}
            return m
        return MagicMock()

    with patch("requests.get", side_effect=side_effect):
        harmonizer.sync()

    assert "Dry run enabled, no changes will be made." in caplog.text
    assert "Matched 'Dune' with 'Dune (1965)'" in caplog.text
    assert "Syncing Dune progress 100 to Plex" in caplog.text

def test_sync_error_handling(harmonizer, caplog):
    import logging
    caplog.set_level(logging.ERROR)
    import requests

    with patch("requests.get", side_effect=requests.RequestException("Network Error")):
        harmonizer.sync()
    assert "Failed to fetch sessions" in caplog.text
