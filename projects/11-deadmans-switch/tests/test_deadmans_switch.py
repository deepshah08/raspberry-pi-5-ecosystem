import unittest
import tempfile
import os
import time
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from daemon import split_secret, recover_secret, DeadMansSwitch

class TestDeadMansSwitch(unittest.TestCase):
    def test_shamir_secret_sharing_math(self):
        secret_msg = 'SUPER_SECRET_RECOVERY_KEY_XYZ'
        secret_int = int.from_bytes(secret_msg.encode('utf-8'), 'big')
        
        shares = split_secret(secret_int, threshold=3, total_shares=5)
        self.assertEqual(len(shares), 5)
        
        subset_shares = [shares[0], shares[2], shares[4]]
        recovered_int = recover_secret(subset_shares)
        recovered_msg = recovered_int.to_bytes((recovered_int.bit_length() + 7) // 8, 'big').decode('utf-8')
        
        self.assertEqual(recovered_msg, secret_msg)

    def test_switch_heartbeat(self):
        temp_dir = tempfile.TemporaryDirectory()
        ping_path = os.path.join(temp_dir.name, 'ping.txt')
        switch = DeadMansSwitch(ping_file=ping_path, timeout_seconds=10)
        
        self.assertTrue(switch.check_alive())
        self.assertTrue(os.path.exists(ping_path))
        
        expired_switch = DeadMansSwitch(ping_file=ping_path, timeout_seconds=0.01)
        time.sleep(0.05)
        self.assertFalse(expired_switch.check_alive())
        
        shares = switch.trigger()
        self.assertEqual(len(shares), 5)
        temp_dir.cleanup()

if __name__ == '__main__':
    unittest.main()
