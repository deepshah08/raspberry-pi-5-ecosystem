import urllib.request
import xml.etree.ElementTree as ET
import json
import os
from datetime import date
import argparse

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
except ImportError:
    try:
        from nltk.sentiment.vader import SentimentIntensityAnalyzer
    except ImportError:
        SentimentIntensityAnalyzer = None

# Fallback basic lexicon for when VADER is not installed
_POSITIVE_WORDS = {"great", "good", "positive", "up", "gain", "profit", "bull", "bullish", "high", "growth", "boost", "surge", "love"}
_NEGATIVE_WORDS = {"bad", "terrible", "negative", "down", "loss", "bear", "bearish", "low", "decline", "drop", "fall", "hate", "crash"}

def _fallback_sentiment(text):
    words = text.lower().split()
    if not words:
        return 0.0
    pos_count = sum(1 for w in words if w.strip(".,!?;:\"'") in _POSITIVE_WORDS)
    neg_count = sum(1 for w in words if w.strip(".,!?;:\"'") in _NEGATIVE_WORDS)
    total = pos_count + neg_count
    if total == 0:
        return 0.0
    return (pos_count - neg_count) / total

def fetch_rss_feed(url):
    """
    Fetches and parses an RSS feed from the given URL.
    Returns a list of titles and descriptions.
    """
    texts = []
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            rss_content = response.read()
            root = ET.fromstring(rss_content)
            for item in root.findall('.//item'):
                title = item.find('title')
                description = item.find('description')
                
                if title is not None and title.text:
                    texts.append(title.text)
                if description is not None and description.text:
                    texts.append(description.text)
    except Exception as e:
        print(f"Error fetching RSS feed: {e}")
        
    return texts

def calculate_average_sentiment(texts):
    """
    Calculates the average sentiment score for a list of texts using VADER (or fallback lexicon).
    """
    if not texts:
        return 0.0
        
    if SentimentIntensityAnalyzer is not None:
        try:
            analyzer = SentimentIntensityAnalyzer()
            total_score = 0.0
            for text in texts:
                score = analyzer.polarity_scores(text)
                total_score += score['compound']
            return total_score / len(texts)
        except Exception:
            pass

    total_score = sum(_fallback_sentiment(t) for t in texts)
    return total_score / len(texts)

def save_daily_report(file_path, score):
    """
    Loads existing JSON history (if any), appends the daily sentiment score,
    and saves the JSON back.
    """
    dir_name = os.path.dirname(file_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    
    history = {}
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r') as f:
                history = json.load(f)
        except (json.JSONDecodeError, OSError):
            history = {}
            
    today_str = date.today().isoformat()
    history[today_str] = score
    
    with open(file_path, 'w') as f:
        json.dump(history, f, indent=4)
        
    return history

def main():
    parser = argparse.ArgumentParser(description="Market Sentiment Analyzer")
    parser.add_argument(
        "--url", 
        type=str, 
        default="https://finance.yahoo.com/news/rssindex",
        help="RSS feed URL"
    )
    parser.add_argument(
        "--output", 
        type=str, 
        default="/mnt/nas/ai_models/sentiment_history.json",
        help="Path to output JSON file"
    )
    args = parser.parse_args()

    print(f"Fetching RSS feed from: {args.url}")
    texts = fetch_rss_feed(args.url)
    
    if texts:
        print(f"Fetched {len(texts)} texts. Calculating sentiment...")
        avg_score = calculate_average_sentiment(texts)
        print(f"Average sentiment score: {avg_score:.4f}")
        
        save_daily_report(args.output, avg_score)
        print(f"Saved daily report to {args.output}")
    else:
        print("No texts fetched. Exiting.")

if __name__ == "__main__":
    main()
