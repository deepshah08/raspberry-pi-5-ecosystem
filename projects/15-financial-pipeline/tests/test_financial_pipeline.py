import unittest
import tempfile
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from portfolio_tracker import PortfolioTracker
from parse_statements import parse_statement_text, store_transactions

class TestFinancialPipeline(unittest.TestCase):
    def test_portfolio_nav_and_allocations(self):
        tracker = PortfolioTracker()
        csv_data = '''date,type,symbol,shares,price
2026-01-01,BUY,AAPL,10,150.0
2026-01-02,BUY,MSFT,5,300.0
2026-01-03,SELL,AAPL,2,160.0
'''
        tracker.ingest_transactions(csv_data)
        prices = {'AAPL': 200.0, 'MSFT': 400.0}
        nav = tracker.get_nav(prices)
        self.assertEqual(nav, 3600.0)
        allocations = tracker.get_asset_allocations(prices)
        self.assertAlmostEqual(allocations['AAPL'], (1600.0 / 3600.0) * 100.0, places=2)
        self.assertAlmostEqual(allocations['MSFT'], (2000.0 / 3600.0) * 100.0, places=2)

    def test_parse_and_store_statements(self):
        sample_text = '''
2026-08-01 Whole Foods Market -45.20
2026-08-02 Payroll Direct Deposit 3500.00
2026-08-03 Netflix Subscription -15.99
'''
        txs = parse_statement_text(sample_text)
        self.assertEqual(len(txs), 3)
        self.assertEqual(txs[0]['description'], 'Whole Foods Market')
        self.assertEqual(txs[0]['amount'], -45.20)
        
        temp_dir = tempfile.TemporaryDirectory()
        db_path = os.path.join(temp_dir.name, 'test_finances.db')
        store_transactions(txs, db_path=db_path)
        self.assertTrue(os.path.exists(db_path))
        temp_dir.cleanup()

if __name__ == '__main__':
    unittest.main()
