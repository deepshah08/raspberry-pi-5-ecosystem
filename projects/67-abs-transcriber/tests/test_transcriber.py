import sys
import os
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

# Include the parent directory to allow standalone execution
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from podcast_transcriber import FeedScraper, Downloader, Transcriber, Episode

# Mock XML content
MOCK_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Podcast</title>
    <item>
      <title>Episode 1: The Beginning</title>
      <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
      <enclosure url="http://example.com/ep1.mp3" type="audio/mpeg"/>
    </item>
    <item>
      <title>Episode 2: The Middle</title>
      <pubDate>Tue, 02 Jan 2024 12:00:00 GMT</pubDate>
      <enclosure url="http://example.com/ep2.m4a" type="audio/mp4"/>
    </item>
  </channel>
</rss>
"""

@pytest.fixture
def mock_output_dir(tmp_path):
    return tmp_path

def test_feed_scraper_parse():
    scraper = FeedScraper("http://mock.feed")
    episodes = scraper.parse_xml(MOCK_RSS)
    
    assert len(episodes) == 2
    assert episodes[0].title == "Episode 1: The Beginning"
    assert episodes[0].pub_date == "Mon, 01 Jan 2024 12:00:00 GMT"
    assert episodes[0].audio_url == "http://example.com/ep1.mp3"
    assert episodes[0].filename == "Episode_1_The_Beginning.mp3"
    
    assert episodes[1].title == "Episode 2: The Middle"
    assert episodes[1].audio_url == "http://example.com/ep2.m4a"
    assert episodes[1].filename == "Episode_2_The_Middle.m4a"

def test_feed_scraper_limit():
    scraper = FeedScraper("http://mock.feed")
    episodes = scraper.parse_xml(MOCK_RSS, limit=1)
    
    assert len(episodes) == 1
    assert episodes[0].title == "Episode 1: The Beginning"

def test_transcriber_vtt_formatting(mock_output_dir):
    episode = Episode(title="Test Ep", pub_date="2024", audio_url="http://x/a.mp3", filename="Test_Ep.mp3")
    transcriber = Transcriber(mock_output_dir)
    
    vtt_path = transcriber.transcribe(episode)
    
    assert vtt_path.exists()
    assert vtt_path.name == "Test_Ep.vtt"
    
    content = vtt_path.read_text(encoding='utf-8')
    assert "WEBVTT" in content
    assert "Welcome to Test Ep!" in content
    assert "00:00:00.000 --> 00:00:05.000" in content

def test_downloader_dry_run(mock_output_dir):
    episode = Episode(title="Test", pub_date="", audio_url="http://x/a.mp3", filename="test.mp3")
    downloader = Downloader(mock_output_dir)
    
    path = downloader.download(episode, dry_run=True)
    
    assert path is not None
    assert str(path).endswith("test.mp3")
    assert not path.exists() # Should not be created

def test_transcriber_dry_run(mock_output_dir):
    episode = Episode(title="Test", pub_date="", audio_url="http://x/a.mp3", filename="test.mp3")
    transcriber = Transcriber(mock_output_dir)
    
    path = transcriber.transcribe(episode, dry_run=True)
    
    assert path is not None
    assert str(path).endswith("test.vtt")
    assert not path.exists() # Should not be created

@patch("podcast_transcriber.FeedScraper")
@patch("podcast_transcriber.Downloader")
@patch("podcast_transcriber.Transcriber")
def test_main_cli_arguments(mock_transcriber, mock_downloader, mock_scraper):
    from podcast_transcriber import main
    
    mock_scraper_inst = mock_scraper.return_value
    mock_scraper_inst.fetch_and_parse.return_value = [
        Episode(title="T1", pub_date="D1", audio_url="U1", filename="F1")
    ]
    
    mock_downloader_inst = mock_downloader.return_value
    mock_transcriber_inst = mock_transcriber.return_value
    
    test_args = ["podcast_transcriber.py", "--feed-url", "http://test.com/rss", "--output-dir", "/tmp", "--limit", "2", "--dry-run"]
    
    with patch("sys.argv", test_args):
        main()
        
    mock_scraper.assert_called_once_with("http://test.com/rss")
    mock_scraper_inst.fetch_and_parse.assert_called_once_with(limit=2)
    mock_downloader.assert_called_once()
    mock_transcriber.assert_called_once()
    
    mock_downloader_inst.download.assert_called_once_with(mock_scraper_inst.fetch_and_parse.return_value[0], dry_run=True)
    # the mock transcriber isn't called here because downloader returns a mock which is not None, wait actually downloader mock returns MagicMock which is truthy, so transcribe should be called
    mock_transcriber_inst.transcribe.assert_called_once_with(mock_scraper_inst.fetch_and_parse.return_value[0], dry_run=True)
