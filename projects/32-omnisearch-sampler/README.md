# OmniSearch Keyframe Extractor & Media Sampler

This module (`sampler.py`) implements a high-throughput asynchronous media sampler designed as the first stage in the OmniSearch pipeline. It recursively scans configured media directories, performing extraction of representative keyframes for videos and ingesting photos.

## Architecture & Zero-Copy Pipeline

The sampler is optimized for performance by reading directly from read-only mounts (e.g., `/volume1/media`, `/volume2`). To avoid heavy disk I/O, it implements a "zero-copy" approach in its design by not copying full files into processing environments:

1.  **Deduplication via Pseudo-Hashing:** Full content hashing (e.g., SHA-256) of large media files (movies, TV shows) is prohibitively slow. Instead, the sampler computes a fast pseudo-hash based on the file path, size in bytes, and last modification time. This prevents reprocessing the same files across pipeline restarts. State is persisted to a lightweight JSON file.
2.  **Asynchronous Non-Blocking Execution:** Directory traversal, photo staging, and video keyframe extraction are handled concurrently via Python's `asyncio`. Spawning `ffmpeg` via `asyncio.create_subprocess_exec` prevents the main event loop from blocking during video decoding.
3.  **Lightweight Queueing:** Extracted thumbnails and metadata (including file paths, timestamps in seconds, and title strings derived from filenames) are pushed to an in-memory `asyncio.Queue`, ready to be consumed by downstream embedding workers.

## FFmpeg Optimization Parameters

For video files, the goal is to extract meaningful frames without decoding the entire stream. We use `ffmpeg` with specific filters to target scene changes (I-frames):

*   `-vf "select='gt(scene,0.4)',showinfo"`:
    *   `select='gt(scene,0.4)'`: This video filter evaluates the visual difference between sequential frames. It only selects frames where the "scene change score" is greater than 0.4 (40% difference). This efficiently skips long static shots and outputs only visually distinct frames.
    *   `showinfo`: This filter outputs metadata about each selected frame to `stderr`. The sampler parses this output to retrieve the precise `pts_time` (presentation timestamp in seconds) for each extracted JPEG.
*   `-vsync vfr`: Sets the video synchronization method to Variable Frame Rate. This ensures `ffmpeg` only writes the selected frames to disk, rather than duplicating frames to match the original frame rate.
*   `-q:v 2`: Sets a high JPEG quality level for the output thumbnails, balancing file size with visual fidelity necessary for accurate downstream vector embeddings.

## Usage

(Assuming integration into a larger async workflow)
```python
import asyncio
from sampler import MediaSampler

async def main():
    sampler = MediaSampler(output_dir="./staging_frames")

    # Start scanning paths
    scan_task = asyncio.create_task(sampler.scan_paths(["/volume1/media", "/volume2"]))

    # Process queue (example)
    while True:
        try:
            file_path, timestamp, title, frame_path = await asyncio.wait_for(sampler.queue.get(), timeout=1.0)
            print(f"Sampled: {title} at {timestamp}s -> {frame_path}")
            sampler.queue.task_done()
        except asyncio.TimeoutError:
            if scan_task.done():
                break

if __name__ == "__main__":
    asyncio.run(main())
```