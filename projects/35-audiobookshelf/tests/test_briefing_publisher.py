import os
import tempfile
import pytest
import xml.etree.ElementTree as ET
from unittest.mock import patch, MagicMock

# Adjust import path if needed, assuming run from repo root
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import sys, os; sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))); from briefing_publisher import BriefingPublisher

@pytest.fixture
def temp_env():
    with tempfile.TemporaryDirectory() as temp_dir:
        yield temp_dir

@pytest.fixture
def publisher(temp_env):
    return BriefingPublisher(library_dir=temp_env, webhook_url="http://test.webhook")

def test_validate_audio_valid(publisher, temp_env):
    # Create dummy mp3
    test_mp3 = os.path.join(temp_env, "test.mp3")
    with open(test_mp3, "w") as f:
        f.write("dummy audio content")
    assert publisher.validate_audio(test_mp3) is True

def test_validate_audio_invalid_extension(publisher, temp_env):
    # Create dummy txt
    test_txt = os.path.join(temp_env, "test.txt")
    with open(test_txt, "w") as f:
        f.write("dummy text content")
    with pytest.raises(ValueError):
        publisher.validate_audio(test_txt)

def test_validate_audio_not_found(publisher, temp_env):
    with pytest.raises(FileNotFoundError):
        publisher.validate_audio(os.path.join(temp_env, "nonexistent.mp3"))

def test_rss_feed_generation(publisher, temp_env):
    feed_file = os.path.join(temp_env, "feed.xml")
    publisher.create_rss_feed("Test Podcast", feed_file)

    assert os.path.exists(feed_file)
    tree = ET.parse(feed_file)
    root = tree.getroot()
    assert root.tag == "rss"
    channel = root.find("channel")
    assert channel is not None
    assert channel.find("title").text == "Test Podcast"

def test_rss_feed_update(publisher, temp_env):
    feed_file = os.path.join(temp_env, "feed.xml")
    publisher.create_rss_feed("Test Podcast", feed_file)

    item_metadata = {
        'title': 'Test Episode',
        'description': 'Test Description',
        'url': 'http://test.url/audio.mp3',
        'size': 1024
    }

    publisher.update_rss_feed(feed_file, item_metadata)

    tree = ET.parse(feed_file)
    root = tree.getroot()
    channel = root.find("channel")
    item = channel.find("item")
    assert item is not None
    assert item.find("title").text == "Test Episode"
    enclosure = item.find("enclosure")
    assert enclosure is not None
    assert enclosure.get("url") == "http://test.url/audio.mp3"
    assert enclosure.get("length") == "1024"

@patch('urllib.request.urlopen')
def test_publish_workflow(mock_urlopen, publisher, temp_env):
    # Setup mock response for webhook
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response

    # Create dummy audio
    test_audio = os.path.join(temp_env, "briefing.mp3")
    with open(test_audio, "wb") as f:
        f.write(b"dummy audio data")

    metadata = {
        'title': 'Morning News',
        'series': 'Daily Brief',
        'description': 'News for today'
    }

    # Execute publish
    dest_path = publisher.publish_briefing(test_audio, metadata, is_podcast=True)

    # Verify audio copied
    assert os.path.exists(dest_path)
    assert dest_path == os.path.join(publisher.podcasts_dir, "Daily Brief", "briefing.mp3")

    # Verify RSS created/updated
    feed_file = os.path.join(publisher.podcasts_dir, "Daily Brief", "feed.xml")
    assert os.path.exists(feed_file)

    tree = ET.parse(feed_file)
    root = tree.getroot()
    channel = root.find("channel")
    item = channel.find("item")
    assert item is not None
    assert item.find("title").text == "Morning News"

    # Verify webhook called
    mock_urlopen.assert_called_once()

def test_tag_metadata(publisher):
    # Currently a pass-through in implementation, just ensure it doesn't crash
    publisher.tag_metadata("dummy.mp3", {"title": "Test"})
