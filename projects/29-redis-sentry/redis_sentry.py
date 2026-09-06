import argparse
import time
import json
import logging
import os
from typing import Dict, Any

import redis
from prometheus_client import start_http_server, Gauge

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('redis_sentry')

MEMORY_USED = Gauge('homelab_redis_memory_used_bytes', 'Redis memory used in bytes')
EVICTED_KEYS = Gauge('homelab_redis_evicted_keys_total', 'Total number of evicted keys')
CONNECTED_CLIENTS = Gauge('homelab_redis_connected_clients', 'Number of connected clients')

class RedisSentry:
    def __init__(self, host: str, port: int, dry_run: bool = False, json_output: bool = False):
        self.host = host
        self.port = port
        self.dry_run = dry_run
        self.json_output = json_output
        self.client = redis.Redis(host=self.host, port=self.port, decode_responses=True)
        self.last_evicted_keys = -1
        self.last_audit_time = 0

    def get_info(self) -> Dict[str, Any]:
        try:
            info_memory = self.client.info('memory')
            info_stats = self.client.info('stats')
            info_keyspace = self.client.info('keyspace')
            info_clients = self.client.info('clients')
            
            return {
                'memory': info_memory,
                'stats': info_stats,
                'keyspace': info_keyspace,
                'clients': info_clients
            }
        except Exception as e:
            if not self.json_output:
                logger.error(f"Failed to get info from Redis: {e}")
            return {}

    def audit_cache_info(self, info: Dict[str, Any]):
        if not info:
            return
            
        memory_used = info.get('memory', {}).get('used_memory', 0)
        max_memory = info.get('memory', {}).get('maxmemory', 0)
        evicted_keys = info.get('stats', {}).get('evicted_keys', 0)
        connected_clients = info.get('clients', {}).get('connected_clients', 0)
        keyspace = info.get('keyspace', {})
        
        # Log keyspace info if needed (as an example of utilizing keyspace data)
        total_keys = sum([db.get('keys', 0) for db in keyspace.values() if isinstance(db, dict)])
        if total_keys > 1000000:
            msg = f"Large keyspace detected: {total_keys} keys."
            if not self.dry_run:
                if self.json_output:
                    print(json.dumps({"alert": "large_keyspace", "message": msg, "total_keys": total_keys}))
                else:
                    logger.info(msg)
        
        MEMORY_USED.set(memory_used)
        EVICTED_KEYS.set(evicted_keys)
        CONNECTED_CLIENTS.set(connected_clients)
        
        if max_memory > 0:
            memory_usage_ratio = memory_used / max_memory
            if memory_usage_ratio > 0.9:
                msg = f"Memory ceiling saturation detected: {memory_usage_ratio*100:.2f}% used."
                if not self.dry_run:
                    if self.json_output:
                        print(json.dumps({"alert": "memory_saturation", "message": msg, "ratio": memory_usage_ratio}))
                    else:
                        logger.warning(msg)
        
        current_time = time.time()
        if self.last_evicted_keys != -1 and self.last_audit_time != 0:
            time_diff = current_time - self.last_audit_time
            if time_diff > 0:
                eviction_rate = (evicted_keys - self.last_evicted_keys) / time_diff
                if eviction_rate > 10.0:
                    msg = f"High eviction rate detected: {eviction_rate:.2f} keys/sec. Memory pressure likely."
                    if not self.dry_run:
                        if self.json_output:
                            print(json.dumps({"alert": "eviction_rate", "message": msg, "rate": eviction_rate}))
                        else:
                            logger.warning(msg)
        
        self.last_evicted_keys = evicted_keys
        self.last_audit_time = current_time

    def audit_key_ttl(self):
        try:
            key = self.client.randomkey()
            if key:
                ttl = self.client.ttl(key)
                if ttl == -1:
                    msg = f"Unbounded key detected: '{key}' has no expiration (TTL=-1)."
                    if not self.dry_run:
                        if self.json_output:
                            print(json.dumps({"alert": "unbounded_key", "key": key}))
                        else:
                            logger.warning(msg)
        except Exception as e:
            if not self.json_output:
                logger.error(f"Failed to audit key TTL: {e}")

    def run_audit(self):
        info = self.get_info()
        if info:
            self.audit_cache_info(info)
        self.audit_key_ttl()

def main():
    parser = argparse.ArgumentParser(description="Homelab In-Memory Cache & Key Space Sentry")
    parser.add_argument('--audit-now', action='store_true', help='Run a single audit immediately')
    parser.add_argument('--redis-host', type=str, help='Redis server host')
    parser.add_argument('--redis-port', type=int, help='Redis server port')
    parser.add_argument('--dry-run', action='store_true', help='Dry run without side effects (alerts)')
    parser.add_argument('--json', action='store_true', help='Output in JSON format')
    
    args = parser.parse_args()
    
    host = args.redis_host or os.environ.get('REDIS_HOST', 'localhost')
    port = args.redis_port or int(os.environ.get('REDIS_PORT', 6379))
    
    sentry = RedisSentry(
        host=host, 
        port=port, 
        dry_run=args.dry_run, 
        json_output=args.json
    )
    
    if args.audit_now:
        sentry.run_audit()
        if args.json:
            print(json.dumps({"status": "audit_complete"}))
    else:
        start_http_server(9135)
        if not args.json:
            logger.info("Started Prometheus exporter on port 9135")
        try:
            while True:
                sentry.run_audit()
                time.sleep(15)
        except KeyboardInterrupt:
            if not args.json:
                logger.info("Shutting down...")

if __name__ == '__main__':
    main()
