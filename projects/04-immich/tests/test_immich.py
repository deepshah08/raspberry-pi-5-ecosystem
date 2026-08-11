import unittest
from pathlib import Path
from config import NAS_BINDINGS
from validate_config import validate

class TestImmichConfig(unittest.TestCase):
    def test_nas_bindings_keys(self):
        self.assertIn("UPLOAD_LOCATION", NAS_BINDINGS)
        self.assertIn("DB_DATA_LOCATION", NAS_BINDINGS)

    def test_validation(self):
        result = validate()
        self.assertIsInstance(result, bool)

if __name__ == "__main__":
    unittest.main()
