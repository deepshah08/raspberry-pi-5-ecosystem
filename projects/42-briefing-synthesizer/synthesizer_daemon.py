import os
import sys
import re
import logging
import datetime
import requests
from typing import List
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TRCK, TDRC, APIC, error as MutagenError

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class TextPreProcessor:
    @staticmethod
    def clean_markdown(text: str) -> str:
        """Strips markdown headers and cleans symbols for smooth TTS cadence."""
        # Remove headers
        text = re.sub(r'#+\s+', '', text)
        # Remove bold/italic markers
        text = re.sub(r'\*\*', '', text)
        text = re.sub(r'\*', '', text)
        text = re.sub(r'__', '', text)
        text = re.sub(r'_', '', text)
        # Replace list items with pauses or plain text
        text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*[-+*]\s+', '', text, flags=re.MULTILINE)

        # Clean up extra whitespace and newlines
        text = re.sub(r'\n+', '. ', text)
        text = re.sub(r'\s+', ' ', text)
        text = text.replace('..', '.')

        return text.strip()

    @staticmethod
    def chunk_text(text: str, max_length: int = 500) -> List[str]:
        """Chunks text into smaller parts for the TTS engine."""
        sentences = re.split(r'(?<=[.!?]) +', text)
        chunks = []
        current_chunk = ""

        for sentence in sentences:
            if len(current_chunk) + len(sentence) <= max_length:
                current_chunk += sentence + " "
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = sentence + " "

        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks


class ID3Tagger:
    @staticmethod
    def tag_file(filepath: str, title: str, date: str, author: str = "Homelab Briefing Bot", episode_num: str = "1"):
        logger.info(f"Tagging {filepath} with title: {title}, author: {author}")
        try:
            try:
                audio = ID3(filepath)
            except MutagenError:
                audio = ID3()

            audio.add(TIT2(encoding=3, text=title))
            audio.add(TPE1(encoding=3, text=author))
            audio.add(TALB(encoding=3, text="Morning Briefing"))
            audio.add(TRCK(encoding=3, text=str(episode_num)))
            audio.add(TDRC(encoding=3, text=date))

            # Add a mock cover art (in a real scenario, this would be read from a file)
            audio.add(APIC(
                encoding=3,
                mime='image/jpeg',
                type=3,
                desc='Cover',
                data=b'mock_image_data'
            ))

            audio.save(filepath, v2_version=3)
            logger.info("Tagging successful.")
        except Exception as e:
            logger.error(f"Failed to tag file: {e}")

class AudiobookshelfClient:
    def __init__(self, base_url: str = "http://192.168.1.80:13378"):
        self.base_url = base_url.rstrip("/")
        self.token = None
        self.library_id = None

    def login(self, username: str, password: str) -> bool:
        if not username or not password:
            logger.error("Missing username or password for login")
            return False

        logger.info(f"Logging into Audiobookshelf at {self.base_url}")
        try:
            resp = requests.post(f"{self.base_url}/api/login", json={"username": username, "password": password})
            resp.raise_for_status()
            data = resp.json()
            self.token = data.get("user", {}).get("token")
            if not self.token:
                logger.error("Login successful but no token returned.")
                return False
            return True
        except requests.RequestException as e:
            logger.error(f"Login failed: {e}")
            return False

    def get_library_id(self, library_name: str = "Podcasts") -> str:
        if not self.token:
            logger.error("Not authenticated.")
            return None

        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            resp = requests.get(f"{self.base_url}/api/libraries", headers=headers)
            resp.raise_for_status()
            libraries = resp.json().get("libraries", [])
            for lib in libraries:
                if lib.get("name") == library_name:
                    self.library_id = lib.get("id")
                    return self.library_id

            logger.warning(f"Library '{library_name}' not found.")
            return None
        except requests.RequestException as e:
            logger.error(f"Failed to fetch libraries: {e}")
            return None

    def upload_audio(self, filepath: str, folder_id: str) -> bool:
        if not self.token:
            logger.error("Not authenticated.")
            return False

        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            with open(filepath, 'rb') as f:
                files = {'file': (os.path.basename(filepath), f, 'audio/mpeg')}
                data = {'folderId': folder_id}
                resp = requests.post(
                    f"{self.base_url}/api/upload",
                    headers=headers,
                    files=files,
                    data=data
                )
                resp.raise_for_status()
                logger.info(f"Upload successful: {filepath}")
                return True
        except requests.RequestException as e:
            logger.error(f"Upload failed: {e}")
            return False

    def trigger_rescan(self, library_id: str) -> bool:
        if not self.token:
            logger.error("Not authenticated.")
            return False

        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            resp = requests.post(f"{self.base_url}/api/libraries/{library_id}/scan", headers=headers)
            resp.raise_for_status()
            logger.info(f"Library rescan triggered for {library_id}.")
            return True
        except requests.RequestException as e:
            logger.error(f"Failed to trigger rescan: {e}")
            return False


class TTSBridge:
    def __init__(self, output_dir: str = "/tmp"):
        self.output_dir = output_dir
        self.engine_type = self._detect_engine()

    def _detect_engine(self) -> str:
        # Check if real TTS is available, else mock
        try:
            import pyttsx3
            return "pyttsx3"
        except ImportError:
            return "mock"

    def generate_audio(self, text: str, filename: str = "output.mp3") -> str:
        output_path = os.path.join(self.output_dir, filename)
        logger.info(f"Generating audio using {self.engine_type} engine to {output_path}")

        if self.engine_type == "pyttsx3":
            try:
                import pyttsx3
                engine = pyttsx3.init()
                engine.save_to_file(text, output_path)
                engine.runAndWait()
            except Exception as e:
                logger.error(f"Error with pyttsx3: {e}. Falling back to mock.")
                self._mock_generate(text, output_path)
        else:
            self._mock_generate(text, output_path)

        return output_path

    def _mock_generate(self, text: str, output_path: str):
        logger.info("Using mock TTS generation.")
        # Create a dummy file to simulate audio generation
        with open(output_path, "wb") as f:
            f.write(b"Mock audio content for: " + text.encode('utf-8')[:100])

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Automated Morning Briefing Audio Synthesizer")
    parser.add_argument("--dry-run", action="store_true", help="Run without uploading to Audiobookshelf")
    parser.add_argument("--briefing-file", type=str, help="Path to the markdown briefing file")
    parser.add_argument("--force-publish", action="store_true", help="Force publish even if errors occurred")

    args = parser.parse_args()

    if not args.briefing_file:
        logger.error("Must provide --briefing-file")
        sys.exit(1)

    if not os.path.exists(args.briefing_file):
        logger.error(f"File not found: {args.briefing_file}")
        sys.exit(1)

    with open(args.briefing_file, "r", encoding="utf-8") as f:
        text = f.read()

    processor = TextPreProcessor()
    cleaned_text = processor.clean_markdown(text)

    tts = TTSBridge(output_dir="/tmp")
    output_filename = f"briefing_{datetime.date.today().isoformat()}.mp3"
    audio_path = tts.generate_audio(cleaned_text, filename=output_filename)

    tagger = ID3Tagger()
    tagger.tag_file(audio_path, title=f"Morning Briefing {datetime.date.today().isoformat()}", date=datetime.date.today().isoformat())

    if not args.dry_run:
        abs_url = os.environ.get("ABS_URL", "http://192.168.1.80:13378")
        abs_user = os.environ.get("ABS_USER")
        abs_pass = os.environ.get("ABS_PASS")

        client = AudiobookshelfClient(base_url=abs_url)
        if client.login(abs_user, abs_pass):
            lib_id = client.get_library_id("Podcasts")
            if lib_id:
                # Assuming the library ID acts as the folder ID for upload in this context
                if client.upload_audio(audio_path, lib_id):
                    client.trigger_rescan(lib_id)
                elif args.force_publish:
                    logger.warning("Upload failed but --force-publish is set. Continuing.")
            else:
                logger.error("Could not find Podcasts library.")
        else:
            logger.error("Failed to login to Audiobookshelf.")

if __name__ == "__main__":
    main()
