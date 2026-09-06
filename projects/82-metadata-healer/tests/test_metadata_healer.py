import sys
from pathlib import Path

# Required to ensure standalone test execution per requirements
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
from unittest.mock import patch, MagicMock
import pytest
import responses

from metadata_healer import MediaAuditor, PlexReconciler, HealingPlanner, main

@pytest.fixture
def mocked_responses():
    with responses.RequestsMock() as rsps:
        yield rsps

def test_media_auditor_radarr(mocked_responses):
    mocked_responses.add(
        responses.GET,
        "http://radarr/api/v3/movie",
        json=[
            {"id": 1, "title": "Good Movie", "hasFile": True, "monitored": True, "tmdbId": 123},
            {"id": 2, "title": "Missing File Movie", "hasFile": False, "monitored": True, "tmdbId": 456},
            {"id": 3, "title": "Unmonitored Missing ID", "hasFile": True, "monitored": False, "tmdbId": 0},
        ],
        status=200
    )

    auditor = MediaAuditor(radarr_url="http://radarr", radarr_key="key")
    items = auditor.audit_radarr()
    issues = [i for i in items if i.get("issues")]

    assert len(items) == 3
    assert len(issues) == 2
    assert issues[0]["title"] == "Missing File Movie"
    assert "missing_file" in issues[0]["issues"]
    assert issues[1]["title"] == "Unmonitored Missing ID"
    assert "unmonitored" in issues[1]["issues"]
    assert "missing_tmdb_id" in issues[1]["issues"]

def test_media_auditor_sonarr(mocked_responses):
    mocked_responses.add(
        responses.GET,
        "http://sonarr/api/v3/series",
        json=[
            {"id": 1, "title": "Good Show", "monitored": True, "tvdbId": 123, "statistics": {"episodeCount": 10, "episodeFileCount": 10}},
            {"id": 2, "title": "Missing Episodes Show", "monitored": True, "tvdbId": 456, "statistics": {"episodeCount": 10, "episodeFileCount": 8}},
            {"id": 3, "title": "Unmonitored Show", "monitored": False, "tvdbId": 789, "statistics": {"episodeCount": 10, "episodeFileCount": 10}},
        ],
        status=200
    )

    auditor = MediaAuditor(sonarr_url="http://sonarr", sonarr_key="key")
    items = auditor.audit_sonarr()
    issues = [i for i in items if i.get("issues")]

    assert len(items) == 3
    assert len(issues) == 2
    assert issues[0]["title"] == "Missing Episodes Show"
    assert "missing_file" in issues[0]["issues"]
    assert issues[1]["title"] == "Unmonitored Show"
    assert "unmonitored" in issues[1]["issues"]

def test_plex_reconciler(mocked_responses):
    mocked_responses.add(
        responses.GET,
        "http://plex/library/sections",
        json={"MediaContainer": {"Directory": [{"key": "1"}, {"key": "2"}]}},
        status=200
    )
    mocked_responses.add(
        responses.GET,
        "http://plex/library/sections/1/all",
        json={"MediaContainer": {"Metadata": [{"title": "Indexed Movie"}]}},
        status=200
    )
    mocked_responses.add(
        responses.GET,
        "http://plex/library/sections/2/all",
        json={"MediaContainer": {"Metadata": [{"title": "Indexed Show"}]}},
        status=200
    )

    reconciler = PlexReconciler(plex_url="http://plex", plex_token="token")
    arr_items = [
        {"id": 1, "title": "Indexed Movie", "type": "movie", "issues": ["unmonitored"]},
        {"id": 2, "title": "Unindexed Movie", "type": "movie", "issues": ["unmonitored"]},
        {"id": 3, "title": "Missing File Movie", "type": "movie", "issues": ["missing_file"]}, # Should be skipped
    ]

    unindexed = reconciler.reconcile(arr_items)

    assert len(unindexed) == 1
    assert unindexed[0]["title"] == "Unindexed Movie"

def test_healing_planner():
    audit_issues = [
        {"id": 1, "type": "movie", "issues": ["missing_tmdb_id"]},
        {"id": 2, "type": "movie", "issues": ["missing_file"]},
        {"id": 3, "type": "series", "issues": ["missing_file", "unmonitored"]}, # shouldn't trigger search if unmonitored
    ]
    unindexed_issues = [
        {"id": 4, "title": "Unindexed Movie", "type": "movie"}
    ]

    planner = HealingPlanner()
    plan = planner.generate_plan(audit_issues, unindexed_issues)

    assert len(plan) == 3
    assert plan[0]["action"] == "refresh_metadata"
    assert plan[0]["id"] == 1

    assert plan[1]["action"] == "trigger_search"
    assert plan[1]["id"] == 2

    assert plan[2]["action"] == "rescan_item"
    assert plan[2]["id"] == 4

@patch("sys.argv", ["metadata_healer.py", "--audit-now", "--dry-run", "--json"])
@patch("metadata_healer.MediaAuditor.audit_radarr")
@patch("metadata_healer.MediaAuditor.audit_sonarr")
@patch("metadata_healer.PlexReconciler.reconcile")
def test_main_cli_json_dry_run(mock_reconcile, mock_audit_sonarr, mock_audit_radarr, capsys):
    mock_audit_radarr.return_value = [{"id": 1, "title": "Movie 1", "type": "movie", "issues": ["missing_file"]}]
    mock_audit_sonarr.return_value = []
    mock_reconcile.return_value = [{"id": 1, "title": "Movie 1", "type": "movie", "issue": "unindexed_in_plex"}]

    main()

    captured = capsys.readouterr()
    output = json.loads(captured.out)

    assert len(output["audit_issues"]) == 1
    assert len(output["unindexed_issues"]) == 1
    assert len(output["healing_plan"]) > 0

@patch("sys.argv", ["metadata_healer.py"])
def test_main_cli_no_args(capsys):
    with pytest.raises(SystemExit):
        main()
    captured = capsys.readouterr()
    assert "usage:" in captured.out
