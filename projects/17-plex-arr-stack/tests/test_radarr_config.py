import os
import json
import pytest
from unittest import mock
from io import StringIO
import sys

# Add config directory to path to import radarr_apply_config
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'config')))
import radarr_apply_config

def test_json_loads_correctly():
    config_path = os.path.join(os.path.dirname(__file__), "..", "config", "radarr_custom_formats.json")
    with open(config_path, "r") as f:
        data = json.load(f)
    
    assert isinstance(data, list)
    assert len(data) == 5
    
    names = [cf["name"] for cf in data]
    assert "Hindi Audio" in names
    assert "Dual Audio" in names
    assert "Hindi Dubbed" in names
    assert "English Audio" in names
    assert "Non EN-HI Audio" in names

@mock.patch("radarr_apply_config.requests.get")
@mock.patch("radarr_apply_config.requests.post")
@mock.patch("radarr_apply_config.requests.put")
@mock.patch("radarr_apply_config.os.environ.get")
def test_radarr_apply_config_success(mock_env_get, mock_put, mock_post, mock_get):
    # Mock environment variables
    def env_get_side_effect(key, default=None):
        if key == "RADARR_API_KEY":
            return "test_api_key"
        if key == "RADARR_URL":
            return "http://localhost:7878"
        return default
    mock_env_get.side_effect = env_get_side_effect

    # Mock requests.get
    def get_side_effect(url, headers):
        mock_resp = mock.Mock()
        if url.endswith("/customformat"):
            mock_resp.json.return_value = [
                {"id": 1, "name": "Hindi Audio"} # Mock existing format
            ]
        elif url.endswith("/qualityprofile"):
            mock_resp.json.return_value = [
                {"id": 1, "name": "Any"}
            ]
        return mock_resp
    mock_get.side_effect = get_side_effect

    # Mock requests.post
    mock_post_resp = mock.Mock()
    mock_post_resp.json.return_value = {"id": 2, "name": "Created Format"}
    mock_post.return_value = mock_post_resp

    # Redirect stdout to capture prints
    captured_output = StringIO()
    sys.stdout = captured_output

    radarr_apply_config.main()

    sys.stdout = sys.__stdout__
    output = captured_output.getvalue()

    # Hindi Audio should be updated
    assert "Updating custom format: Hindi Audio (ID: 1)" in output
    assert mock_put.call_count == 1
    
    # Others should be created
    assert "Creating custom format: Dual Audio" in output
    assert "Creating custom format: Hindi Dubbed" in output
    assert "Creating custom format: English Audio" in output
    assert "Creating custom format: Non EN-HI Audio" in output
    assert mock_post.call_count == 4
    
    # Quality profiles should be fetched
    assert "Existing Quality Profiles:" in output
    assert "- Any (ID: 1)" in output

@mock.patch("radarr_apply_config.os.environ.get")
def test_radarr_apply_config_missing_api_key(mock_env_get):
    # Mock environment variables without RADARR_API_KEY
    def env_get_side_effect(key, default=None):
        if key == "RADARR_API_KEY":
            return None
        if key == "RADARR_URL":
            return "http://localhost:7878"
        return default
    mock_env_get.side_effect = env_get_side_effect

    captured_output = StringIO()
    sys.stdout = captured_output

    radarr_apply_config.main()

    sys.stdout = sys.__stdout__
    output = captured_output.getvalue()

    assert "Error: RADARR_API_KEY environment variable is not set." in output
