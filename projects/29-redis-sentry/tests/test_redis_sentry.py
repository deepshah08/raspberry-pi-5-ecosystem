import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unittest
from unittest.mock import patch, MagicMock
import json
import time
from io import StringIO
import argparse

import pytest
from prometheus_client import REGISTRY

from redis_sentry import RedisSentry, main

class TestRedisSentry(unittest.TestCase):

    @patch('redis.Redis')
    def test_init(self, mock_redis):
        sentry = RedisSentry('localhost', 6379)
        self.assertEqual(sentry.host, 'localhost')
        self.assertEqual(sentry.port, 6379)
        self.assertFalse(sentry.dry_run)
        self.assertFalse(sentry.json_output)

    @patch('redis.Redis')
    def test_get_info(self, mock_redis):
        mock_client = mock_redis.return_value
        mock_client.info.side_effect = [
            {'used_memory': 1000},
            {'evicted_keys': 10},
            {'keys': 100},
            {'connected_clients': 5}
        ]
        
        sentry = RedisSentry('localhost', 6379)
        info = sentry.get_info()
        
        self.assertEqual(info['memory'], {'used_memory': 1000})
        self.assertEqual(info['stats'], {'evicted_keys': 10})
        self.assertEqual(info['keyspace'], {'keys': 100})
        self.assertEqual(info['clients'], {'connected_clients': 5})

    @patch('redis.Redis')
    def test_get_info_exception(self, mock_redis):
        mock_client = mock_redis.return_value
        mock_client.info.side_effect = Exception("Connection error")
        
        sentry = RedisSentry('localhost', 6379)
        info = sentry.get_info()
        self.assertEqual(info, {})

    @patch('redis.Redis')
    @patch('time.time')
    def test_audit_cache_info_memory_saturation(self, mock_time, mock_redis):
        mock_time.return_value = 1000
        sentry = RedisSentry('localhost', 6379, json_output=True)
        info = {
            'memory': {'used_memory': 950, 'maxmemory': 1000},
            'stats': {'evicted_keys': 0},
            'clients': {'connected_clients': 1}
        }
        
        with patch('sys.stdout', new=StringIO()) as fake_out:
            sentry.audit_cache_info(info)
            output = fake_out.getvalue().strip()
            self.assertTrue("memory_saturation" in output)
            
            # Prometheus metrics check
            val = REGISTRY.get_sample_value('homelab_redis_memory_used_bytes')
            self.assertEqual(val, 950.0)

    @patch('redis.Redis')
    @patch('time.time')
    def test_audit_cache_info_high_eviction_rate(self, mock_time, mock_redis):
        sentry = RedisSentry('localhost', 6379, json_output=True)
        
        # First call
        mock_time.return_value = 1000
        info1 = {
            'memory': {'used_memory': 100, 'maxmemory': 1000},
            'stats': {'evicted_keys': 10},
            'clients': {'connected_clients': 1}
        }
        sentry.audit_cache_info(info1)
        
        # Second call, 1 second later, 15 keys evicted (rate = 15 keys/sec)
        mock_time.return_value = 1001
        info2 = {
            'memory': {'used_memory': 100, 'maxmemory': 1000},
            'stats': {'evicted_keys': 25},
            'clients': {'connected_clients': 1}
        }
        
        with patch('sys.stdout', new=StringIO()) as fake_out:
            sentry.audit_cache_info(info2)
            output = fake_out.getvalue().strip()
            self.assertTrue("eviction_rate" in output)
            self.assertTrue("15.00" in output)
            
            val = REGISTRY.get_sample_value('homelab_redis_evicted_keys_total')
            self.assertEqual(val, 25.0)

    @patch('redis.Redis')
    def test_audit_cache_info_dry_run(self, mock_redis):
        sentry = RedisSentry('localhost', 6379, json_output=True, dry_run=True)
        info = {
            'memory': {'used_memory': 950, 'maxmemory': 1000},
            'stats': {'evicted_keys': 0},
            'clients': {'connected_clients': 1}
        }
        
        with patch('sys.stdout', new=StringIO()) as fake_out:
            sentry.audit_cache_info(info)
            output = fake_out.getvalue().strip()
            self.assertEqual(output, "") # Should be empty due to dry run

    @patch('redis.Redis')
    def test_audit_key_ttl_unbounded(self, mock_redis):
        mock_client = mock_redis.return_value
        mock_client.randomkey.return_value = 'test_key'
        mock_client.ttl.return_value = -1
        
        sentry = RedisSentry('localhost', 6379, json_output=True)
        
        with patch('sys.stdout', new=StringIO()) as fake_out:
            sentry.audit_key_ttl()
            output = fake_out.getvalue().strip()
            self.assertTrue("unbounded_key" in output)
            self.assertTrue("test_key" in output)

    @patch('redis.Redis')
    def test_audit_key_ttl_bounded(self, mock_redis):
        mock_client = mock_redis.return_value
        mock_client.randomkey.return_value = 'test_key'
        mock_client.ttl.return_value = 100
        
        sentry = RedisSentry('localhost', 6379, json_output=True)
        
        with patch('sys.stdout', new=StringIO()) as fake_out:
            sentry.audit_key_ttl()
            output = fake_out.getvalue().strip()
            self.assertEqual(output, "")

    @patch('redis.Redis')
    def test_audit_key_ttl_exception(self, mock_redis):
        mock_client = mock_redis.return_value
        mock_client.randomkey.side_effect = Exception("Connection error")
        
        sentry = RedisSentry('localhost', 6379)
        with patch('redis_sentry.logger.error') as mock_logger:
            sentry.audit_key_ttl()
            mock_logger.assert_called_once()

    @patch('argparse.ArgumentParser.parse_args')
    @patch('redis_sentry.RedisSentry')
    def test_cli_audit_now(self, mock_sentry_class, mock_parse_args):
        mock_parse_args.return_value = argparse.Namespace(
            audit_now=True,
            redis_host='localhost',
            redis_port=6379,
            dry_run=False,
            json=True
        )
        
        mock_sentry = mock_sentry_class.return_value
        
        with patch('sys.stdout', new=StringIO()) as fake_out:
            main()
            mock_sentry.run_audit.assert_called_once()
            output = fake_out.getvalue().strip()
            self.assertTrue("audit_complete" in output)

    @patch('argparse.ArgumentParser.parse_args')
    @patch('redis_sentry.RedisSentry')
    @patch('os.environ.get')
    def test_cli_env_vars(self, mock_env_get, mock_sentry_class, mock_parse_args):
        mock_parse_args.return_value = argparse.Namespace(
            audit_now=True,
            redis_host=None,
            redis_port=None,
            dry_run=False,
            json=True
        )
        mock_env_get.side_effect = lambda k, d=None: 'custom_host' if k == 'REDIS_HOST' else (6380 if k == 'REDIS_PORT' else d)
        
        mock_sentry = mock_sentry_class.return_value
        
        with patch('sys.stdout', new=StringIO()) as fake_out:
            main()
            mock_sentry.run_audit.assert_called_once()
            output = fake_out.getvalue().strip()
            self.assertTrue("audit_complete" in output)

if __name__ == '__main__':
    unittest.main()
