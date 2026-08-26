import csv
import io
from collections import defaultdict

class PortfolioTracker:
    def __init__(self):
        self.holdings = defaultdict(float)

    def ingest_transactions(self, file_content: str):
        """
        Ingest transactions from a CSV file content.
        Expected headers: date, type, symbol, shares, price
        """
        reader = csv.DictReader(io.StringIO(file_content))
        for row in reader:
            if not row:
                continue
            symbol = row.get("symbol", "").strip().upper()
            if not symbol:
                continue
            try:
                shares = float(row.get("shares", 0))
            except ValueError:
                shares = 0.0
            tx_type = row.get("type", "").strip().upper()
            if tx_type == "BUY":
                self.holdings[symbol] += shares
            elif tx_type == "SELL":
                self.holdings[symbol] -= shares

    def get_nav(self, current_prices: dict) -> float:
        """Calculate total Net Asset Value."""
        nav = 0.0
        for symbol, shares in self.holdings.items():
            price = current_prices.get(symbol, 0.0)
            nav += shares * price
        return nav

    def get_asset_allocations(self, current_prices: dict) -> dict:
        """Calculate percentage weighting of each asset based on current NAV."""
        nav = self.get_nav(current_prices)
        allocations = {}
        if nav == 0:
            return allocations
        for symbol, shares in self.holdings.items():
            price = current_prices.get(symbol, 0.0)
            value = shares * price
            allocations[symbol] = (value / nav) * 100.0
        return allocations

    def get_summary(self, current_prices: dict) -> dict:
        """Return a summary containing NAV, holdings, and allocations."""
        return {
            "nav": self.get_nav(current_prices),
            "holdings": dict(self.holdings),
            "allocations": self.get_asset_allocations(current_prices)
        }
