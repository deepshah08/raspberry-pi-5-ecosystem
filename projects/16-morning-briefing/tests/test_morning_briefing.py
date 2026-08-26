import unittest
import tempfile
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import MorningBriefing

class TestMorningBriefing(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.briefing = MorningBriefing(output_dir=self.tmp_dir.name)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_generate_briefing_text(self):
        mock_headlines = [
            {'title': 'Global Markets Rally', 'description': 'Tech stocks lead market gains worldwide.'},
            {'title': 'AI Hardware Advancements', 'description': 'New energy efficient chips announced.'}
        ]
        text = self.briefing.generate_briefing(mock_headlines, sentiment_score=0.45)
        self.assertIn('Morning Briefing', text)
        self.assertIn('Global Markets Rally', text)
        self.assertIn('+0.45', text)

    def test_run_generates_file(self):
        content = self.briefing.run(sentiment_score=0.10)
        self.assertIsInstance(content, str)
        self.assertGreater(len(content), 20)

if __name__ == '__main__':
    unittest.main()
