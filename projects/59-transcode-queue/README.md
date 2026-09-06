# Project 59: Homelab Intelligent Media Transcode & AV1/HEVC Archive Queue

## Overview
A background media compressor that converts bloated raw camera recordings or downloads into high-efficiency HEVC/AV1 formats without disrupting homelab resources.

## Features
- **Intel N100 QuickSync (QSV) & CPU Throttling:** Utilizes hardware acceleration where possible, or falls back to `libx265`/`libsvtav1` software encoders with strict CPU throttling (`nice -n 15`). Ensures the host system (NAS/Pi) remains responsive for essential services (Plex/DNS).
- **Storage Tiering:** Implements a two-tier storage model. The temporary transcode buffer must reside on fast NVMe storage (or local `tmp`), followed by a single-stream sequential replacement onto mechanical HDDs to preserve hibernation states.
- **Zero Disruption:** Maps all streams and strictly copies audio tracks, subtitle tracks, and file metadata (creation date, EXIF) to preserve the original integrity.

## Architecture & Flow

```mermaid
graph TD
    A[Scan Directory] --> B{Check File Size & Codec}
    B -- Skip --> C[Ignore]
    B -- Matches (H264/MPEG-2, > Size limit) --> D[Transcode Queue]
    D --> E[Run FFmpeg on NVMe Buffer (nice -n 15)]
    E --> F{Check Exit Code & Output Size}
    F -- Failure --> G[Delete Tmp File & Log Error]
    F -- Success --> H[Sequential Atomic Replacement on Media Drive]
```

## FFmpeg Parameter Matrix

| Target Codec | QSV Hardware Encoder | Software Fallback Encoder | CRF Mapping |
| :--- | :--- | :--- | :--- |
| **HEVC** | `hevc_qsv` (via `-global_quality`) | `libx265` (via `-crf`) | Default: 23 |
| **AV1** | `av1_qsv` (via `-global_quality`) | `libsvtav1` (via `-crf`) | Default: 23 |

All encodes enforce single-stream maps: `-map 0 -c:a copy -c:s copy -map_metadata 0`.

## Hardware Acceleration Guide
This daemon utilizes Intel QuickSync Video (QSV) explicitly to optimize CPU load on nodes like an Intel N100 or a Celeron-based NAS.
- **Initialization:** FFmpeg uses `-init_hw_device qsv=hw -filter_hw_device hw`.
- **Fallback Logic:** If QSV encoding fails (e.g., driver missing, codec unoptimized, or container missing `/dev/dri` pass-through), the daemon safely logs the failure, deletes any corrupt partial output, and seamlessly falls back to CPU-bound software encoding via `libx265` or `libsvtav1` throttled strictly with `nice -n 15`.

## Setup & Deployment
1. Ensure the host provides `/dev/dri` access to utilize Intel QSV.
2. Configure environment variables in `docker-compose.yml` for watch directories and NVMe buffers.
3. Deploy with Docker Compose: `docker-compose up -d --build`
