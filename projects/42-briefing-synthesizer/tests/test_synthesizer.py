import os
import sys
import unittest.mock
import pytest
from unittest.mock import patch, MagicMock

# Add the project directory to sys.path to allow importing despite invalid python module names
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from synthesizer_daemon import (
    TextPreProcessor,
    TTSBridge,
    ID3Tagger,
    AudiobookshelfClient,
    main
)
import requests

def test_text_pre_processor():
    processor = TextPreProcessor()
    raw_md = "# ☀️ Morning Briefing\n**Market Sentiment Indicator**: +0.15\n## 📰 Top News Highlights\n1. **News Item 1**\n   Description 1..."

    cleaned = processor.clean_markdown(raw_md)

    assert "#" not in cleaned
    assert "**" not in cleaned
    assert "☀️ Morning Briefing" in cleaned
    assert "Market Sentiment Indicator: +0.15" in cleaned
    assert "Top News Highlights" in cleaned
    assert "News Item 1" in cleaned

    chunks = processor.chunk_text(cleaned, max_length=50)
    assert len(chunks) > 0

@patch('builtins.__import__')
def test_tts_bridge_mock(mock_import, tmpdir):
    def side_effect(name, *args, **kwargs):
        if name == 'pyttsx3':
            raise ImportError("mock import error")
        return __import__(name, *args, **kwargs)
    mock_import.side_effect = side_effect

    bridge = TTSBridge(output_dir=str(tmpdir))
    assert bridge.engine_type == "mock"

    out_file = bridge.generate_audio("Hello world", "test.mp3")
    assert os.path.exists(out_file)
    with open(out_file, 'rb') as f:
        content = f.read()
        assert b"Mock audio content" in content

@patch('synthesizer_daemon.ID3')
def test_id3_tagging(mock_id3, tmpdir):
    tagger = ID3Tagger()
    dummy_file = os.path.join(str(tmpdir), "test.mp3")
    with open(dummy_file, "w") as f:
        f.write("dummy")

    mock_audio = MagicMock()
    mock_id3.return_value = mock_audio

    tagger.tag_file(dummy_file, title="Test Title", date="2023-10-27")

    assert mock_id3.called
    assert mock_audio.add.called
    assert mock_audio.save.called

@patch('synthesizer_daemon.requests')
def test_audiobookshelf_api_auth_upload_rescan(mock_requests):
    client = AudiobookshelfClient()

    # Test Login
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"user": {"token": "test-token"}}
    mock_requests.post.return_value = mock_resp

    assert client.login("admin", "password") == True
    assert client.token == "test-token"

    # Test Get Library ID
    mock_resp_lib = MagicMock()
    mock_resp_lib.json.return_value = {"libraries": [{"name": "Podcasts", "id": "lib-123"}]}
    mock_requests.get.return_value = mock_resp_lib

    assert client.get_library_id("Podcasts") == "lib-123"
    assert client.library_id == "lib-123"

    # Test Upload
    mock_resp_upload = MagicMock()
    mock_requests.post.return_value = mock_resp_upload

    with patch('builtins.open', unittest.mock.mock_open(read_data=b'data')):
        assert client.upload_audio("test.mp3", "lib-123") == True

    # Test Rescan
    mock_resp_rescan = MagicMock()
    mock_requests.post.return_value = mock_resp_rescan

    assert client.trigger_rescan("lib-123") == True

    # Test Upload Error
    mock_requests.RequestException = requests.RequestException
    mock_requests.post.side_effect = requests.RequestException("Upload failed")
    with patch('builtins.open', unittest.mock.mock_open(read_data=b'data')):
        assert client.upload_audio("test.mp3", "lib-123") == False

@patch('synthesizer_daemon.sys.exit')
@patch('synthesizer_daemon.logger')
def test_cli_parsing_no_file(mock_logger, mock_exit):
    with patch.object(sys, 'argv', ['synthesizer_daemon.py']):
        try:
            main()
        except Exception:
            pass
        mock_logger.error.assert_called_with("Must provide --briefing-file")
        mock_exit.assert_called_with(1)
