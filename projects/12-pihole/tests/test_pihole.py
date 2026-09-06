import unittest
import sys, os; sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))); from validate_pihole import check_dns_port, check_gravity_db

class TestPiholeConfig(unittest.TestCase):
    def test_dns_validation_function(self):
        # Function returns boolean without throwing uncaught exceptions
        res = check_dns_port(host="127.0.0.1", port=53)
        self.assertIsInstance(res, bool)

    def test_gravity_db_check(self):
        exists, path = check_gravity_db()
        self.assertIsInstance(exists, bool)
        self.assertIsInstance(path, str)

if __name__ == "__main__":
    unittest.main()
