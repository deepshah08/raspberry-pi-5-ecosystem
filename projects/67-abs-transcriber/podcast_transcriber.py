import argparse
import logging
import os
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class Episode:
    title: str
    pub_date: str
    audio_url: str
    filename: str

class FeedScraper:
    def __init__(self, feed_url: str):
        self.feed_url = feed_url

    def fetch_and_parse(self, limit: Optional[int] = None) -> List[Episode]:
        logger.info(f"Fetching RSS feed from: {self.feed_url}")
        try:
            req = urllib.request.Request(self.feed_url, headers={'User-Agent': 'PodcastTranscriber/1.0'})
            with urllib.request.urlopen(req) as response:
                xml_content = response.read()
        except urllib.error.URLError as e:
            logger.error(f"Failed to fetch feed: {e}")
            # Mocking it for test if necessary or simply raise
            xml_content = b""

        return self.parse_xml(xml_content, limit)

    def parse_xml(self, xml_content: bytes, limit: Optional[int] = None) -> List[Episode]:
        episodes = []
        if not xml_content:
            return episodes
        try:
            root = ET.fromstring(xml_content)
            channel = root.find("channel")
            if channel is None:
                return episodes
            
            items = channel.findall("item")
            for item in items:
                if limit is not None and len(episodes) >= limit:
                    break
                
                title_elem = item.find("title")
                title = title_elem.text if title_elem is not None else "Unknown Title"
                
                pub_date_elem = item.find("pubDate")
                pub_date = pub_date_elem.text if pub_date_elem is not None else ""
                
                enclosure = item.find("enclosure")
                if enclosure is not None and enclosure.get("url"):
                    audio_url = enclosure.get("url")
                    
                    # Create a safe filename
                    safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
                    safe_title = safe_title.replace(' ', '_')
                    ext = audio_url.split('.')[-1]
                    if ext not in ['mp3', 'm4a', 'wav']:
                        ext = 'mp3' # default
                    
                    filename = f"{safe_title}.{ext}"
                    episodes.append(Episode(title=title, pub_date=pub_date, audio_url=audio_url, filename=filename))
        except ET.ParseError as e:
            logger.error(f"Failed to parse XML: {e}")
            
        return episodes

class Downloader:
    def __init__(self, output_dir: Path, rate_limit_kbps: int = 500):
        self.output_dir = output_dir
        self.rate_limit_kbps = rate_limit_kbps
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
    def download(self, episode: Episode, dry_run: bool = False) -> Optional[Path]:
        output_path = self.output_dir / episode.filename
        if dry_run:
            logger.info(f"[DRY-RUN] Would download {episode.audio_url} to {output_path}")
            return output_path
            
        logger.info(f"Downloading {episode.title} to {output_path}")
        
        try:
            req = urllib.request.Request(episode.audio_url, headers={'User-Agent': 'PodcastTranscriber/1.0'})
            with urllib.request.urlopen(req) as response:
                with open(output_path, 'wb') as f:
                    # chunk based rate limiting
                    chunk_size = 1024 * 8 # 8KB chunks
                    while True:
                        start_time = time.time()
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        
                        # Calculate time taken and sleep if we are too fast
                        elapsed = time.time() - start_time
                        expected_time = len(chunk) / (self.rate_limit_kbps * 1024)
                        if elapsed < expected_time:
                            time.sleep(expected_time - elapsed)
            return output_path
        except urllib.error.URLError as e:
            logger.error(f"Failed to download {episode.audio_url}: {e}")
            return None

class Transcriber:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        
    def transcribe(self, episode: Episode, dry_run: bool = False) -> Optional[Path]:
        base_name = os.path.splitext(episode.filename)[0]
        vtt_path = self.output_dir / f"{base_name}.vtt"
        
        if dry_run:
            logger.info(f"[DRY-RUN] Would transcribe {episode.filename} to {vtt_path}")
            return vtt_path
            
        logger.info(f"Generating transcript for {episode.title} to {vtt_path}")
        
        # Mock transcription generator
        vtt_content = "WEBVTT\n\n"
        vtt_content += "1\n"
        vtt_content += "00:00:00.000 --> 00:00:05.000\n"
        vtt_content += f"Welcome to {episode.title}!\n\n"
        vtt_content += "2\n"
        vtt_content += "00:00:05.000 --> 00:00:10.000\n"
        vtt_content += f"Published on {episode.pub_date}.\n"
        
        with open(vtt_path, 'w', encoding='utf-8') as f:
            f.write(vtt_content)
            
        return vtt_path

def main():
    parser = argparse.ArgumentParser(description="Audiobookshelf Podcast RSS Scraper & Transcriber")
    parser.add_argument("--feed-url", type=str, required=True, help="URL of the podcast RSS feed")
    parser.add_argument("--output-dir", type=str, required=True, help="Directory to save audio and transcripts")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of episodes to process")
    parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without downloading or writing files")
    
    args = parser.parse_args()
    
    output_dir = Path(args.output_dir)
    
    scraper = FeedScraper(args.feed_url)
    episodes = scraper.fetch_and_parse(limit=args.limit)
    
    if not episodes:
        logger.info("No episodes found or failed to fetch.")
        return
        
    downloader = Downloader(output_dir)
    transcriber = Transcriber(output_dir)
    
    for episode in episodes:
        logger.info(f"Processing episode: {episode.title}")
        downloaded_path = downloader.download(episode, dry_run=args.dry_run)
        if downloaded_path or args.dry_run:
            transcriber.transcribe(episode, dry_run=args.dry_run)

if __name__ == "__main__":
    main()
