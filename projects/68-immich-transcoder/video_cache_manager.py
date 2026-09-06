import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def parse_args(args=None):
    parser = argparse.ArgumentParser(description="Automated Immich Video Transcoding & H.265 Cache Manager")
    parser.add_argument("--input", type=str, help="Path to input video file")
    parser.add_argument("--cache-dir", type=str, required=True, help="Directory to store transcoded cache")
    parser.add_argument("--max-cache-gb", type=float, default=50.0, help="Maximum cache size in GB")
    parser.add_argument("--dry-run", action="store_true", help="Print commands instead of executing them")
    parser.add_argument("--clean-cache", action="store_true", help="Force clean cache to respect limit without encoding")
    return parser.parse_args(args)

def get_video_metadata(input_path: Path) -> dict:
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(input_path)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        logging.error(f"Error inspecting video metadata for {input_path}: {e}")
        return {}

def build_transcode_command(input_path: Path, output_path: Path) -> list:
    # Check for QSV hardware acceleration availability
    hw_accel_available = Path("/dev/dri").exists()
    
    cmd = [
        "ffmpeg",
        "-y"
    ]
    
    if hw_accel_available:
        cmd.extend(["-hwaccel", "qsv"])
        
    cmd.extend(["-i", str(input_path)])
    
    if hw_accel_available:
        cmd.extend([
            "-vf", "scale_qsv=w=-2:h=1080",
            "-c:v", "h264_qsv",
            "-preset", "fast"
        ])
    else:
        cmd.extend([
            "-vf", "scale=-2:1080",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23"
        ])
        
    cmd.extend([
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(output_path)
    ])
    
    return cmd

def prune_cache(cache_dir: Path, max_cache_gb: float, dry_run: bool = False):
    if not cache_dir.exists():
        return

    max_cache_bytes = max_cache_gb * 1024 * 1024 * 1024
    
    files = []
    total_size = 0
    for file_path in cache_dir.rglob("*"):
        if file_path.is_file():
            stat = file_path.stat()
            files.append((file_path, stat.st_atime, stat.st_size))
            total_size += stat.st_size

    if total_size <= max_cache_bytes:
        logging.info(f"Cache size ({total_size / 1e9:.2f} GB) is within limit ({max_cache_gb} GB).")
        return

    # Sort files by atime (oldest first)
    files.sort(key=lambda x: x[1])

    bytes_to_free = total_size - max_cache_bytes
    freed_bytes = 0

    logging.info(f"Cache limit exceeded. Attempting to free {bytes_to_free / 1e9:.2f} GB...")

    for file_path, atime, size in files:
        if freed_bytes >= bytes_to_free:
            break
        
        logging.info(f"Evicting {file_path} ({size / 1e6:.2f} MB)")
        if not dry_run:
            try:
                file_path.unlink()
                freed_bytes += size
            except Exception as e:
                logging.error(f"Failed to delete {file_path}: {e}")
        else:
            logging.info(f"[DRY-RUN] Would have deleted {file_path}")
            freed_bytes += size

    logging.info(f"Pruning complete. Freed {freed_bytes / 1e9:.2f} GB.")

def is_optimal(metadata: dict) -> bool:
    if not metadata or "streams" not in metadata:
        return False
        
    for stream in metadata["streams"]:
        if stream.get("codec_type") == "video":
            codec = stream.get("codec_name")
            height = stream.get("height", 9999)
            if codec in ("h264", "hevc") and height <= 1080:
                return True
    return False

def main():
    args = parse_args()
    
    cache_dir = Path(args.cache_dir)
    if not args.dry_run and not cache_dir.exists():
        cache_dir.mkdir(parents=True, exist_ok=True)
    
    if args.clean_cache:
        prune_cache(cache_dir, args.max_cache_gb, args.dry_run)
        if not args.input:
            return

    if args.input:
        input_path = Path(args.input)
        if not input_path.exists():
            logging.error(f"Input file not found: {input_path}")
            sys.exit(1)
            
        metadata = get_video_metadata(input_path)
        if not metadata:
            logging.warning("Could not read metadata. Proceeding anyway.")
            
        if is_optimal(metadata):
            logging.info(f"Video {input_path} is already optimal. Skipping transcode.")
        else:
            output_filename = input_path.stem + "_transcoded.mp4"
            output_path = cache_dir / output_filename
            
            cmd = build_transcode_command(input_path, output_path)
            
            logging.info(f"Transcoding {input_path} to {output_path}")
            if args.dry_run:
                logging.info(f"[DRY-RUN] Would run: {' '.join(cmd)}")
            else:
                try:
                    subprocess.run(cmd, check=True)
                    logging.info("Transcoding completed successfully.")
                except subprocess.CalledProcessError as e:
                    logging.error(f"Transcoding failed: {e}")
                    sys.exit(1)
            
        prune_cache(cache_dir, args.max_cache_gb, args.dry_run)

if __name__ == "__main__":
    main()
