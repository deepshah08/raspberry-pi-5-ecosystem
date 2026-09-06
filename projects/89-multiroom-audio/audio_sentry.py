import argparse
import socket
import json
import time
import logging
from prometheus_client import start_http_server, Gauge

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class SnapcastClient:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self._msg_id = 1

    def _send_request(self, method: str, params: dict = None) -> dict:
        req = {
            "id": self._msg_id,
            "jsonrpc": "2.0",
            "method": method
        }
        if params is not None:
            req["params"] = params

        self._msg_id += 1

        try:
            with socket.create_connection((self.host, self.port), timeout=5) as sock:
                sock.sendall((json.dumps(req) + "\r\n").encode("utf-8"))

                # Read response
                response_data = b""
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    response_data += chunk
                    if b"\n" in chunk:
                        break

                if response_data:
                    return json.loads(response_data.decode("utf-8"))
        except Exception as e:
            logging.error(f"Error communicating with Snapserver: {e}")
        return {}

    def get_status(self) -> dict:
        return self._send_request("Server.GetStatus")

    def mute_client(self, client_id: str, mute: bool = True) -> dict:
        return self._send_request("Client.SetVolume", {
            "id": client_id,
            "volume": {
                "muted": mute
            }
        })


# Prometheus Metrics
CLIENTS_CONNECTED = Gauge('homelab_snapcast_clients_connected', 'Number of connected clients')
CLIENT_LATENCY = Gauge('homelab_snapcast_client_latency_ms', 'Client latency in ms', ['client_id', 'hostname'])
STREAM_ACTIVE = Gauge('homelab_snapcast_stream_active', 'Active streams count')

class AudioSentry:
    def __init__(self, client: SnapcastClient, max_latency_ms: int, dry_run: bool = False, json_log: bool = False):
        self.client = client
        self.max_latency_ms = max_latency_ms
        self.dry_run = dry_run
        self.json_log = json_log
        self.logger = logging.getLogger(__name__)

    def log(self, level, message, **kwargs):
        if self.json_log:
            log_data = {"level": level, "message": message}
            log_data.update(kwargs)
            print(json.dumps(log_data))
        else:
            msg = f"{message} " + " ".join([f"{k}={v}" for k, v in kwargs.items()])
            if level == "INFO":
                self.logger.info(msg)
            elif level == "WARNING":
                self.logger.warning(msg)
            elif level == "ERROR":
                self.logger.error(msg)

    def monitor(self):
        status = self.client.get_status()
        if not status or "result" not in status:
            self.log("ERROR", "Failed to retrieve status from Snapserver")
            return

        server_info = status["result"].get("server", {})
        groups = server_info.get("groups", [])
        streams = server_info.get("streams", [])

        active_streams = len([s for s in streams if s.get("status") == "playing"])
        STREAM_ACTIVE.set(active_streams)

        total_clients = 0

        for group in groups:
            for client_data in group.get("clients", []):
                if client_data.get("connected"):
                    total_clients += 1
                    client_id = client_data.get("id")
                    hostname = client_data.get("host", {}).get("name", "unknown")
                    latency_ms = client_data.get("config", {}).get("latency", 0)

                    # Log and expose metric
                    CLIENT_LATENCY.labels(client_id=client_id, hostname=hostname).set(latency_ms)
                    self.log("INFO", f"Client {hostname} latency", client_id=client_id, latency_ms=latency_ms)

                    # Check desync
                    if latency_ms > self.max_latency_ms:
                        self.log("WARNING", f"Desync detected for {hostname}", client_id=client_id, latency_ms=latency_ms, threshold=self.max_latency_ms)

                        if not self.dry_run:
                            self.client.mute_client(client_id, mute=True)
                            self.log("INFO", f"Muted client {hostname} due to desync", client_id=client_id)

        CLIENTS_CONNECTED.set(total_clients)


def parse_args():
    parser = argparse.ArgumentParser(description='Snapcast Audio Sentry')
    parser.add_argument('--check-now', action='store_true', help='Run a single check and exit')
    parser.add_argument('--host', type=str, default='192.168.1.92', help='Snapserver host IP')
    parser.add_argument('--port', type=int, default=1705, help='Snapserver JSON-RPC port')
    parser.add_argument('--max-latency-ms', type=int, default=50, help='Maximum latency deviation in ms')
    parser.add_argument('--dry-run', action='store_true', help='Do not actually mute clients')
    parser.add_argument('--json', action='store_true', help='Output JSON instead of standard logging')
    return parser.parse_args()

def main():
    args = parse_args()

    if args.json:
        logging.getLogger().setLevel(logging.CRITICAL)  # Suppress standard logging

    client = SnapcastClient(host=args.host, port=args.port)
    sentry = AudioSentry(client, args.max_latency_ms, args.dry_run, args.json)

    if args.check_now:
        sentry.monitor()
    else:
        start_http_server(9117)
        sentry.log("INFO", "Started Prometheus metrics server on port 9117")
        while True:
            sentry.monitor()
            time.sleep(10)

if __name__ == '__main__':
    main()
