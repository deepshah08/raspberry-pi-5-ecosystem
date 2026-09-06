import argparse
import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, Set
import dateutil.parser

import docker
from docker.errors import APIError

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class PolicyFilter:
    def __init__(self, keep_days: int, client: docker.DockerClient):
        self.keep_days = keep_days
        self.client = client
        self.now = datetime.now(timezone.utc)

    def is_protected(self, image: Any) -> bool:
        """
        Check if an image is protected.
        - Never prune active container images.
        - Never prune tagged production images.
        - Never prune images created within the last N days.
        """
        # Check active containers
        containers = self.client.containers.list(all=True)
        active_image_ids = {c.image.id for c in containers}
        if image.id in active_image_ids:
            return True

        # Check age
        try:
            # Docker API usually returns timestamp string
            created_str = image.attrs.get('Created', '')
            if created_str:
                created_dt = dateutil.parser.isoparse(created_str)
                if (self.now - created_dt).days < self.keep_days:
                    return True
        except Exception as e:
            logger.warning(f"Error parsing date for image {image.id}: {e}")
            pass

        # Check tagged images (production)
        # Assuming dangling means not tagged, if it has a tag other than <none>:<none>, it might be protected
        tags = image.tags
        if tags and not all(t == '<none>:<none>' for t in tags):
            return True

        return False

class ImageAnalyzer:
    def __init__(self, client: docker.DockerClient, filter_policy: PolicyFilter):
        self.client = client
        self.filter_policy = filter_policy

    def analyze(self) -> Dict[str, Any]:
        """
        Scans local Docker images, calculating disk reclaim potential.
        """
        images = self.client.images.list(all=True)
        
        reclaimable_size_bytes = 0
        reclaimable_images = []
        
        # Calculate reclaimable size for images that are not protected
        for image in images:
            if not self.filter_policy.is_protected(image):
                reclaimable_images.append(image)
                reclaimable_size_bytes += image.attrs.get('VirtualSize', 0)
        
        # We also need to consider buildx cache, which we can get via system df
        try:
            df = self.client.df()
            build_cache_size = sum(cache.get('Size', 0) for cache in df.get('BuildCache', []))
            reclaimable_size_bytes += build_cache_size
        except Exception as e:
            logger.warning(f"Failed to get build cache size: {e}")
            build_cache_size = 0

        reclaimable_gb = reclaimable_size_bytes / (1024 ** 3)
        
        return {
            'reclaimable_gb': reclaimable_gb,
            'reclaimable_bytes': reclaimable_size_bytes,
            'reclaimable_images': reclaimable_images,
            'build_cache_size_bytes': build_cache_size
        }

class Pruner:
    def __init__(self, client: docker.DockerClient, threshold_gb: float, dry_run: bool):
        self.client = client
        self.threshold_gb = threshold_gb
        self.dry_run = dry_run

    def prune(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        reclaimable_gb = analysis['reclaimable_gb']
        reclaimable_images = analysis['reclaimable_images']
        
        report = {
            'threshold_met': reclaimable_gb >= self.threshold_gb,
            'reclaimable_gb': reclaimable_gb,
            'dry_run': self.dry_run,
            'pruned_images': [],
            'pruned_build_cache': False,
            'errors': []
        }
        
        if not report['threshold_met']:
            logger.info(f"Threshold not met. Reclaimable: {reclaimable_gb:.2f}GB < Threshold: {self.threshold_gb:.2f}GB")
            return report
            
        logger.info(f"Threshold met. Reclaimable: {reclaimable_gb:.2f}GB >= Threshold: {self.threshold_gb:.2f}GB")
        
        for img in reclaimable_images:
            if self.dry_run:
                logger.info(f"[DRY-RUN] Would remove image: {img.id}")
                report['pruned_images'].append(img.id)
            else:
                try:
                    self.client.images.remove(img.id, force=False)
                    logger.info(f"Removed image: {img.id}")
                    report['pruned_images'].append(img.id)
                except APIError as e:
                    logger.error(f"Failed to remove image {img.id}: {e}")
                    report['errors'].append(f"Failed to remove {img.id}: {e}")
                    
        # Prune build cache
        if analysis['build_cache_size_bytes'] > 0:
            if self.dry_run:
                logger.info("[DRY-RUN] Would prune build cache")
                report['pruned_build_cache'] = True
            else:
                try:
                    # In python sdk: client.api.prune_builds() 
                    self.client.api.prune_builds()
                    logger.info("Pruned build cache")
                    report['pruned_build_cache'] = True
                except Exception as e:
                    logger.error(f"Failed to prune build cache: {e}")
                    report['errors'].append(f"Failed to prune build cache: {e}")

        return report

def parse_args():
    parser = argparse.ArgumentParser(description="Homelab Multi-Node Container Image Pruner & Cache Garbage Collector")
    parser.add_argument("--dry-run", action="store_true", help="Dry-run mode, do not actually prune anything.")
    parser.add_argument("--threshold-gb", type=float, default=10.0, help="Threshold in GB before pruning runs.")
    parser.add_argument("--keep-days", type=int, default=7, help="Keep images created within the last N days.")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format.")
    return parser.parse_args()

def main():
    args = parse_args()
    try:
        client = docker.from_env()
    except Exception as e:
        logger.error(f"Failed to connect to Docker daemon: {e}")
        sys.exit(1)
        
    policy_filter = PolicyFilter(keep_days=args.keep_days, client=client)
    analyzer = ImageAnalyzer(client=client, filter_policy=policy_filter)
    
    analysis = analyzer.analyze()
    
    pruner = Pruner(client=client, threshold_gb=args.threshold_gb, dry_run=args.dry_run)
    report = pruner.prune(analysis)
    
    if args.json:
        # Avoid serialization issues with custom objects
        clean_report = {
            'threshold_met': report['threshold_met'],
            'reclaimable_gb': report['reclaimable_gb'],
            'dry_run': report['dry_run'],
            'pruned_images': report['pruned_images'],
            'pruned_build_cache': report['pruned_build_cache'],
            'errors': report['errors']
        }
        print(json.dumps(clean_report, indent=2))
    else:
        logger.info(f"Report: {report}")

if __name__ == "__main__":
    main()
