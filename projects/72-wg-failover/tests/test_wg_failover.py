import sys
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

# Ensure we can import wg_failover
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import wg_failover

class TestWGFailover(unittest.TestCase):
    
    @patch('wg_failover.subprocess.run')
    @patch('wg_failover.time.time')
    def test_get_wg_peer_stats(self, mock_time, mock_subprocess_run):
        mock_time.return_value = 1000
        
        # interface pubkey preshared_key endpoint allowed_ips latest_handshake transfer_rx transfer_tx persistent_keepalive
        mock_stdout = "wg0\tpubkey1\t(none)\t192.168.1.80:51820\t10.0.0.2/32\t950\t100\t200\toff\n" \
                      "wg0\tpubkey2\t(none)\t192.168.1.92:51820\t10.0.0.3/32\t1000\t100\t200\toff\n" \
                      "wg0\tpubkey3\t(none)\t(none)\t10.0.0.4/32\t0\t0\t0\toff"
                      
        mock_result = MagicMock()
        mock_result.stdout = mock_stdout
        mock_subprocess_run.return_value = mock_result
        
        stats = wg_failover.get_wg_peer_stats()
        
        self.assertIn('192.168.1.80', stats)
        self.assertEqual(stats['192.168.1.80']['handshake_age'], 50)
        
        self.assertIn('192.168.1.92', stats)
        self.assertEqual(stats['192.168.1.92']['handshake_age'], 0)
        
        # (none) endpoint shouldn't be added with IP
        self.assertNotIn('(none)', stats)

    @patch('wg_failover.subprocess.run')
    def test_check_latency_success(self, mock_subprocess_run):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "64 bytes from 192.168.1.80: icmp_seq=1 ttl=64 time=45.2 ms"
        mock_subprocess_run.return_value = mock_result
        
        latency = wg_failover.check_latency('192.168.1.80')
        self.assertEqual(latency, 45.2)

    @patch('wg_failover.subprocess.run')
    def test_check_latency_fail(self, mock_subprocess_run):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_subprocess_run.return_value = mock_result
        
        latency = wg_failover.check_latency('192.168.1.80')
        self.assertEqual(latency, -1.0)
        
    def test_failover_controller_transition(self):
        controller = wg_failover.FailoverController('192.168.1.80', '192.168.1.92', dry_run=True)
        self.assertEqual(controller.active_node, '192.168.1.80')
        
        # Trigger failover
        controller.failover('192.168.1.92')
        self.assertEqual(controller.active_node, '192.168.1.92')
        
        # Failover again (same node shouldn't trigger anything special, but active node remains)
        controller.failover('192.168.1.92')
        self.assertEqual(controller.active_node, '192.168.1.92')
        
        # Revert to primary
        controller.failover('192.168.1.80')
        self.assertEqual(controller.active_node, '192.168.1.80')
        
    @patch('wg_failover.get_wg_peer_stats')
    @patch('wg_failover.check_latency')
    @patch('wg_failover.time.sleep')
    @patch('sys.argv', ['wg_failover.py', '--primary-ip', '192.168.1.80', '--secondary-ip', '192.168.1.92', '--check-now', '--dry-run'])
    def test_main_metrics_and_failover_trigger(self, mock_sleep, mock_check_latency, mock_get_stats):
        # Primary is dead (handshake -1, latency -1)
        # Secondary is healthy (handshake 10, latency 20)
        mock_get_stats.return_value = {
            '192.168.1.80': {'handshake_age': -1},
            '192.168.1.92': {'handshake_age': 10}
        }
        
        def latency_side_effect(ip):
            if ip == '192.168.1.80':
                return -1.0
            return 20.0
            
        mock_check_latency.side_effect = latency_side_effect
        
        initial_failovers = wg_failover.HOMELAB_WG_FAILOVER_COUNT._value.get()
        
        wg_failover.main()
        
        # Primary should be unhealthy, secondary healthy -> Failover to secondary triggered
        self.assertEqual(wg_failover.HOMELAB_WG_TUNNEL_HEALTHY.labels(peer_ip='192.168.1.80')._value.get(), 0)
        self.assertEqual(wg_failover.HOMELAB_WG_TUNNEL_HEALTHY.labels(peer_ip='192.168.1.92')._value.get(), 1)
        
        # Failover count should increment
        final_failovers = wg_failover.HOMELAB_WG_FAILOVER_COUNT._value.get()
        self.assertEqual(final_failovers, initial_failovers + 1)
        
    @patch('wg_failover.get_wg_peer_stats')
    @patch('wg_failover.check_latency')
    @patch('wg_failover.time.sleep')
    @patch('sys.argv', ['wg_failover.py', '--primary-ip', '192.168.1.80', '--secondary-ip', '192.168.1.92', '--check-now', '--dry-run'])
    def test_main_primary_healthy(self, mock_sleep, mock_check_latency, mock_get_stats):
        # Both healthy
        mock_get_stats.return_value = {
            '192.168.1.80': {'handshake_age': 10},
            '192.168.1.92': {'handshake_age': 15}
        }
        mock_check_latency.return_value = 10.0
        
        # Make active node secondary temporarily to test fallback to primary
        # Wait, the script creates a fresh FailoverController starting with primary.
        # So failover shouldn't be called, failover count doesn't increase.
        initial_failovers = wg_failover.HOMELAB_WG_FAILOVER_COUNT._value.get()
        
        wg_failover.main()
        
        final_failovers = wg_failover.HOMELAB_WG_FAILOVER_COUNT._value.get()
        self.assertEqual(final_failovers, initial_failovers)


if __name__ == '__main__':
    unittest.main()
