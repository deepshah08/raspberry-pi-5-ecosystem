import argparse
import json
import logging
import time
import threading
from urllib.parse import urljoin
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import requests
from prometheus_client import start_http_server, Gauge
from typing import List, Dict, Any

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Prometheus Metrics
LOADED_MODELS = Gauge('homelab_llm_loaded_models', 'Number of currently loaded models')
MEMORY_BYTES = Gauge('homelab_llm_memory_bytes', 'Total memory (RAM/VRAM) allocated by loaded models', ['model_name'])
IDLE_SECONDS = Gauge('homelab_llm_idle_seconds', 'Idle duration of loaded models in seconds', ['model_name'])

class LLMGovernor:
    def __init__(self, ollama_url: str, idle_timeout: int, dry_run: bool = False, is_json: bool = False):
        self.ollama_url = ollama_url
        self.idle_timeout = idle_timeout
        self.dry_run = dry_run
        self.is_json = is_json
        self.model_last_active: Dict[str, float] = {}
        self.max_concurrency = 2
        self.current_requests = 0
        self.lock = threading.Lock()

    def update_model_activity(self, model_name: str) -> None:
        with self.lock:
            self.model_last_active[model_name] = time.time()

    def get_loaded_models(self) -> List[Dict[str, Any]]:
        try:
            url = urljoin(self.ollama_url, "/api/ps")
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            return data.get("models", [])
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to query Ollama API: {e}")
            return []

    def get_tags(self) -> List[Dict[str, Any]]:
        try:
            url = urljoin(self.ollama_url, "/api/tags")
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            return data.get("models", [])
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get tags from Ollama API: {e}")
            return []

    def check_concurrency(self) -> bool:
        with self.lock:
            if self.current_requests >= self.max_concurrency:
                logger.warning(f"Concurrency limit reached ({self.current_requests}/{self.max_concurrency}). Rejecting request.")
                return False
            self.current_requests += 1
            return True

    def release_concurrency(self) -> None:
        with self.lock:
            if self.current_requests > 0:
                self.current_requests -= 1

    def run_audit(self) -> List[Dict[str, Any]]:
        models = self.get_loaded_models()

        LOADED_MODELS.set(len(models))

        # Reset memory and idle metrics for models that are no longer loaded
        current_model_names = {m.get('name') for m in models}
        for name in list(self.model_last_active.keys()):
            if name not in current_model_names:
                del self.model_last_active[name]
                try:
                    MEMORY_BYTES.remove(name)
                    IDLE_SECONDS.remove(name)
                except KeyError:
                    pass

        audit_results = []
        now = time.time()

        for model in models:
            name = model.get('name')
            if not name:
                continue

            size = model.get('size', 0)
            MEMORY_BYTES.labels(model_name=name).set(size)

            if name not in self.model_last_active:
                self.model_last_active[name] = now

            idle_duration = now - self.model_last_active[name]
            IDLE_SECONDS.labels(model_name=name).set(idle_duration)

            if idle_duration > self.idle_timeout:
                self.unload_model(name)
            else:
                audit_results.append({
                    "model": name,
                    "memory_bytes": size,
                    "idle_seconds": idle_duration
                })

        if self.is_json:
            print(json.dumps(audit_results))
        else:
            for res in audit_results:
                logger.info(f"Model: {res['model']} | Memory: {res['memory_bytes']} bytes | Idle: {res['idle_seconds']:.2f}s")

        return audit_results

    def unload_model(self, model_name: str) -> None:
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would unload model {model_name}")
            return

        logger.info(f"Unloading idle model {model_name}")
        url = urljoin(self.ollama_url, "/api/generate")
        payload = {
            "model": model_name,
            "keep_alive": 0
        }
        try:
            # We don't actually need to read the stream, just trigger unload
            requests.post(url, json=payload, timeout=10)
            logger.info(f"Successfully unloaded model {model_name}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to unload model {model_name}: {e}")

    def audit_loop(self, interval: int = 60) -> None:
        while True:
            self.run_audit()
            time.sleep(interval)

    def start_loop(self, interval: int = 60) -> None:
        start_http_server(9118)
        logger.info("Started Prometheus metrics server on port 9118")

        audit_thread = threading.Thread(target=self.audit_loop, args=(interval,), daemon=True)
        audit_thread.start()

class ProxyHandler(BaseHTTPRequestHandler):
    def __init__(self, governor: LLMGovernor, *args: Any, **kwargs: Any):
        self.governor = governor
        super().__init__(*args, **kwargs)

    def do_POST(self) -> None:
        if not self.governor.check_concurrency():
            self.send_response(429)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Too Many Requests"}).encode())
            return

        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)

            # Extract model name if possible to update activity
            try:
                body_json = json.loads(body.decode('utf-8'))
                model_name = body_json.get('model')
                if model_name:
                    self.governor.update_model_activity(model_name)
            except json.JSONDecodeError:
                pass

            url = urljoin(self.governor.ollama_url, self.path)

            headers = {k: v for k, v in self.headers.items() if k.lower() != 'host'}

            response = requests.post(
                url,
                data=body,
                headers=headers,
                stream=True
            )

            self.send_response(response.status_code)
            for k, v in response.headers.items():
                if k.lower() not in ['transfer-encoding', 'content-encoding']:
                    self.send_header(k, v)
            self.end_headers()

            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    self.wfile.write(chunk)

        except Exception as e:
            logger.error(f"Proxy error: {e}")
            if not self.wfile.closed:
                self.send_response(500)
                self.end_headers()
        finally:
            self.governor.release_concurrency()

def run_proxy_server(governor: LLMGovernor, port: int = 11435) -> None:
    def handler_factory(*args: Any, **kwargs: Any) -> ProxyHandler:
        return ProxyHandler(governor, *args, **kwargs)

    server = ThreadingHTTPServer(('', port), handler_factory)
    logger.info(f"Started proxy server on port {port}")
    server.serve_forever()

def main() -> None:
    parser = argparse.ArgumentParser(description="Automated Ollama / Local LLM Model Cache & VRAM Governor")
    parser.add_argument("--audit-now", action="store_true", help="Run a single audit and exit")
    parser.add_argument("--ollama-url", default="http://localhost:11434", help="Ollama API URL")
    parser.add_argument("--idle-timeout", type=int, default=300, help="Idle timeout in seconds before unloading a model")
    parser.add_argument("--dry-run", action="store_true", help="Do not actually unload models")
    parser.add_argument("--json", action="store_true", help="Output audit results in JSON format")

    args = parser.parse_args()

    governor = LLMGovernor(
        ollama_url=args.ollama_url,
        idle_timeout=args.idle_timeout,
        dry_run=args.dry_run,
        is_json=args.json
    )

    if args.audit_now:
        governor.run_audit()
    else:
        governor.start_loop()
        run_proxy_server(governor)

if __name__ == "__main__":
    main()
