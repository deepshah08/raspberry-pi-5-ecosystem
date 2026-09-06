import time
import json
import argparse
import dns.resolver
import requests
from typing import Dict, Any, List
from prometheus_client import start_http_server, Gauge, Counter

DNS_LATENCY_METRIC = Gauge('homelab_canary_dns_latency_ms', 'DNS resolution latency in ms', ['server', 'domain'])
HTTP_TTFB_METRIC = Gauge('homelab_canary_http_ttfb_ms', 'HTTP TTFB in ms', ['url'])
SLO_VIOLATION_METRIC = Counter('homelab_canary_slo_violation_count', 'Number of SLO violations (latency > 500ms)', ['type', 'target'])

SLO_THRESHOLD_MS = 500.0

class DNSProber:
    def __init__(self, servers: List[str]):
        self.servers = servers

    def probe(self, domain: str, timeout: float = 2.0) -> Dict[str, Any]:
        results = {}
        for server in self.servers:
            resolver = dns.resolver.Resolver(configure=False)
            resolver.nameservers = [server]
            resolver.timeout = timeout
            resolver.lifetime = timeout
            
            start_time = time.perf_counter()
            try:
                resolver.resolve(domain, 'A')
                latency_ms = (time.perf_counter() - start_time) * 1000
                status = "success"
            except Exception as e:
                latency_ms = float('inf')
                status = str(e)
                
            results[server] = {
                "latency_ms": latency_ms,
                "status": status
            }
        return results

class HTTPProber:
    def probe(self, url: str, timeout: float = 2.0) -> Dict[str, Any]:
        start_time = time.perf_counter()
        try:
            # Use stream=True to measure TTFB properly
            response = requests.get(url, timeout=timeout, stream=True)
            ttfb_ms = (time.perf_counter() - start_time) * 1000
            
            # Consume the remaining content and close
            response.raw.read()
            response.close()
            
            return {
                "ttfb_ms": ttfb_ms,
                "status_code": response.status_code,
                "status": "success"
            }
        except requests.exceptions.RequestException as e:
            return {
                "ttfb_ms": float('inf'),
                "status_code": 0,
                "status": str(e)
            }

def run_probes(dns_servers, domains, http_urls, dry_run=False, output_json=False):
    dns_prober = DNSProber(dns_servers)
    http_prober = HTTPProber()
    
    results = {
        "dns": {},
        "http": {},
        "slo_violations": []
    }

    # DNS Probes
    for domain in domains:
        dns_results = dns_prober.probe(domain)
        results["dns"][domain] = dns_results
        for server, data in dns_results.items():
            latency = data["latency_ms"]
            if not dry_run and latency != float('inf'):
                DNS_LATENCY_METRIC.labels(server=server, domain=domain).set(latency)
            
            is_violation = latency > SLO_THRESHOLD_MS
            if is_violation:
                if not dry_run:
                    SLO_VIOLATION_METRIC.labels(type="dns", target=f"{server}:{domain}").inc()
                results["slo_violations"].append({"type": "dns", "target": f"{server}:{domain}", "latency_ms": latency})

    # HTTP Probes
    for url in http_urls:
        http_result = http_prober.probe(url)
        results["http"][url] = http_result
        latency = http_result["ttfb_ms"]
        
        if not dry_run and latency != float('inf'):
            HTTP_TTFB_METRIC.labels(url=url).set(latency)
            
        is_violation = latency > SLO_THRESHOLD_MS
        if is_violation:
            if not dry_run:
                SLO_VIOLATION_METRIC.labels(type="http", target=url).inc()
            results["slo_violations"].append({"type": "http", "target": url, "latency_ms": latency})
            
    if output_json:
        print(json.dumps(results, indent=2))
    elif dry_run:
        print(f"Dry run completed. Results: {results}")

    return results

def main():
    parser = argparse.ArgumentParser(description="Homelab Synthetic Canary Traffic Generator")
    parser.add_argument("--probe-now", action="store_true", help="Run probes once and exit")
    parser.add_argument("--interval", type=int, default=60, help="Interval between probes in seconds")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument("--dry-run", action="store_true", help="Run without updating Prometheus metrics")
    
    args = parser.parse_args()
    
    dns_servers = ["192.168.1.80", "192.168.1.92"]
    domains = ["pi.hole", "router.local", "plex.local"]
    http_urls = ["http://192.168.1.100:32400", "http://192.168.1.100:80", "http://192.168.1.100:3001"] # Assuming IP for Plex, Reverse Proxy, Uptime Kuma

    if not args.dry_run and not args.probe_now:
        start_http_server(9110)
        
    if args.probe_now:
        run_probes(dns_servers, domains, http_urls, dry_run=args.dry_run, output_json=args.json)
    else:
        while True:
            run_probes(dns_servers, domains, http_urls, dry_run=args.dry_run, output_json=args.json)
            time.sleep(args.interval)

if __name__ == "__main__":
    main()
