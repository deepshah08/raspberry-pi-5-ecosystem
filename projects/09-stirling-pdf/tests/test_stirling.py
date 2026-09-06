import unittest
import os
import sys, os; sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))); from validate_stirling import validate_compose

class TestStirlingPDF(unittest.TestCase):
    def test_validation(self):
        compose_path = os.path.join(os.path.dirname(__file__), "..", "docker-compose.stirling.yml")
        valid, msg = validate_compose(compose_path)
        self.assertTrue(valid, msg)

if __name__ == "__main__":
    unittest.main()
