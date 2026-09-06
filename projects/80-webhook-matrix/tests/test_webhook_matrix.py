import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest
from unittest.mock import patch, MagicMock
import json
import urllib.request
import urllib.error
import hmac
import hashlib
import time

from webhook_matrix import SyntheticDispatcher, MatrixHealthEvaluator, SECRET_KEY, WebhookMatrixReceiver

class TestWebhookMatrix(unittest.TestCase):
    def setUp(self):
        WebhookMatrixReceiver.recorded_webhooks.clear()

    @patch('urllib.request.urlopen')
    def test_synthetic_event_emission(self, mock_urlopen):
        # Mock successful HTTP response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        dispatcher = SyntheticDispatcher()
        result = dispatcher.emit("http://example.com", "TestEvent", {"key": "value"})

        self.assertEqual(result["status"], 200)
        self.assertIn("latency_ms", result)
        self.assertIn("payload", result)
        self.assertEqual(result["payload"]["eventType"], "TestEvent")
        self.assertEqual(result["payload"]["data"]["key"], "value")

    def test_dry_run_emission(self):
        dispatcher = SyntheticDispatcher(dry_run=True)
        result = dispatcher.emit("http://example.com", "TestEvent", {"key": "value"})

        self.assertEqual(result["status"], "dry_run_success")
        self.assertIn("payload", result)

    @patch('sys.argv', ['webhook_matrix.py', '--dry-run', '--test-route', 'test,http://test.com'])
    @patch('webhook_matrix.start_receiver')
    def test_cli_args(self, mock_start_receiver):
        # Using import inside to capture the mocked sys.argv
        import webhook_matrix
        
        mock_server = MagicMock()
        mock_start_receiver.return_value = mock_server
        
        with patch('builtins.print') as mock_print:
            webhook_matrix.main()
            
            # Since it's dry run, it should print DRY RUN message (but we only capture stdout from script)
            # The script main output for routes:
            mock_print.assert_any_call("Route: test [UNHEALTHY] - Latency: N/A")


    @patch('urllib.request.urlopen')
    def test_payload_schema_and_hmac_validation(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        dispatcher = SyntheticDispatcher()
        dispatcher.emit("http://example.com", "SchemaEvent", {"info": "data"})

        req_call = mock_urlopen.call_args[0][0]
        payload = json.loads(req_call.data.decode('utf-8'))
        
        # Validate schema
        self.assertIn("eventId", payload)
        self.assertIn("eventType", payload)
        self.assertIn("data", payload)
        self.assertIn("_dispatched_at", payload)
        
        # Validate HMAC
        expected_mac = hmac.new(SECRET_KEY, req_call.data, hashlib.sha256).hexdigest()
        # Header keys are often title-cased or capitalised in urllib
        self.assertEqual(req_call.headers.get("X-hub-signature-256") or req_call.headers.get("X-Hub-Signature-256"), f"sha256={expected_mac}")

    @patch('urllib.request.urlopen')
    def test_latency_measurement_and_timeout(self, mock_urlopen):
        # Test HTTP Error
        mock_urlopen.side_effect = urllib.error.HTTPError("http://example.com", 500, "Internal Server Error", {}, None)
        
        dispatcher = SyntheticDispatcher()
        result = dispatcher.emit("http://example.com", "ErrorEvent", {})
        
        self.assertEqual(result["status"], 500)
        self.assertIn("latency_ms", result)
        self.assertIn("error", result)
        
        # Test General Exception (like timeout)
        mock_urlopen.side_effect = Exception("Timeout")
        
        result_timeout = dispatcher.emit("http://example.com", "TimeoutEvent", {})
        self.assertEqual(result_timeout["status"], 0)
        self.assertIn("latency_ms", result_timeout)
        self.assertIn("error", result_timeout)

    @patch('urllib.request.urlopen')
    def test_health_evaluator(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response
        
        # Monkey patch time.time to mock latency
        with patch('time.time', side_effect=[0, 0, 0.1, 0, 0, 0.6]): # 100ms first call, 600ms second call
            dispatcher = SyntheticDispatcher()
            evaluator = MatrixHealthEvaluator(dispatcher)
            
            # Fast response (100ms)
            result1 = evaluator.check_route("fast", "http://fast.com")
            self.assertTrue(result1["healthy"])
            
            # Slow response (600ms)
            result2 = evaluator.check_route("slow", "http://slow.com")
            self.assertFalse(result2["healthy"])

if __name__ == '__main__':
    unittest.main()
