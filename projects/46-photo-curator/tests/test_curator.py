import datetime
import io
import json
import os
import sys, os; sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))); from unittest import mock

import pytest
import sys, os; sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))); from PIL import Image, ImageDraw

# Add to path so it can import photo_curator
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

import sys, os; sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))); from photo_curator import (
    DeduplicationManager,
    ImageHasher,
    ImmichClient,
    TimestampNormalizer,
)

def create_gradient_image(color_start, color_end):
    img = Image.new('RGB', (100, 100))
    draw = ImageDraw.Draw(img)
    for i in range(100):
        # simple linear gradient
        r = int(color_start[0] + (color_end[0] - color_start[0]) * (i / 100))
        g = int(color_start[1] + (color_end[1] - color_start[1]) * (i / 100))
        b = int(color_start[2] + (color_end[2] - color_start[2]) * (i / 100))
        draw.line([(i, 0), (i, 100)], fill=(r, g, b))
    return img


@pytest.fixture
def mock_immich_client():
    client = mock.MagicMock(spec=ImmichClient)
    # Mock some assets
    client.get_assets.return_value = [
        {"id": "img1", "type": "IMAGE", "originalFileName": "PXL_20231025_123456", "exifInfo": {"exifImageWidth": 100, "exifImageHeight": 100}},
        {"id": "img2", "type": "IMAGE", "originalFileName": "PXL_20231025_123456_DUP", "exifInfo": {"exifImageWidth": 80, "exifImageHeight": 80}},
        {"id": "img3", "type": "IMAGE", "originalFileName": "IMG_20240101_000000", "exifInfo": {"exifImageWidth": 200, "exifImageHeight": 200}},
    ]

    # Create images for thumbnails
    def get_thumbnail(asset_id):
        if asset_id == "img1" or asset_id == "img2":
            # Same gradient, will have same hash
            img = create_gradient_image((255, 0, 0), (0, 0, 0))
        else:
            # Different gradient, will have different hash
            img = create_gradient_image((0, 0, 255), (255, 255, 255))

        buf = io.BytesIO()
        img.save(buf, format='JPEG')
        return buf.getvalue()

    client.get_thumbnail.side_effect = get_thumbnail
    return client


def test_timestamp_normalizer():
    # Test valid PXL pattern
    dt1 = TimestampNormalizer.extract_timestamp("PXL_20231025_123456.jpg")
    assert dt1 == datetime.datetime(2023, 10, 25, 12, 34, 56)

    # Test valid IMG pattern
    dt2 = TimestampNormalizer.extract_timestamp("IMG_20231025_123456.jpg")
    assert dt2 == datetime.datetime(2023, 10, 25, 12, 34, 56)

    # Test pattern with no time
    dt3 = TimestampNormalizer.extract_timestamp("PXL_20231025.jpg")
    assert dt3 == datetime.datetime(2023, 10, 25, 0, 0, 0)

    # Test invalid pattern
    dt4 = TimestampNormalizer.extract_timestamp("random_image_name.jpg")
    assert dt4 is None


def test_image_hasher():
    img1 = create_gradient_image((255, 0, 0), (0, 0, 0))
    img2 = create_gradient_image((255, 0, 0), (0, 0, 0))
    img3 = create_gradient_image((0, 0, 255), (255, 255, 255))

    hash1 = ImageHasher.compute_dhash(img1)
    hash2 = ImageHasher.compute_dhash(img2)
    hash3 = ImageHasher.compute_dhash(img3)

    assert hash1 == hash2
    assert hash1 != hash3

    dist_same = ImageHasher.hamming_distance(hash1, hash2)
    dist_diff = ImageHasher.hamming_distance(hash1, hash3)

    assert dist_same == 0
    assert dist_diff > 0


def test_deduplication_manager(mock_immich_client, tmp_path):
    export_path = tmp_path / "duplicates_review.json"
    manager = DeduplicationManager(
        client=mock_immich_client,
        threshold=10,
        export_json=str(export_path),
        dry_run=True
    )

    manager.process()

    # Expect JSON file to be created
    assert export_path.exists()

    with open(export_path, 'r') as f:
        output_data = json.load(f)

    manifest = output_data["duplicate_clusters"]
    normalized = output_data["normalized_timestamps"]

    # We should have 1 cluster (img1 and img2)
    assert len(manifest) == 1
    cluster = manifest[0]

    # img1 has higher resolution (100x100) than img2 (80x80), so it should be primary
    assert cluster["primary"]["id"] == "img1"
    assert len(cluster["duplicates"]) == 1
    assert cluster["duplicates"][0]["id"] == "img2"

    # Verify that normalized timestamps are populated
    # In the mock, EXIF data is present but dateTimeOriginal is missing,
    # so normalization should have triggered.
    assert len(normalized) > 0
    # For img1: PXL_20231025_123456
    assert any(a['id'] == 'img1' for a in normalized)
