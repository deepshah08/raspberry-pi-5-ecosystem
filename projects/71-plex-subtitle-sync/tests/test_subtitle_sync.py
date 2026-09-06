import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from subtitle_sync import clean_ads, process_file_content, normalize_filename

def test_clean_ads():
    raw_sub = "1\n00:00:01,000 --> 00:00:04,000\nHello World!\n\n2\n00:00:05,000 --> 00:00:08,000\nDownloaded from www.opensubtitles.org"
    cleaned = clean_ads(raw_sub)
    assert "Hello World!" in cleaned
    assert "opensubtitles" not in cleaned
    assert "Downloaded from" not in cleaned

def test_process_file_content_encoding(tmp_path):
    sub_file = tmp_path / "test.srt"
    # Write some non-utf8 encoded text (e.g., windows-1252)
    # Using 'café' in windows-1252
    text = "caf\xe9"
    sub_file.write_bytes(text.encode("windows-1252"))
    
    modified, content = process_file_content(sub_file, clean=False, convert=True)
    assert modified is True
    assert "café" in content

def test_normalize_filename():
    sub_path = Path("/media/Movie_Sub.srt")
    videos = [Path("/media/Movie (2020).mkv"), Path("/media/Other Movie.mkv")]
    
    new_path = normalize_filename(sub_path, videos)
    assert new_path.name == "Movie (2020).en.srt"
    
def test_normalize_filename_forced():
    sub_path = Path("/media/Movie_Sub.forced.srt")
    videos = [Path("/media/Movie (2020).mkv")]
    
    new_path = normalize_filename(sub_path, videos)
    assert new_path.name == "Movie (2020).en.forced.srt"

def test_normalize_filename_lang():
    sub_path = Path("/media/Movie_Sub.fre.srt")
    videos = [Path("/media/Movie (2020).mkv")]
    
    new_path = normalize_filename(sub_path, videos)
    assert new_path.name == "Movie (2020).fre.srt"


def test_dry_run(tmp_path, capsys):
    sub_file = tmp_path / "test.srt"
    sub_file.write_text("Hello World!")
    videos = [tmp_path / "Movie.mkv"]
    
    import argparse
    from unittest.mock import patch
    
    with patch("sys.argv", ["subtitle_sync.py", "--path", str(tmp_path), "--dry-run", "--clean-ads"]):
        from subtitle_sync import main
        main()
        
    captured = capsys.readouterr()
    assert "No changes for: test.srt" in captured.out or "Processing:" in captured.out
