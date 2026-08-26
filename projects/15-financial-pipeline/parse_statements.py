import re
import sqlite3
import os

def parse_statement_text(text: str) -> list:
    """Parses transactions from statement text using regex."""
    transactions = []
    pattern = re.compile(r'(\d{4}-\d{2}-\d{2})\s+([A-Za-z0-9\s\.\,\-]+?)\s+([-\d\.\,]+)')
    for line in text.split('\n'):
        line = line.strip()
        match = pattern.search(line)
        if match:
            date, desc, amount_str = match.groups()
            amount = float(amount_str.replace('$', '').replace(',', ''))
            transactions.append({
                'date': date,
                'description': desc.strip(),
                'amount': amount
            })
    return transactions

def store_transactions(transactions: list, db_path="finances.db"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            description TEXT,
            amount REAL
        )
    ''')
    for t in transactions:
        cursor.execute(
            "INSERT INTO transactions (date, description, amount) VALUES (?, ?, ?)",
            (t['date'], t['description'], t['amount'])
        )
    conn.commit()
    conn.close()
