import datetime
import logging
import os
import requests
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

class MorningBriefing:
    def __init__(self, rss_url="https://feeds.npr.org/500005/podcast.xml", output_dir="/mnt/nas/media_vault"):
        self.rss_url = rss_url
        self.output_dir = output_dir

    def fetch_latest_headlines(self, max_items=5) -> list:
        headlines = []
        try:
            resp = requests.get(self.rss_url, timeout=10, headers={"User-Agent": "Pi5-Briefing/1.0"})
            if resp.status_code == 200:
                root = ET.fromstring(resp.content)
                for item in root.findall('.//item')[:max_items]:
                    title = item.find('title')
                    desc = item.find('description')
                    t_text = title.text if title is not None else ""
                    d_text = desc.text if desc is not None else ""
                    if t_text:
                        headlines.append({"title": t_text, "description": d_text})
        except Exception as e:
            logger.warning(f"Could not fetch RSS: {e}")
            headlines = [
                {"title": "Morning Briefing Offline Mode", "description": "Network connection unavailable or feed offline."}
            ]
        return headlines

    def generate_briefing(self, headlines: list, sentiment_score: float = 0.0) -> str:
        date_str = datetime.date.today().strftime("%A, %B %d, %Y")
        report = []
        report.append(f"# ☀️ Morning Briefing — {date_str}")
        report.append(f"**Market Sentiment Indicator**: {sentiment_score:+.2f}")
        report.append("\n## 📰 Top News Highlights")
        for i, item in enumerate(headlines, 1):
            report.append(f"{i}. **{item['title']}**")
            if item.get('description'):
                report.append(f"   {item['description'][:200]}...")
        return "\n".join(report)

    def run(self, sentiment_score=0.15) -> str:
        headlines = self.fetch_latest_headlines()
        briefing_text = self.generate_briefing(headlines, sentiment_score)
        os.makedirs(self.output_dir, exist_ok=True)
        out_file = os.path.join(self.output_dir, f"briefing_{datetime.date.today().isoformat()}.md")
        try:
            with open(out_file, 'w', encoding='utf-8') as f:
                f.write(briefing_text)
        except Exception as e:
            logger.warning(f"Could not write to {out_file}: {e}")
        return briefing_text
