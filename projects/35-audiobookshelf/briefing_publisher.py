import os
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime
import json
import urllib.request
from email.utils import formatdate

class BriefingPublisher:
    def __init__(self, library_dir="/volume2/audiobookshelf", webhook_url=None):
        self.library_dir = library_dir
        self.podcasts_dir = os.path.join(self.library_dir, "podcasts")
        self.audiobooks_dir = os.path.join(self.library_dir, "audiobooks")
        self.webhook_url = webhook_url

    def validate_audio(self, file_path):
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Audio file not found: {file_path}")
        if not (file_path.endswith('.mp3') or file_path.endswith('.m4b')):
            raise ValueError(f"Invalid audio format. Must be .mp3 or .m4b: {file_path}")
        return True

    def tag_metadata(self, file_path, metadata):
        try:
            from mutagen.mp3 import MP3
            from mutagen.id3 import ID3, TIT2, TPE1, TALB
            from mutagen.mp4 import MP4

            if file_path.endswith('.mp3'):
                try:
                    audio = MP3(file_path, ID3=ID3)
                except Exception:
                    audio = MP3(file_path)
                    audio.add_tags()

                if 'title' in metadata:
                    audio.tags.add(TIT2(encoding=3, text=metadata['title']))
                if 'artist' in metadata:
                    audio.tags.add(TPE1(encoding=3, text=metadata['artist']))
                if 'series' in metadata:
                    audio.tags.add(TALB(encoding=3, text=metadata['series']))
                audio.save()

            elif file_path.endswith('.m4b'):
                audio = MP4(file_path)
                if 'title' in metadata:
                    audio.tags['\xa9nam'] = [metadata['title']]
                if 'artist' in metadata:
                    audio.tags['\xa9ART'] = [metadata['artist']]
                if 'series' in metadata:
                    audio.tags['\xa9alb'] = [metadata['series']]
                audio.save()

        except Exception as e:
            print(f"Failed to tag metadata: {e}")

    def create_rss_feed(self, podcast_name, feed_file):
        rss = ET.Element("rss", version="2.0", xmlns__itunes="http://www.itunes.com/dtds/podcast-1.0.dtd")
        channel = ET.SubElement(rss, "channel")
        ET.SubElement(channel, "title").text = podcast_name
        ET.SubElement(channel, "description").text = f"Automated Morning Briefing: {podcast_name}"
        ET.SubElement(channel, "link").text = "http://localhost:13378"

        tree = ET.ElementTree(rss)
        tree.write(feed_file, encoding='utf-8', xml_declaration=True)

    def update_rss_feed(self, feed_file, item_metadata):
        tree = ET.parse(feed_file)
        root = tree.getroot()
        channel = root.find("channel")

        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = item_metadata.get('title', 'Morning Briefing')
        ET.SubElement(item, "description").text = item_metadata.get('description', 'Daily briefing audio.')
        ET.SubElement(item, "pubDate").text = formatdate(timeval=None, localtime=False, usegmt=True)

        enclosure = ET.SubElement(item, "enclosure")
        enclosure.set("url", item_metadata.get('url', ''))
        enclosure.set("type", "audio/mpeg")
        enclosure.set("length", str(item_metadata.get('size', 0)))

        tree.write(feed_file, encoding='utf-8', xml_declaration=True)
        return True

    def publish_briefing(self, audio_file, metadata, is_podcast=True):
        self.validate_audio(audio_file)
        self.tag_metadata(audio_file, metadata)

        # Determine destination
        dest_base = self.podcasts_dir if is_podcast else self.audiobooks_dir
        dest_dir = os.path.join(dest_base, metadata.get('series', 'Morning Briefing'))
        os.makedirs(dest_dir, exist_ok=True)

        filename = os.path.basename(audio_file)
        dest_path = os.path.join(dest_dir, filename)

        shutil.copy2(audio_file, dest_path)

        # Handle RSS if podcast
        if is_podcast:
            feed_file = os.path.join(dest_dir, "feed.xml")
            if not os.path.exists(feed_file):
                self.create_rss_feed(metadata.get('series', 'Morning Briefing'), feed_file)

            item_metadata = {
                'title': metadata.get('title', 'Briefing'),
                'description': metadata.get('description', ''),
                'url': f"http://localhost:13378/podcasts/{metadata.get('series', 'Morning Briefing')}/{filename}",
                'size': os.path.getsize(dest_path)
            }
            self.update_rss_feed(feed_file, item_metadata)

        # Webhook
        if self.webhook_url:
            self.send_webhook(metadata)

        return dest_path

    def send_webhook(self, metadata):
        data = json.dumps({"text": f"New briefing published: {metadata.get('title')}"}).encode('utf-8')
        req = urllib.request.Request(self.webhook_url, data=data, headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req) as response:
                return response.status == 200
        except Exception as e:
            print(f"Webhook failed: {e}")
            return False

if __name__ == "__main__":
    # Example usage
    publisher = BriefingPublisher()
    # publisher.publish_briefing("test.mp3", {"title": "Today's Brief", "series": "Daily Updates"})
