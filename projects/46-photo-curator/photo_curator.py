import argparse
import datetime
import io
import json
import logging
import os
import re
import typing
from urllib.parse import urljoin

import requests
from PIL import Image

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class ImmichClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "x-api-key": self.api_key
        })

    def get_assets(self, limit: int = None) -> typing.Iterator[dict]:
        url = urljoin(self.base_url, "/api/assets")
        logger.info(f"Fetching assets from {url}")

        skip = 0
        take = 500  # Default pagination limit
        yielded = 0

        while True:
            params = {"isTrashed": False, "skip": skip, "take": take}
            response = self.session.get(url, params=params)
            response.raise_for_status()
            assets = response.json()

            if not assets:
                break

            for asset in assets:
                if limit and yielded >= limit:
                    return
                yield asset
                yielded += 1

            if len(assets) < take:
                break

            skip += take

    def get_thumbnail(self, asset_id: str) -> bytes:
        url = urljoin(self.base_url, f"/api/assets/{asset_id}/thumbnail")
        response = self.session.get(url, stream=True)
        response.raise_for_status()
        return response.content


class ImageHasher:
    @staticmethod
    def compute_dhash(image: Image.Image, hash_size: int = 8) -> str:
        # Convert to grayscale and resize
        image = image.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
        pixels = list(image.getdata())

        # Calculate differences between adjacent pixels
        difference = []
        for row in range(hash_size):
            for col in range(hash_size):
                pixel_left = pixels[row * (hash_size + 1) + col]
                pixel_right = pixels[row * (hash_size + 1) + col + 1]
                difference.append(pixel_left > pixel_right)

        # Convert to hex string
        decimal_value = 0
        hex_string = []
        for index, value in enumerate(difference):
            if value:
                decimal_value += 2**(index % 8)
            if (index % 8) == 7:
                hex_string.append(hex(decimal_value)[2:].rjust(2, '0'))
                decimal_value = 0

        return "".join(hex_string)

    @staticmethod
    def hamming_distance(hash1: str, hash2: str) -> int:
        if len(hash1) != len(hash2):
            raise ValueError("Hashes must be of equal length")

        # Convert hex strings back to integers and count differing bits
        int1 = int(hash1, 16)
        int2 = int(hash2, 16)
        return bin(int1 ^ int2).count('1')


class TimestampNormalizer:
    # Match patterns like:
    # PXL_20231025_123456...
    # IMG_20231025_123456...
    # YYYYMMDD_...
    DATE_PATTERN = re.compile(r'(?:PXL_|IMG_|VID_)?(\d{8})_?(\d{6})?')

    @classmethod
    def extract_timestamp(cls, filename: str) -> typing.Optional[datetime.datetime]:
        match = cls.DATE_PATTERN.search(filename)
        if match:
            date_str = match.group(1)
            time_str = match.group(2) or "000000"
            try:
                dt = datetime.datetime.strptime(f"{date_str}{time_str}", "%Y%m%d%H%M%S")
                return dt
            except ValueError:
                pass
        return None

class DeduplicationManager:
    def __init__(self, client: ImmichClient, threshold: int, export_json: str, dry_run: bool):
        self.client = client
        self.threshold = threshold
        self.export_json = export_json
        self.dry_run = dry_run

    def get_asset_resolution(self, asset: dict) -> int:
        width = asset.get('exifInfo', {}).get('exifImageWidth') or asset.get('exifInfo', {}).get('imageWidth') or 0
        height = asset.get('exifInfo', {}).get('exifImageHeight') or asset.get('exifInfo', {}).get('imageHeight') or 0
        return width * height

    def process(self, limit: int = None):
        logger.info("Starting deduplication process...")
        assets = list(self.client.get_assets(limit=limit))
        logger.info(f"Retrieved {len(assets)} assets")

        hashes = {}
        normalized_assets = []
        for asset in assets:
            # EXIF Normalization Check
            if not asset.get('exifInfo', {}).get('dateTimeOriginal'):
                filename = asset.get('originalFileName', '') + asset.get('originalExtension', '')
                extracted_dt = TimestampNormalizer.extract_timestamp(filename)
                if extracted_dt:
                    logger.info(f"Normalized missing EXIF timestamp for {asset['id']} ({filename}) to {extracted_dt.isoformat()}")
                    asset['_normalized_timestamp'] = extracted_dt.isoformat()
                    normalized_assets.append(asset)

            if not asset.get('type') == 'IMAGE':
                continue

            try:
                thumb_bytes = self.client.get_thumbnail(asset['id'])
                img = Image.open(io.BytesIO(thumb_bytes))
                dhash = ImageHasher.compute_dhash(img)
                hashes[asset['id']] = {
                    "asset": asset,
                    "dhash": dhash,
                    "resolution": self.get_asset_resolution(asset)
                }
            except Exception as e:
                logger.error(f"Failed to process asset {asset['id']}: {e}")

        # Group duplicates
        clusters = []
        processed_ids = set()

        asset_ids = list(hashes.keys())
        for i, aid1 in enumerate(asset_ids):
            if aid1 in processed_ids:
                continue

            cluster = [aid1]
            processed_ids.add(aid1)

            for aid2 in asset_ids[i+1:]:
                if aid2 in processed_ids:
                    continue

                distance = ImageHasher.hamming_distance(hashes[aid1]['dhash'], hashes[aid2]['dhash'])
                if distance <= self.threshold:
                    cluster.append(aid2)
                    processed_ids.add(aid2)

            if len(cluster) > 1:
                clusters.append(cluster)

        # Select primaries and output manifest
        manifest = []
        for cluster in clusters:
            # Sort by resolution descending
            sorted_cluster = sorted(cluster, key=lambda aid: hashes[aid]['resolution'], reverse=True)
            primary_id = sorted_cluster[0]
            duplicate_ids = sorted_cluster[1:]

            manifest.append({
                "primary": hashes[primary_id]['asset'],
                "duplicates": [hashes[aid]['asset'] for aid in duplicate_ids]
            })

        logger.info(f"Found {len(manifest)} duplicate clusters")

        output_data = {
            "duplicate_clusters": manifest,
            "normalized_timestamps": normalized_assets
        }

        if self.export_json:
            with open(self.export_json, 'w') as f:
                json.dump(output_data, f, indent=2)
            logger.info(f"Exported review manifest to {self.export_json}")

        if self.dry_run:
            logger.info("Dry run enabled, skipping any destructive actions (which are disabled anyway by directive).")


def main():
    parser = argparse.ArgumentParser(description="Immich AI Duplicate Finder & EXIF Normalizer")
    parser.add_argument("--dry-run", action="store_true", help="Run in dry-run mode (default safety)")
    parser.add_argument("--threshold", type=int, default=10, help="Hamming distance similarity threshold")
    parser.add_argument("--limit", type=int, help="Limit number of assets to process")
    parser.add_argument("--export-json", type=str, default="duplicates_review.json", help="Path to export review manifest")
    parser.add_argument("--url", type=str, default=os.environ.get("IMMICH_URL", "http://localhost:2283"), help="Immich API URL")
    parser.add_argument("--api-key", type=str, default=os.environ.get("IMMICH_API_KEY", ""), help="Immich API Key")

    args = parser.parse_args()

    if not args.api_key:
        logger.error("Immich API Key is required. Set IMMICH_API_KEY env var or use --api-key.")
        return

    client = ImmichClient(base_url=args.url, api_key=args.api_key)
    manager = DeduplicationManager(client=client, threshold=args.threshold, export_json=args.export_json, dry_run=args.dry_run)
    manager.process(limit=args.limit)

if __name__ == "__main__":
    main()
