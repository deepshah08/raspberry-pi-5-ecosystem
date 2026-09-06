import argparse
import sys
import json
import time
from typing import Dict, List, Optional
import docker

PROTECTED_CONTAINERS = {"pihole", "unbound", "reverse-proxy", "uptime-kuma"}
LIMIT_THRESHOLD_PERCENT = 85.0

class ContainerMemorySampler:
    def __init__(self, client):
        self.client = client

    def get_stats(self) -> Dict[str, dict]:
        """Fetch basic memory stats for all running containers."""
        containers = self.client.containers.list()
        stats_map = {}
        for c in containers:
            try:
                stats = c.stats(stream=False)
                memory_stats = stats.get('memory_stats', {})
                if 'usage' in memory_stats and 'limit' in memory_stats:
                    usage = memory_stats['usage']
                    limit = memory_stats['limit']
                    stats_type = memory_stats.get('stats', {})
                    if 'inactive_file' in stats_type:
                        usage = usage - stats_type['inactive_file']
                    elif 'cache' in stats_type:
                        usage = usage - stats_type['cache']
                    
                    stats_map[c.name] = {
                        'usage_bytes': usage,
                        'limit_bytes': limit,
                        'timestamp': time.time()
                    }
            except Exception as e:
                continue
        return stats_map

class LeakSlopeCalculator:
    def __init__(self, history_size: int = 5):
        self.history_size = history_size
        self.history: Dict[str, List[dict]] = {}

    def add_sample(self, container_name: str, usage_bytes: int, limit_bytes: int, timestamp: float):
        if container_name not in self.history:
            self.history[container_name] = []
        
        self.history[container_name].append({
            'usage_bytes': usage_bytes,
            'limit_bytes': limit_bytes,
            'timestamp': timestamp
        })
        
        if len(self.history[container_name]) > self.history_size:
            self.history[container_name].pop(0)

    def calculate_slope(self, container_name: str) -> Optional[float]:
        """Calculate memory growth rate in MB/minute."""
        history = self.history.get(container_name, [])
        if len(history) < 2:
            return None
            
        first = history[0]
        last = history[-1]
        
        time_diff_minutes = (last['timestamp'] - first['timestamp']) / 60.0
        if time_diff_minutes <= 0:
            return 0.0
            
        usage_diff_mb = (last['usage_bytes'] - first['usage_bytes']) / (1024 * 1024)
        
        return usage_diff_mb / time_diff_minutes

class PolicyEvaluator:
    def __init__(self, threshold_percent: float = LIMIT_THRESHOLD_PERCENT):
        self.threshold_percent = threshold_percent

    def evaluate(self, container_name: str, usage_bytes: int, limit_bytes: int, slope_mb_min: Optional[float]) -> Optional[dict]:
        if container_name in PROTECTED_CONTAINERS:
            return None # Protected containers are exempt from generic alerts

        if limit_bytes <= 0:
            return None
            
        usage_percent = (usage_bytes / limit_bytes) * 100.0
        
        is_high_usage = usage_percent > self.threshold_percent
        
        # Calculate ETA to OOM if slope is positive
        eta_minutes = None
        if slope_mb_min is not None and slope_mb_min > 0:
            remaining_mb = (limit_bytes - usage_bytes) / (1024 * 1024)
            if remaining_mb > 0:
                eta_minutes = remaining_mb / slope_mb_min

        is_fast_leak = eta_minutes is not None and eta_minutes < 15.0
        
        if is_high_usage or is_fast_leak:
            return {
                "container_name": container_name,
                "usage_percent": usage_percent,
                "slope_mb_min": slope_mb_min,
                "eta_minutes": eta_minutes,
                "reason": "high_usage" if is_high_usage else "fast_leak"
            }
            
        return None

class AlertFormatter:
    @staticmethod
    def format_alert(alert_data: dict, as_json: bool) -> str:
        if as_json:
            return json.dumps(alert_data)
        
        msg = (f"ALERT: Container '{alert_data['container_name']}' is at risk of OOM. "
               f"Usage: {alert_data['usage_percent']:.2f}%. ")
        
        if alert_data['slope_mb_min'] is not None:
             msg += f"Growth rate: {alert_data['slope_mb_min']:.2f} MB/min. "
             
        if alert_data['eta_minutes'] is not None:
             msg += f"ETA to OOM: {alert_data['eta_minutes']:.2f} minutes."
             
        return msg

def parse_args():
    parser = argparse.ArgumentParser(description="Docker Container Memory Leak & OOM Killer Watchdog")
    parser.add_argument("--check-now", action="store_true", help="Run a single check immediately")
    parser.add_argument("--interval", type=int, default=60, help="Interval between checks in seconds")
    parser.add_argument("--json", action="store_true", help="Output alerts in JSON format")
    parser.add_argument("--dry-run", action="store_true", help="Do not dispatch alerts, just log them")
    return parser.parse_args()

def main():
    args = parse_args()
    try:
        client = docker.from_env()
    except Exception as e:
        print(f"Failed to connect to Docker daemon: {e}")
        sys.exit(1)
        
    sampler = ContainerMemorySampler(client)
    calculator = LeakSlopeCalculator()
    evaluator = PolicyEvaluator()
    
    def process_stats():
        stats = sampler.get_stats()
        for name, stat in stats.items():
            calculator.add_sample(name, stat['usage_bytes'], stat['limit_bytes'], stat['timestamp'])
            slope = calculator.calculate_slope(name)
            
            alert = evaluator.evaluate(name, stat['usage_bytes'], stat['limit_bytes'], slope)
            if alert:
                formatted = AlertFormatter.format_alert(alert, args.json)
                if args.dry_run:
                    print(f"[DRY-RUN] {formatted}")
                else:
                    # Simulate dispatch to Alert Router
                    print(formatted)
                    
    if args.check_now:
        process_stats()
    else:
        while True:
            process_stats()
            time.sleep(args.interval)

if __name__ == "__main__":
    main()
