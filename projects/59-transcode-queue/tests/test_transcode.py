import sys
import subprocess
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from transcode_daemon import probe_file, needs_transcode, run_transcode, replace_atomic

@pytest.fixture
def mock_subprocess_run():
    with patch("subprocess.run") as mock_run:
        yield mock_run

@pytest.fixture
def mock_shutil_copy2():
    with patch("shutil.copy2") as mock_copy:
        yield mock_copy

@pytest.fixture
def mock_os_rename():
    with patch("os.rename") as mock_rename:
        yield mock_rename

@pytest.fixture
def temp_files(tmp_path):
    input_file = tmp_path / "test_input.mp4"
    output_file = tmp_path / "test_output.mp4"
    input_file.write_text("dummy content")
    return input_file, output_file

def test_probe_file_success(mock_subprocess_run, temp_files):
    input_file, _ = temp_files
    mock_result = MagicMock()
    mock_result.stdout = json.dumps({"streams": [{"codec_type": "video", "codec_name": "h264"}]})
    mock_subprocess_run.return_value = mock_result

    result = probe_file(input_file)
    assert result is not None
    assert result["streams"][0]["codec_name"] == "h264"
    mock_subprocess_run.assert_called_once()

def test_probe_file_failure(mock_subprocess_run, temp_files):
    input_file, _ = temp_files
    mock_subprocess_run.side_effect = subprocess.CalledProcessError(1, "ffprobe")

    result = probe_file(input_file)
    assert result is None

def test_needs_transcode(mock_subprocess_run, temp_files):
    input_file, _ = temp_files
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat_obj = MagicMock()
        mock_stat.return_value = mock_stat_obj

        # Test 1: Size is large, but codec is already target -> FALSE
        mock_stat_obj.st_size = 600 * 1024 * 1024 # 600 MB
        mock_result = MagicMock()
        mock_result.stdout = json.dumps({"streams": [{"codec_type": "video", "codec_name": "hevc"}]})
        mock_subprocess_run.return_value = mock_result
        assert needs_transcode(input_file, 500, "hevc") == False

        # Test 2: Size is large, and codec is not target -> TRUE
        mock_stat_obj.st_size = 600 * 1024 * 1024 # 600 MB
        mock_result.stdout = json.dumps({"streams": [{"codec_type": "video", "codec_name": "vp9"}]})
        mock_subprocess_run.return_value = mock_result
        assert needs_transcode(input_file, 500, "hevc") == True

        # Test 3: Size is small, but codec is legacy -> TRUE
        mock_stat_obj.st_size = 400 * 1024 * 1024 # 400 MB
        mock_result.stdout = json.dumps({"streams": [{"codec_type": "video", "codec_name": "h264"}]})
        mock_subprocess_run.return_value = mock_result
        assert needs_transcode(input_file, 500, "hevc") == True

        # Test 4: Size is small, and codec is not legacy (and not target) -> FALSE
        mock_stat_obj.st_size = 400 * 1024 * 1024 # 400 MB
        mock_result.stdout = json.dumps({"streams": [{"codec_type": "video", "codec_name": "vp9"}]})
        mock_subprocess_run.return_value = mock_result
        assert needs_transcode(input_file, 500, "hevc") == False

def test_run_transcode_qsv_success(mock_subprocess_run, temp_files):
    input_file, output_file = temp_files
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_subprocess_run.return_value = mock_result

    success = run_transcode(input_file, output_file, "hevc", 23)
    assert success == True

    # QSV should be the first call
    called_args = mock_subprocess_run.call_args_list[0][0][0]
    assert "hevc_qsv" in called_args
    assert "-global_quality" in called_args
    assert "qsv=hw" in called_args
    # SW fallback should not be called
    assert mock_subprocess_run.call_count == 1

    # AV1 test
    mock_subprocess_run.reset_mock()
    success_av1 = run_transcode(input_file, output_file, "av1", 23)
    assert success_av1 == True
    called_args_av1 = mock_subprocess_run.call_args_list[0][0][0]
    assert "av1_qsv" in called_args_av1

def test_run_transcode_qsv_failure_sw_success(mock_subprocess_run, temp_files):
    input_file, output_file = temp_files

    # First call (QSV) fails, second call (SW) succeeds
    def mock_run_side_effect(*args, **kwargs):
        cmd = args[0]
        if "hevc_qsv" in cmd:
            mock_res = MagicMock()
            mock_res.returncode = 1
            mock_res.stderr = "QSV Failed"
            return mock_res
        elif "libx265" in cmd:
            mock_res = MagicMock()
            mock_res.returncode = 0
            return mock_res
        return MagicMock()

    mock_subprocess_run.side_effect = mock_run_side_effect

    # Write a dummy file to ensure cleanup is tested
    output_file.write_text("partial data")

    success = run_transcode(input_file, output_file, "hevc", 23)
    assert success == True

    # Both QSV and SW should be called
    assert mock_subprocess_run.call_count == 2
    sw_called_args = mock_subprocess_run.call_args_list[1][0][0]
    assert "libx265" in sw_called_args
    assert "-crf" in sw_called_args
    assert not output_file.exists()  # Ensure cleanup occurred before SW ran (our test context won't rewrite it)

def test_run_transcode_all_failure(mock_subprocess_run, temp_files):
    input_file, output_file = temp_files

    def mock_run_side_effect(*args, **kwargs):
        cmd = args[0]
        if "hevc_qsv" in cmd:
            mock_res = MagicMock()
            mock_res.returncode = 1
            return mock_res
        elif "libx265" in cmd:
            raise subprocess.CalledProcessError(1, "ffmpeg")

    mock_subprocess_run.side_effect = mock_run_side_effect

    success = run_transcode(input_file, output_file, "hevc", 23)
    assert success == False

def test_replace_atomic_success(mock_shutil_copy2, mock_os_rename, temp_files):
    input_file, output_file = temp_files
    # Ensure output file exists and has size
    output_file.write_text("transcoded content")

    dest_tmp = str(input_file.parent / f".tmp_{output_file.name}")

    success = replace_atomic(input_file, output_file, dry_run=False)
    assert success == True
    mock_shutil_copy2.assert_called_once_with(str(output_file), dest_tmp)
    mock_os_rename.assert_called_once_with(dest_tmp, str(input_file))
    assert not output_file.exists()  # Original tmp file should be unlinked

def test_replace_atomic_dry_run(mock_shutil_copy2, mock_os_rename, temp_files):
    input_file, output_file = temp_files
    output_file.write_text("transcoded content")

    success = replace_atomic(input_file, output_file, dry_run=True)
    assert success == True
    mock_shutil_copy2.assert_not_called()
    mock_os_rename.assert_not_called()

def test_replace_atomic_failure_empty(mock_shutil_copy2, mock_os_rename, temp_files):
    input_file, output_file = temp_files
    # Create empty output file
    output_file.write_text("")

    success = replace_atomic(input_file, output_file, dry_run=False)
    assert success == False
    mock_shutil_copy2.assert_not_called()
    mock_os_rename.assert_not_called()
