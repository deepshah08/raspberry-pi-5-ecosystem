import argparse
import sys
import json
import hmac
import hashlib
import time
import uuid
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from typing import Dict, Any

SECRET_KEY = b"homelab_webhook_secret"

class WebhookMatrixReceiver(BaseHTTPRequestHandler):
    recorded_webhooks = []
    
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        # Verify HMAC if present
        signature = self.headers.get('X-Hub-Signature-256')
        if signature:
            expected_mac = hmac.new(SECRET_KEY, post_data, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(f"sha256={expected_mac}", signature):
                self.send_response(401)
                self.end_headers()
                return

        try:
            payload = json.loads(post_data.decode('utf-8'))
            payload['_received_at'] = time.time()
            if '_dispatched_at' in payload:
                latency = (payload['_received_at'] - payload['_dispatched_at']) * 1000
                payload['_propagation_latency_ms'] = latency
            WebhookMatrixReceiver.recorded_webhooks.append(payload)
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return
            
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"status": "ok"}')

    def log_message(self, format, *args):
        pass # Silence logging for cleaner output

class SyntheticDispatcher:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        
    def emit(self, url: str, event_type: str, data: Dict[str, Any], sign: bool = True) -> Dict[str, Any]:
        payload = {
            "eventId": str(uuid.uuid4()),
            "eventType": event_type,
            "data": data,
            "_dispatched_at": time.time()
        }
        
        payload_bytes = json.dumps(payload).encode('utf-8')
        
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "WebhookMatrix/1.0"
        }
        
        if sign:
            mac = hmac.new(SECRET_KEY, payload_bytes, hashlib.sha256).hexdigest()
            headers["X-Hub-Signature-256"] = f"sha256={mac}"
            
        if self.dry_run:
            print(f"[DRY RUN] Would dispatch event {event_type} to {url}")
            return {"status": "dry_run_success", "payload": payload}
            
        req = urllib.request.Request(url, data=payload_bytes, headers=headers, method='POST')
        
        start_time = time.time()
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                status = response.status
                latency = (time.time() - start_time) * 1000
                return {"status": status, "latency_ms": latency, "payload": payload}
        except urllib.error.HTTPError as e:
            latency = (time.time() - start_time) * 1000
            return {"status": e.code, "latency_ms": latency, "error": str(e), "payload": payload}
        except Exception as e:
            latency = (time.time() - start_time) * 1000
            return {"status": 0, "latency_ms": latency, "error": str(e), "payload": payload}

class MatrixHealthEvaluator:
    def __init__(self, dispatcher: SyntheticDispatcher):
        self.dispatcher = dispatcher
        
    def check_route(self, name: str, url: str) -> Dict[str, Any]:
        event_type = "HealthCheck"
        result = self.dispatcher.emit(url, event_type, {"message": "ping"})
        
        healthy = False
        if "latency_ms" in result and result.get("status") in (200, 201, 202, 204):
            if result["latency_ms"] <= 500:
                healthy = True
                
        return {
            "route": name,
            "url": url,
            "healthy": healthy,
            "result": result
        }

def start_receiver(port: int) -> HTTPServer:
    server = HTTPServer(('0.0.0.0', port), WebhookMatrixReceiver)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server

def main():
    parser = argparse.ArgumentParser(description="Homelab Synthetic Webhook Dispatcher & Health Matrix")
    parser.add_argument("--test-route", type=str, help="Route name to test (format: name,url)")
    parser.add_argument("--listen-port", type=int, default=8095, help="Port for the Matrix Receiver")
    parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without emitting events")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    
    args = parser.parse_args()
    
    dispatcher = SyntheticDispatcher(dry_run=args.dry_run)
    evaluator = MatrixHealthEvaluator(dispatcher)
    
    server = start_receiver(args.listen_port)
    
    results = {}
    
    if args.test_route:
        try:
            name, url = args.test_route.split(",", 1)
            results[name] = evaluator.check_route(name, url)
        except ValueError:
            print("Error: --test-route must be in the format 'name,url'", file=sys.stderr)
            sys.exit(1)
            
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for name, data in results.items():
            healthy = data.get("healthy", False)
            status = "HEALTHY" if healthy else "UNHEALTHY"
            latency = data.get("result", {}).get("latency_ms", "N/A")
            if isinstance(latency, float):
                latency = f"{latency:.2f}ms"
            print(f"Route: {name} [{status}] - Latency: {latency}")
            
    server.shutdown()
    server.server_close()

if __name__ == "__main__":
    main()
