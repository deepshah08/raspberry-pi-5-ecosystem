import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from unittest.mock import patch, MagicMock
from ml_governor import ImmichClient

@pytest.fixture
def client():
    return ImmichClient("http://immich:2283", "test_api_key")

def test_get_queue_status_success(client):
    with patch('requests.get') as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "facialRecognition": {"jobCounts": {"active": 5, "waiting": 10}},
            "smartSearch": {"jobCounts": {"active": 2, "waiting": 0}}
        }
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        status = client.get_queue_status()
        assert "facialRecognition" in status
        assert status["facialRecognition"]["jobCounts"]["active"] == 5
        mock_get.assert_called_once_with("http://immich:2283/api/jobs", headers=client.headers, timeout=10)

def test_get_queue_status_failure(client):
    with patch('requests.get') as mock_get:
        mock_get.side_effect = Exception("Connection Error")
        status = client.get_queue_status()
        assert status == {}

def test_get_ml_status_online(client):
    with patch('requests.get') as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        status = client.get_ml_status()
        assert status["status"] == "online"
        mock_get.assert_called_once_with("http://immich:3003/ping", timeout=5)

def test_pause_job_success(client):
    with patch('requests.put') as mock_put:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_put.return_value = mock_resp

        result = client.pause_job_processing("facialRecognition")
        assert result is True
        mock_put.assert_called_once_with("http://immich:2283/api/jobs/facialRecognition/pause", headers=client.headers, timeout=10)

def test_resume_job_success(client):
    with patch('requests.put') as mock_put:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_put.return_value = mock_resp

        result = client.resume_job_processing("smartSearch")
        assert result is True
        mock_put.assert_called_once_with("http://immich:2283/api/jobs/smartSearch/resume", headers=client.headers, timeout=10)

from ml_governor import Governor, parse_args, JOBS_QUEUED, THROTTLED_STATE, main

@pytest.fixture
def governor(client):
    return Governor(client, max_cpu=80.0, dry_run=False)

def test_governor_throttle(governor):
    with patch('psutil.cpu_percent', return_value=95.0), \
         patch('psutil.virtual_memory') as mock_mem:

        mem_mock = MagicMock()
        mem_mock.percent = 50.0
        mock_mem.return_value = mem_mock

        governor.client.get_queue_status = MagicMock(return_value={
            "facialRecognition": {"jobCounts": {"active": 5, "waiting": 10}}
        })
        governor.client.pause_job_processing = MagicMock()

        governor.check_and_govern()

        assert governor.throttled is True
        assert JOBS_QUEUED._value.get() == 15
        assert THROTTLED_STATE._value.get() == 1
        assert governor.client.pause_job_processing.call_count == len(governor.ml_jobs)

def test_governor_resume(governor):
    governor.throttled = True # start throttled

    with patch('psutil.cpu_percent', return_value=50.0), \
         patch('psutil.virtual_memory') as mock_mem:

        mem_mock = MagicMock()
        mem_mock.percent = 50.0
        mock_mem.return_value = mem_mock

        governor.client.get_queue_status = MagicMock(return_value={})
        governor.client.resume_job_processing = MagicMock()

        governor.check_and_govern()

        assert governor.throttled is False
        assert THROTTLED_STATE._value.get() == 0
        assert governor.client.resume_job_processing.call_count == len(governor.ml_jobs)

def test_parse_args():
    test_args = ["--immich-url", "http://immich:2283", "--api-key", "testkey", "--max-cpu", "75", "--check-now"]
    with patch.object(sys, 'argv', ['ml_governor.py'] + test_args):
        args = parse_args()
        assert args.immich_url == "http://immich:2283"
        assert args.api_key == "testkey"
        assert args.max_cpu == 75.0
        assert args.check_now is True
        assert args.dry_run is False

def test_main_check_now():
    test_args = ["--immich-url", "http://immich:2283", "--api-key", "testkey", "--check-now"]
    with patch.object(sys, 'argv', ['ml_governor.py'] + test_args), \
         patch('ml_governor.Governor.check_and_govern') as mock_check, \
         patch('sys.exit', side_effect=SystemExit) as mock_exit:

         try:
             main()
         except SystemExit:
             pass
         mock_check.assert_called_once()
         mock_exit.assert_called_once_with(0)
