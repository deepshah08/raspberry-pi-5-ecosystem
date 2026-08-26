import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from immich_config import NAS_BINDINGS
from validate_config import validate

class TestImmichConfig(unittest.TestCase):
    def test_nas_bindings_keys(self):
        self.assertIn('UPLOAD_LOCATION', NAS_BINDINGS)
        self.assertIn('DB_DATA_LOCATION', NAS_BINDINGS)

    def test_validation(self):
        result = validate()
        self.assertIsInstance(result, bool)

if __name__ == '__main__':
    unittest.main()
