import unittest
import tempfile
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from worker import JulesReviewWorker

class TestJulesReviewWorker(unittest.TestCase):
    def setUp(self):
        self.worker = JulesReviewWorker(repositories=["deepshah08/raspberry-pi-5-ecosystem"])
        self.tmp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_inspect_diff_syntax_valid(self):
        valid_py = os.path.join(self.tmp_dir.name, "valid.py")
        with open(valid_py, "w") as f:
            f.write("def add(a, b):\n    return a + b\n")
        issues = self.worker.inspect_diff_syntax([valid_py])
        self.assertEqual(len(issues), 0)

    def test_inspect_diff_syntax_invalid(self):
        invalid_py = os.path.join(self.tmp_dir.name, "invalid.py")
        with open(invalid_py, "w") as f:
            f.write("def broken(\n")
        issues = self.worker.inspect_diff_syntax([invalid_py])
        self.assertGreater(len(issues), 0)
        self.assertIn("SyntaxError", issues[0])

    def test_generate_review_summary_approval(self):
        pr = {"number": 42, "title": "feat: add autonomous agent pipeline"}
        res = self.worker.generate_review_summary(pr, test_passed=True, output_log="68 passed in 6.70s", syntax_issues=[])
        self.assertEqual(res["verdict"], "APPROVE")
        self.assertIn("LGTM", res["body"])

    def test_generate_review_summary_rejection(self):
        pr = {"number": 43, "title": "fix: broken import"}
        res = self.worker.generate_review_summary(pr, test_passed=False, output_log="1 failed", syntax_issues=["SyntaxError in foo.py"])
        self.assertEqual(res["verdict"], "REQUEST_CHANGES")
        self.assertIn("Changes Requested", res["body"])

    def test_run_tests_success(self):
        success, out = self.worker.run_tests(self.tmp_dir.name, test_cmd="python3 -c 'exit(0)'")
        self.assertTrue(success)

if __name__ == '__main__':
    unittest.main()
