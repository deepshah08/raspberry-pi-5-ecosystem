import unittest
import os
from validate_n8n import validate_n8n_compose

class TestN8NConfig(unittest.TestCase):
    def test_validation(self):
        compose_path = os.path.join(os.path.dirname(__file__), "..", "docker-compose.n8n.yml")
        valid, msg = validate_n8n_compose(compose_path)
        self.assertTrue(valid, msg)

if __name__ == "__main__":
    unittest.main()
