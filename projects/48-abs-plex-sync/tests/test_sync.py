import pytest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sync_daemon import AudiobookshelfClient, PlexClient, ProgressHarmonizer

@pytest.fixture
def mock_abs_client(mocker):
    client = AudiobookshelfClient("http://fake-abs", "fake_token")
    return client

@pytest.fixture
def mock_plex_client(mocker):
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

def test_sync_dry_run_no_exception(harmonizer, caplog, mocker):
    import logging
    caplog.set_level(logging.INFO)
    harmonizer.dry_run = True

    # Mock network responses so it actually executes the loop
    mocker.patch("requests.get", return_value=mocker.Mock(json=lambda: {"sessions": [{"id": "1", "title": "Dune", "progress": 100, "updatedAt": 100}]}))

    # Also mock Plex API
    plex_mock_response = mocker.Mock()
    plex_mock_response.json.return_value = {"MediaContainer": {"Metadata": [{"ratingKey": "2", "title": "Dune (1965)", "viewOffset": 50, "updatedAt": 50}]}}

    def side_effect(url, **kwargs):
        if "library/metadata" in url:
            return plex_mock_response
        elif "status/sessions" in url:
            return plex_mock_response
        elif "/api/items/" in url and "/play" in url:
            return mocker.Mock(json=lambda: {"progress": 100, "updatedAt": 100})
        elif "/api/items/" in url:
            return mocker.Mock(json=lambda: {"mediaProgress": {"isFinished": False}})
        elif "listening-sessions" in url:
            return mocker.Mock(json=lambda: {"sessions": [{"id": "1", "title": "Dune", "progress": 100, "updatedAt": 100}]})
        return mocker.Mock()

    mocker.patch("requests.get", side_effect=side_effect)

    harmonizer.sync()

    assert "Dry run enabled, no changes will be made." in caplog.text
    assert "Matched 'Dune' with 'Dune (1965)'" in caplog.text
    assert "Syncing Dune progress 100 to Plex" in caplog.text

def test_sync_error_handling(harmonizer, caplog, mocker):
    import logging
    caplog.set_level(logging.ERROR)
    import requests

    mocker.patch("requests.get", side_effect=requests.RequestException("Network Error"))

    harmonizer.sync()
    assert "Failed to fetch sessions" in caplog.text
