import unittest
from unittest.mock import patch, MagicMock
import tempfile
import os
import json
from datetime import date
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../projects/14-market-sentiment')))
from sentiment_analyzer import fetch_rss_feed, calculate_average_sentiment, save_daily_report

class TestSentimentAnalyzer(unittest.TestCase):
    
    @patch('urllib.request.urlopen')
    def test_fetch_rss_feed(self, mock_urlopen):
        mock_xml = b"""<?xml version="1.0" encoding="UTF-8" ?>
        <rss version="2.0">
            <channel>
                <item>
                    <title>Test Title 1</title>
                    <description>Test Description 1</description>
                </item>
                <item>
                    <title>Test Title 2</title>
                </item>
                <item>
                    <description>Test Description 3</description>
                </item>
            </channel>
        </rss>
        """
        mock_response = MagicMock()
        mock_response.read.return_value = mock_xml
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response
        
        url = "http://fake.rss.url"
        texts = fetch_rss_feed(url)
        
        self.assertEqual(len(texts), 4)
        self.assertIn("Test Title 1", texts)
        self.assertIn("Test Description 1", texts)
        self.assertIn("Test Title 2", texts)
        self.assertIn("Test Description 3", texts)
        
    @patch('urllib.request.urlopen')
    def test_fetch_rss_feed_error(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Network Error")
        url = "http://fake.rss.url"
        texts = fetch_rss_feed(url)
        self.assertEqual(texts, [])

    def test_calculate_average_sentiment(self):
        self.assertEqual(calculate_average_sentiment([]), 0.0)
        
        positive_texts = ["This is great!", "I love this market."]
        score_pos = calculate_average_sentiment(positive_texts)
        self.assertGreater(score_pos, 0.0)
        
        negative_texts = ["This is terrible.", "I hate this."]
        score_neg = calculate_average_sentiment(negative_texts)
        self.assertLess(score_neg, 0.0)
        
        mixed_texts = ["The market opened today.", "It is a regular day."]
        score_mixed = calculate_average_sentiment(mixed_texts)
        self.assertAlmostEqual(score_mixed, 0.0, delta=0.2)

    def test_save_daily_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = os.path.join(temp_dir, 'ai_models', 'sentiment_history.json')
            
            score1 = 0.5
            history1 = save_daily_report(file_path, score1)
            
            today_str = date.today().isoformat()
            self.assertIn(today_str, history1)
            self.assertEqual(history1[today_str], score1)
            
            with open(file_path, 'r') as f:
                saved_data = json.load(f)
                self.assertEqual(saved_data, history1)
                
            score2 = 0.8
            history2 = save_daily_report(file_path, score2)
            
            self.assertEqual(len(history2), 1)
            self.assertEqual(history2[today_str], score2)

    def test_save_daily_report_current_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            orig_cwd = os.getcwd()
            try:
                os.chdir(temp_dir)
                file_path = "sentiment_history.json"
                history = save_daily_report(file_path, 0.42)
                today_str = date.today().isoformat()
                self.assertIn(today_str, history)
                self.assertEqual(history[today_str], 0.42)
            finally:
                os.chdir(orig_cwd)

if __name__ == '__main__':
    unittest.main()
