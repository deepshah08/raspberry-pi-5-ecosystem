import unittest
import tempfile
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from pixel1_sync_guard import PixelSyncGuard

class TestBackupEngine(unittest.TestCase):
    def setUp(self):
        self.staging_dir = tempfile.TemporaryDirectory()
        self.guard = PixelSyncGuard(staging_dir=self.staging_dir.name, remote_dir='/sdcard/DCIM/NAS_Sync')

    def tearDown(self):
        self.staging_dir.cleanup()

    def test_local_checksum(self):
        test_file = os.path.join(self.staging_dir.name, 'photo.jpg')
        with open(test_file, 'wb') as f:
            f.write(b'sample_image_binary_data')
        checksum = self.guard.get_local_checksum(test_file)
        self.assertIsNotNone(checksum)
        self.assertEqual(len(checksum), 32)

    def test_purge_logic(self):
        test_file = os.path.join(self.staging_dir.name, 'old_photo.jpg')
        with open(test_file, 'wb') as f:
            f.write(b'old_data')
        self.assertFalse(self.guard.should_purge(test_file, days=3))

if __name__ == '__main__':
    unittest.main()
