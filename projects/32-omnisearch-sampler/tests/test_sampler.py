import asyncio
import json
import os
import shutil
import tempfile
import sys
import sys, os; sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))); from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add projects/32-omnisearch-sampler to sys.path so we can import sampler
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import sys, os; sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))); from sampler import MediaSampler


@pytest.fixture
def temp_workspace():
    workspace = tempfile.mkdtemp()
    output_dir = os.path.join(workspace, "output")
    state_file = os.path.join(workspace, "state.json")
    media_dir = os.path.join(workspace, "media")
    os.makedirs(media_dir)

    yield workspace, output_dir, state_file, media_dir

    shutil.rmtree(workspace)


@pytest.mark.asyncio
async def test_compute_hash_and_deduplication(temp_workspace):
    workspace, output_dir, state_file, media_dir = temp_workspace
    sampler = MediaSampler(output_dir=output_dir, state_file=state_file)

    test_file = Path(media_dir) / "test.jpg"
    test_file.write_text("dummy content")

    # Process once
    await sampler.process_file(test_file)
    assert sampler.queue.qsize() == 1

    # Process again, should be skipped
    await sampler.process_file(test_file)
    assert sampler.queue.qsize() == 1  # Still 1

    # Check state file
    assert os.path.exists(state_file)
    with open(state_file, 'r') as f:
        data = json.load(f)
        assert len(data.get("processed_hashes", [])) == 1


@pytest.mark.asyncio
async def test_process_photo(temp_workspace):
    workspace, output_dir, state_file, media_dir = temp_workspace
    sampler = MediaSampler(output_dir=output_dir, state_file=state_file)

    photo_file = Path(media_dir) / "photo.png"
    photo_file.write_text("dummy")

    await sampler.process_file(photo_file)

    item = await sampler.queue.get()
    assert item[0] == str(photo_file)
    assert item[1] == 0.0
    assert item[2] == "photo"
    assert item[3] == str(photo_file)


@pytest.mark.asyncio
@patch('asyncio.create_subprocess_exec')
async def test_extract_keyframes_success(mock_create_subprocess_exec, temp_workspace):
    workspace, output_dir, state_file, media_dir = temp_workspace
    sampler = MediaSampler(output_dir=output_dir, state_file=state_file)

    video_file = Path(media_dir) / "video.mp4"
    video_file.write_text("dummy video")

    # Mocking asyncio.create_subprocess_exec return value
    mock_process = MagicMock()
    # Mock ffmpeg showinfo output for two frames
    stderr_output = b"pts_time:1.5\npts_time:3.0\n"

    # For asyncio.create_subprocess_exec we need to mock a coroutine function
    # instead of passing asyncio.coroutine (which is deprecated)
    async def mock_communicate():
        return (b"", stderr_output)

    mock_process.communicate = mock_communicate
    mock_process.returncode = 0
    mock_create_subprocess_exec.return_value = mock_process

    await sampler.process_file(video_file)

    assert sampler.queue.qsize() == 2

    item1 = await sampler.queue.get()
    assert item1[0] == str(video_file)
    assert item1[1] == 1.5
    assert item1[2] == "video"
    assert "frame_0001.jpg" in item1[3]

    item2 = await sampler.queue.get()
    assert item2[0] == str(video_file)
    assert item2[1] == 3.0
    assert item2[2] == "video"
    assert "frame_0002.jpg" in item2[3]


@pytest.mark.asyncio
@patch('asyncio.create_subprocess_exec')
async def test_extract_keyframes_failure(mock_create_subprocess_exec, temp_workspace):
    workspace, output_dir, state_file, media_dir = temp_workspace
    sampler = MediaSampler(output_dir=output_dir, state_file=state_file)

    video_file = Path(media_dir) / "bad_video.mkv"
    video_file.write_text("bad video")

    mock_process = MagicMock()
    async def mock_communicate():
        return (b"", b"error")
    mock_process.communicate = mock_communicate
    mock_process.returncode = 1
    mock_create_subprocess_exec.return_value = mock_process

    await sampler.process_file(video_file)

    assert sampler.queue.qsize() == 0


@pytest.mark.asyncio
async def test_scan_paths(temp_workspace):
    workspace, output_dir, state_file, media_dir = temp_workspace
    sampler = MediaSampler(output_dir=output_dir, state_file=state_file)

    file1 = Path(media_dir) / "a.jpg"
    file2 = Path(media_dir) / "b.mp4"
    file3 = Path(media_dir) / "c.txt" # Should be ignored

    file1.write_text("a")
    file2.write_text("b")
    file3.write_text("c")

    # We patch process_file so we don't actually try to run ffmpeg
    with patch.object(sampler, 'process_file') as mock_process_file:
        async def mock_process_file_impl(*args, **kwargs):
            pass
        mock_process_file.side_effect = mock_process_file_impl

        await sampler.scan_paths([media_dir, "non_existent_path"])

        assert mock_process_file.call_count == 2
        calls = [c[0][0] for c in mock_process_file.call_args_list]
        assert any(str(c) == str(file1) for c in calls)
        assert any(str(c) == str(file2) for c in calls)
        assert not any(str(c) == str(file3) for c in calls)
