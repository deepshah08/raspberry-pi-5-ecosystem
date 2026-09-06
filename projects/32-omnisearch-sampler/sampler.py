import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import List, Tuple, Set

logger = logging.getLogger(__name__)

class MediaSampler:
    def __init__(self, output_dir: str, state_file: str = "sampler_state.json"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = Path(state_file)
        self.processed_hashes: Set[str] = set()
        self.queue: asyncio.Queue[Tuple[str, float, str, str]] = asyncio.Queue()
        self.load_state()

    def load_state(self) -> None:
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    self.processed_hashes = set(data.get("processed_hashes", []))
            except Exception as e:
                logger.error(f"Error loading state: {e}")

    def save_state(self) -> None:
        try:
            with open(self.state_file, 'w') as f:
                json.dump({"processed_hashes": list(self.processed_hashes)}, f)
        except Exception as e:
            logger.error(f"Error saving state: {e}")

    def compute_file_hash(self, file_path: Path) -> str:
        """Computes a pseudo-hash based on file path, size, and mtime for deduplication."""
        stat = file_path.stat()
        hash_input = f"{file_path.absolute()}_{stat.st_size}_{stat.st_mtime}"
        return hashlib.md5(hash_input.encode()).hexdigest()

    async def scan_paths(self, paths: List[str]) -> None:
        """Scans directories recursively for media files and processes them."""
        media_extensions = {".mp4", ".mkv", ".avi", ".mov", ".jpg", ".jpeg", ".png"}

        for base_path in paths:
            path_obj = Path(base_path)
            if not path_obj.exists():
                logger.warning(f"Path does not exist: {base_path}")
                continue

            for root, _, files in os.walk(base_path):
                for file in files:
                    file_path = Path(root) / file
                    if file_path.suffix.lower() in media_extensions:
                        await self.process_file(file_path)

    async def process_file(self, file_path: Path) -> None:
        file_hash = self.compute_file_hash(file_path)
        if file_hash in self.processed_hashes:
            logger.info(f"Skipping already processed file: {file_path}")
            return

        if file_path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            await self.process_photo(file_path)
        else:
            await self.extract_keyframes(file_path, file_hash)

        self.processed_hashes.add(file_hash)
        self.save_state()

    async def process_photo(self, file_path: Path) -> None:
        """Processes a photo by pushing it directly to the queue."""
        title = file_path.stem
        await self.queue.put((str(file_path), 0.0, title, str(file_path)))

    async def extract_keyframes(self, file_path: Path, file_hash: str) -> None:
        """Extracts scene change keyframes from a video using ffmpeg."""
        title = file_path.stem
        output_pattern = self.output_dir / f"{file_hash}_frame_%04d.jpg"

        # ffmpeg command to extract I-frames / scene changes
        cmd = [
            "ffmpeg",
            "-i", str(file_path),
            "-vf", "select='gt(scene,0.4)',showinfo",
            "-vsync", "vfr",
            "-q:v", "2",
            str(output_pattern)
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            logger.error(f"FFmpeg failed for {file_path}:\n{stderr.decode() if stderr else ''}")
            return

        stderr_output = stderr.decode() if stderr else ""
        timestamps = self._parse_ffmpeg_showinfo(stderr_output)

        for i, ts in enumerate(timestamps):
            frame_path = self.output_dir / f"{file_hash}_frame_{i+1:04d}.jpg"
            await self.queue.put((str(file_path), ts, title, str(frame_path)))

    def _parse_ffmpeg_showinfo(self, stderr: str) -> List[float]:
        """Parses ffmpeg showinfo output to extract frame timestamps."""
        timestamps = []
        for line in stderr.splitlines():
            if "pts_time:" in line:
                try:
                    parts = line.split("pts_time:")
                    if len(parts) > 1:
                        time_str = parts[1].split()[0]
                        timestamps.append(float(time_str))
                except ValueError:
                    continue
        return timestamps
