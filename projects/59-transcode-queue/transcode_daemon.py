import argparse
import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

def probe_file(filepath: Path) -> Optional[Dict]:
    """Uses ffprobe to analyze the file and return its streams and format info."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(filepath)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        logger.error(f"Failed to probe file {filepath}: {e}")
        return None

def needs_transcode(filepath: Path, min_size_mb: int, target_codec: str) -> bool:
    """Determine if a file needs transcoding based on size OR legacy codec.
    Skips if the file is already encoded in the target codec."""
    if not filepath.exists():
        return False

    info = probe_file(filepath)
    if not info:
        return False

    # Check if it's already in the target codec
    is_already_target = False
    for stream in info.get("streams", []):
        if stream.get("codec_type") == "video":
            codec = stream.get("codec_name")
            if codec == target_codec:
                is_already_target = True

            # If we find a legacy codec, we should probably transcode it anyway
            if codec in ["h264", "mpeg2video"]:
                return True

    if is_already_target:
        return False

    # Check size threshold
    size_mb = filepath.stat().st_size / (1024 * 1024)
    if size_mb >= min_size_mb:
        return True

    return False

def run_transcode(input_file: Path, output_file: Path, codec: str, crf: int) -> bool:
    """Runs ffmpeg for transcoding, using nice -n 15 for CPU throttling.
    Attempts QSV hardware acceleration first, falling back to software encoding on failure."""

    qsv_encoder = "hevc_qsv" if codec == "hevc" else "av1_qsv"
    sw_encoder = "libx265" if codec == "hevc" else "libsvtav1"

    def get_cmd(encoder: str) -> List[str]:
        cmd = [
            "nice", "-n", "15",
            "ffmpeg", "-y",
            "-init_hw_device", "qsv=hw", "-filter_hw_device", "hw",
            "-i", str(input_file),
            "-map", "0",
            "-c:v", encoder
        ]

        # CRF handling varies slightly between QSV and SW
        if "qsv" in encoder:
            cmd.extend(["-global_quality", str(crf)])
        else:
            cmd.extend(["-crf", str(crf)])

        cmd.extend([
            "-c:a", "copy",
            "-c:s", "copy",
            "-map_metadata", "0",
            str(output_file)
        ])
        return cmd

    # Attempt QSV first
    logger.info(f"Attempting hardware-accelerated QSV transcode ({qsv_encoder})...")
    try:
        result = subprocess.run(get_cmd(qsv_encoder), capture_output=True, text=True)
        if result.returncode == 0:
            logger.info("QSV Transcode successful.")
            return True
        else:
            logger.warning(f"QSV Transcode failed with code {result.returncode}. Output: {result.stderr}")
    except Exception as e:
        logger.warning(f"Error during QSV transcode attempt: {e}")

    # Fallback to software encoding
    logger.info(f"Falling back to software transcode ({sw_encoder})...")
    # Clean up potentially corrupt partial output file from failed QSV attempt
    if output_file.exists():
        output_file.unlink()

    # Remove QSV-specific initialization flags for SW encode
    sw_cmd = [
        "nice", "-n", "15",
        "ffmpeg", "-y",
        "-i", str(input_file),
        "-map", "0",
        "-c:v", sw_encoder,
        "-crf", str(crf),
        "-c:a", "copy",
        "-c:s", "copy",
        "-map_metadata", "0",
        str(output_file)
    ]
    logger.info(f"Running SW transcode: {' '.join(sw_cmd)}")

    try:
        result = subprocess.run(sw_cmd, check=True)
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        logger.error(f"Software Transcode failed with code {e.returncode}")
        return False
    except Exception as e:
        logger.error(f"Error during SW transcode: {e}")
        return False

def replace_atomic(original_file: Path, transcoded_file: Path, dry_run: bool = False) -> bool:
    """Verifies the transcoded file and atomically replaces the original across devices."""
    if not transcoded_file.exists():
        logger.error("Transcoded file does not exist, aborting replacement.")
        return False

    if transcoded_file.stat().st_size == 0:
        logger.error("Transcoded file is empty, aborting replacement.")
        return False

    logger.info(f"Replacing {original_file} with {transcoded_file}")

    if dry_run:
        logger.info("[DRY RUN] Would replace file.")
        return True

    try:
        # Cross-device atomic replacement:
        # 1. Copy to a hidden tmp file in the destination directory
        # 2. os.rename (which is atomic on the same filesystem) over the original file
        dest_tmp = original_file.parent / f".tmp_{transcoded_file.name}"
        shutil.copy2(str(transcoded_file), str(dest_tmp))
        os.rename(str(dest_tmp), str(original_file))

        # Clean up original buffer file
        transcoded_file.unlink(missing_ok=True)
        return True
    except Exception as e:
        logger.error(f"Failed to replace file: {e}")
        # Attempt cleanup of dest tmp file if failure occurred
        if 'dest_tmp' in locals() and dest_tmp.exists():
            dest_tmp.unlink()
        return False

def process_queue(args):
    watch_dir = Path(args.watch_dir)
    tmp_dir = Path(args.tmp_dir)

    if not watch_dir.exists():
        logger.error(f"Watch dir {watch_dir} does not exist.")
        return

    tmp_dir.mkdir(parents=True, exist_ok=True)

    for filepath in watch_dir.rglob("*"):
        if not filepath.is_file():
            continue

        if filepath.suffix.lower() not in [".mp4", ".mkv", ".avi", ".mov"]:
            continue

        if needs_transcode(filepath, args.min_size_mb, args.codec):
            logger.info(f"Queuing for transcode: {filepath}")

            # Temporary file on fast storage.
            # Force mkv extension for legacy formats to prevent muxing issues.
            target_ext = filepath.suffix.lower()
            if target_ext not in [".mp4", ".mkv"]:
                target_ext = ".mkv"

            tmp_output = tmp_dir / f"transcoded_{filepath.stem}{target_ext}"

            if args.dry_run:
                logger.info(f"[DRY RUN] Would transcode {filepath} to {tmp_output}")
                continue

            success = run_transcode(filepath, tmp_output, args.codec, args.crf)

            if success:
                logger.info(f"Transcode successful for {filepath}")
                # If extension changed, original file becomes the new stem + new extension
                target_final = filepath.with_suffix(target_ext)
                success_replace = replace_atomic(target_final, tmp_output, args.dry_run)

                # Clean up old legacy file if extension changed and replace was successful
                if success_replace and filepath != target_final and not args.dry_run:
                    filepath.unlink(missing_ok=True)
            else:
                logger.error(f"Transcode failed for {filepath}. Cleaning up.")
                if tmp_output.exists():
                    tmp_output.unlink()

def parse_args():
    parser = argparse.ArgumentParser(description="Homelab Intelligent Media Transcode Queue")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without executing")
    parser.add_argument("--codec", choices=["hevc", "av1"], default="hevc", help="Target codec")
    parser.add_argument("--crf", type=int, default=23, help="CRF value for encoding")
    parser.add_argument("--min-size-mb", type=int, default=500, help="Minimum file size in MB to consider")
    parser.add_argument("--watch-dir", type=str, required=True, help="Directory to watch for media")
    parser.add_argument("--tmp-dir", type=str, default="/tmp", help="Temporary transcode buffer directory (e.g., NVMe)")
    parser.add_argument("--scan-interval", type=int, default=3600, help="Interval in seconds between directory scans")
    return parser.parse_args()

def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    args = parse_args()
    logger.info(f"Started transcode queue for {args.watch_dir}. Scanning every {args.scan_interval}s.")

    while True:
        try:
            logger.info("Starting new directory scan...")
            process_queue(args)
            logger.info(f"Scan complete. Sleeping for {args.scan_interval} seconds to allow HDD hibernation.")
            time.sleep(args.scan_interval)
        except KeyboardInterrupt:
            logger.info("Transcode daemon stopped by user.")
            break
        except Exception as e:
            logger.error(f"Unexpected error in daemon loop: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
