import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import time
import pytest
from unittest.mock import patch, MagicMock

from video_cache_manager import (
    parse_args,
    get_video_metadata,
    build_transcode_command,
    prune_cache,
    main
)

def test_parse_args():
    args = parse_args(["--input", "video.mp4", "--cache-dir", "/cache", "--max-cache-gb", "10", "--dry-run"])
    assert args.input == "video.mp4"
    assert args.cache_dir == "/cache"
    assert args.max_cache_gb == 10.0
    assert args.dry_run is True
    assert args.clean_cache is False

def test_parse_args_clean_cache():
    args = parse_args(["--cache-dir", "/cache", "--clean-cache"])
    assert args.cache_dir == "/cache"
    assert args.clean_cache is True
    assert args.input is None

@patch("subprocess.run")
def test_get_video_metadata(mock_run):
    mock_result = MagicMock()
    mock_result.stdout = json.dumps({"format": {"duration": "120"}, "streams": [{"codec_name": "hevc"}]})
    mock_run.return_value = mock_result
    
    metadata = get_video_metadata(Path("test.mp4"))
    assert metadata["format"]["duration"] == "120"
    assert metadata["streams"][0]["codec_name"] == "hevc"
    mock_run.assert_called_once()

@patch("subprocess.run")
def test_get_video_metadata_error(mock_run):
    import subprocess
    mock_run.side_effect = subprocess.CalledProcessError(1, "cmd")
    metadata = get_video_metadata(Path("test.mp4"))
    assert metadata == {}

@patch("pathlib.Path.exists")
def test_build_transcode_command_cpu_fallback(mock_exists):
    # Mock /dev/dri to return False
    mock_exists.return_value = False
    
    cmd = build_transcode_command(Path("input.mp4"), Path("output.mp4"))
    assert "ffmpeg" in cmd
    assert "-i" in cmd
    assert "input.mp4" in cmd
    assert "output.mp4" in cmd
    assert "-vf" in cmd
    assert "scale=-2:1080" in cmd
    assert "-c:v" in cmd
    assert "libx264" in cmd
    assert "+faststart" in cmd

@patch("pathlib.Path.exists")
def test_build_transcode_command_qsv(mock_exists):
    # Mock /dev/dri to return True
    mock_exists.return_value = True
    
    cmd = build_transcode_command(Path("input.mp4"), Path("output.mp4"))
    assert "ffmpeg" in cmd
    assert "-hwaccel" in cmd
    assert "qsv" in cmd
    assert "-i" in cmd
    assert "input.mp4" in cmd
    assert "output.mp4" in cmd
    assert "-vf" in cmd
    assert "scale_qsv=w=-2:h=1080" in cmd
    assert "-c:v" in cmd
    assert "h264_qsv" in cmd
    assert "+faststart" in cmd

def test_prune_cache(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    
    # Create 3 files of 100MB each (total 300MB)
    f1 = cache_dir / "f1.mp4"
    f2 = cache_dir / "f2.mp4"
    f3 = cache_dir / "f3.mp4"
    
    f1.write_bytes(b"0" * 100_000_000)
    time.sleep(0.01)
    f2.write_bytes(b"0" * 100_000_000)
    time.sleep(0.01)
    f3.write_bytes(b"0" * 100_000_000)
    
    # Max cache size 0.2GB (200MB roughly, actually 0.2 * 1024^3 = 214MB)
    # Total size is 300_000_000 bytes ~ 286MB. Need to free ~72MB. 
    # Deleting oldest (f1) will free 100MB and leave 200MB.
    prune_cache(cache_dir, max_cache_gb=0.2, dry_run=False)
    
    assert not f1.exists()
    assert f2.exists()
    assert f3.exists()

def test_prune_cache_dry_run(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    
    f1 = cache_dir / "f1.mp4"
    f1.write_bytes(b"0" * 100_000_000)
    
    # Max size 0.05GB ~ 53MB. File is 100MB. Limit exceeded.
    prune_cache(cache_dir, max_cache_gb=0.05, dry_run=True)
    
    # Dry run should not delete
    assert f1.exists()

@patch("video_cache_manager.parse_args")
@patch("video_cache_manager.subprocess.run")
def test_main_transcode(mock_run, mock_parse_args, tmp_path):
    input_file = tmp_path / "input.mp4"
    input_file.write_text("dummy video")
    cache_dir = tmp_path / "cache"
    
    mock_args = MagicMock()
    mock_args.input = str(input_file)
    mock_args.cache_dir = str(cache_dir)
    mock_args.max_cache_gb = 10.0
    mock_args.dry_run = False
    mock_args.clean_cache = False
    mock_parse_args.return_value = mock_args
    
    mock_result = MagicMock()
    mock_result.stdout = json.dumps({"format": {"duration": "120"}, "streams": [{"codec_name": "hevc"}]})
    mock_run.return_value = mock_result
    
    main()
    
    assert cache_dir.exists()
    mock_run.assert_called()

@patch("video_cache_manager.parse_args")
def test_main_clean_cache_only(mock_parse_args, tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    
    f1 = cache_dir / "f1.mp4"
    f1.write_bytes(b"0" * 100_000_000)
    
    mock_args = MagicMock()
    mock_args.input = None
    mock_args.cache_dir = str(cache_dir)
    mock_args.max_cache_gb = 0.05 # ~53MB
    mock_args.dry_run = False
    mock_args.clean_cache = True
    mock_parse_args.return_value = mock_args
    
    main()
    
    # File should be deleted because 100MB > 53MB
    assert not f1.exists()
