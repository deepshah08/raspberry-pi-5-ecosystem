import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

from docker_gc import PolicyFilter, ImageAnalyzer, Pruner

@pytest.fixture
def mock_docker_client():
    client = MagicMock()
    return client

def create_mock_image(image_id, created_days_ago=0, tags=None, virtual_size=1024):
    image = MagicMock()
    image.id = image_id
    
    # Calculate creation time
    creation_time = datetime.now(timezone.utc) - timedelta(days=created_days_ago)
    image.attrs = {
        'Created': creation_time.isoformat(),
        'VirtualSize': virtual_size
    }
    
    image.tags = tags or ['<none>:<none>']
    return image

def test_policy_filter_active_container(mock_docker_client):
    # Mock container using an image
    container = MagicMock()
    container.image.id = "active_image_123"
    mock_docker_client.containers.list.return_value = [container]
    
    filter = PolicyFilter(keep_days=7, client=mock_docker_client)
    
    active_image = create_mock_image("active_image_123", created_days_ago=10)
    inactive_image = create_mock_image("inactive_image_456", created_days_ago=10)
    
    assert filter.is_protected(active_image) == True
    assert filter.is_protected(inactive_image) == False

def test_policy_filter_keep_days(mock_docker_client):
    mock_docker_client.containers.list.return_value = []
    filter = PolicyFilter(keep_days=7, client=mock_docker_client)
    
    recent_image = create_mock_image("recent_1", created_days_ago=3)
    old_image = create_mock_image("old_1", created_days_ago=10)
    
    assert filter.is_protected(recent_image) == True
    assert filter.is_protected(old_image) == False

def test_policy_filter_tagged_production(mock_docker_client):
    mock_docker_client.containers.list.return_value = []
    filter = PolicyFilter(keep_days=7, client=mock_docker_client)
    
    # Not dangling (tagged)
    tagged_image = create_mock_image("tagged_1", created_days_ago=10, tags=["myapp:latest"])
    # Dangling
    dangling_image = create_mock_image("dangling_1", created_days_ago=10, tags=["<none>:<none>"])
    
    assert filter.is_protected(tagged_image) == True
    assert filter.is_protected(dangling_image) == False

def test_image_analyzer_dangling_images(mock_docker_client):
    mock_docker_client.containers.list.return_value = []
    
    img1 = create_mock_image("dangling_old", created_days_ago=10, virtual_size=1 * (1024**3)) # 1GB
    img2 = create_mock_image("dangling_recent", created_days_ago=2, virtual_size=2 * (1024**3)) # 2GB, protected
    img3 = create_mock_image("tagged", created_days_ago=10, tags=["prod:v1"], virtual_size=5 * (1024**3)) # 5GB, protected
    
    mock_docker_client.images.list.return_value = [img1, img2, img3]
    
    mock_docker_client.df.return_value = {
        'BuildCache': [{'Size': 1.5 * (1024**3)}] # 1.5GB
    }
    
    filter = PolicyFilter(keep_days=7, client=mock_docker_client)
    analyzer = ImageAnalyzer(client=mock_docker_client, filter_policy=filter)
    
    analysis = analyzer.analyze()
    
    assert len(analysis['reclaimable_images']) == 1
    assert analysis['reclaimable_images'][0].id == "dangling_old"
    
    # 1GB from dangling_old + 1.5GB from build cache = 2.5GB
    assert analysis['reclaimable_gb'] == 2.5
    assert analysis['build_cache_size_bytes'] == 1.5 * (1024**3)

def test_pruner_dry_run_safety(mock_docker_client):
    img = create_mock_image("dangling_old", virtual_size=15 * (1024**3))
    analysis = {
        'reclaimable_gb': 15.0,
        'reclaimable_images': [img],
        'build_cache_size_bytes': 0
    }
    
    pruner = Pruner(client=mock_docker_client, threshold_gb=10.0, dry_run=True)
    report = pruner.prune(analysis)
    
    assert report['threshold_met'] == True
    assert report['dry_run'] == True
    assert "dangling_old" in report['pruned_images']
    
    # Ensure API wasn't actually called
    mock_docker_client.images.remove.assert_not_called()
    mock_docker_client.api.prune_builds.assert_not_called()

def test_pruner_threshold_not_met(mock_docker_client):
    img = create_mock_image("dangling_old", virtual_size=5 * (1024**3))
    analysis = {
        'reclaimable_gb': 5.0,
        'reclaimable_images': [img],
        'build_cache_size_bytes': 0
    }
    
    pruner = Pruner(client=mock_docker_client, threshold_gb=10.0, dry_run=False)
    report = pruner.prune(analysis)
    
    assert report['threshold_met'] == False
    assert len(report['pruned_images']) == 0
    
    # Ensure API wasn't called because threshold wasn't met
    mock_docker_client.images.remove.assert_not_called()

def test_pruner_execution(mock_docker_client):
    img = create_mock_image("dangling_old", virtual_size=11 * (1024**3))
    analysis = {
        'reclaimable_gb': 12.0,
        'reclaimable_images': [img],
        'build_cache_size_bytes': 1 * (1024**3)
    }
    
    pruner = Pruner(client=mock_docker_client, threshold_gb=10.0, dry_run=False)
    report = pruner.prune(analysis)
    
    assert report['threshold_met'] == True
    assert report['dry_run'] == False
    assert "dangling_old" in report['pruned_images']
    assert report['pruned_build_cache'] == True
    
    # Ensure API was called
    mock_docker_client.images.remove.assert_called_once_with("dangling_old", force=False)
    mock_docker_client.api.prune_builds.assert_called_once()
