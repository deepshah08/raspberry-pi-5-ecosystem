import argparse
import json
import logging
import sys
import time
from typing import Dict, Any

import paho.mqtt.client as mqtt
from prometheus_client import start_http_server, Gauge

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

ZIGBEE_DEVICES_TOTAL = Gauge('homelab_zigbee_devices_total', 'Total number of Zigbee devices')
ZIGBEE_LQI_AVERAGE = Gauge('homelab_zigbee_lqi_average', 'Average LQI of Zigbee network')
ZIGBEE_OFFLINE_TOTAL = Gauge('homelab_zigbee_offline_nodes_total', 'Total number of offline Zigbee nodes')

class MeshSentinel:
    def __init__(self, broker: str, port: int, dry_run: bool = False, json_output: bool = False, audit_now: bool = False):
        self.broker = broker
        self.port = port
        self.dry_run = dry_run
        self.json_output = json_output
        self.audit_now = audit_now

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

        self.devices: Dict[str, Any] = {}

    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            if not self.json_output:
                logger.info(f"Connected to MQTT broker at {self.broker}:{self.port}")
            client.subscribe("zigbee2mqtt/bridge/devices")
            client.subscribe("zigbee2mqtt/bridge/state")
            client.subscribe("zigbee2mqtt/+")
        else:
            if not self.json_output:
                logger.error(f"Failed to connect, return code {reason_code}")

    def on_message(self, client, userdata, msg):
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
        except json.JSONDecodeError:
            return

        if topic == "zigbee2mqtt/bridge/devices":
            self._handle_bridge_devices(payload)
        elif topic.startswith("zigbee2mqtt/") and not topic.startswith("zigbee2mqtt/bridge"):
            self._handle_device_message(topic, payload)

        self._analyze_mesh()

    def _handle_bridge_devices(self, payload):
        if isinstance(payload, list):
            for device in payload:
                if 'friendly_name' in device:
                    name = device['friendly_name']
                    if name not in self.devices:
                        self.devices[name] = device
                    else:
                        self.devices[name].update(device)

    def _handle_device_message(self, topic, payload):
        device_name = topic.split("/")[-1]

        if device_name not in self.devices:
            self.devices[device_name] = {}

        if 'linkquality' in payload:
            self.devices[device_name]['linkquality'] = payload['linkquality']
        if 'state' in payload:
            self.devices[device_name]['state'] = payload['state']

        if 'availability' in payload:
            if isinstance(payload['availability'], dict) and 'state' in payload['availability']:
                self.devices[device_name]['availability'] = payload['availability']['state']
            elif isinstance(payload['availability'], str):
                self.devices[device_name]['availability'] = payload['availability']

    def _analyze_mesh(self):
        total_devices = len(self.devices)
        lqi_values = []
        offline_nodes = 0
        weak_links = []

        for name, data in self.devices.items():
            if data.get('type') == 'Coordinator':
                continue

            lqi = data.get('linkquality')
            if lqi is not None:
                lqi_values.append(lqi)
                if lqi < 50:
                    weak_links.append((name, lqi))

            is_offline = False
            availability = data.get('availability')

            if availability == 'offline':
                is_offline = True

            if is_offline:
                offline_nodes += 1

        avg_lqi = sum(lqi_values) / len(lqi_values) if lqi_values else 0

        if not self.dry_run:
            ZIGBEE_DEVICES_TOTAL.set(total_devices)
            ZIGBEE_LQI_AVERAGE.set(avg_lqi)
            ZIGBEE_OFFLINE_TOTAL.set(offline_nodes)

        return {
            'total_devices': total_devices,
            'average_lqi': avg_lqi,
            'offline_nodes': offline_nodes,
            'weak_links': weak_links
        }

    def start(self):
        if not self.dry_run and not self.audit_now:
            start_http_server(9132)

        try:
            self.client.connect(self.broker, self.port, 60)
        except Exception as e:
            logger.error(f"Error connecting to MQTT broker: {e}")
            sys.exit(1)

        if self.audit_now:
            self.client.loop_start()
            time.sleep(2)  # Give time to receive retained messages
            self.client.loop_stop()
            report = self._analyze_mesh()
            if self.json_output:
                print(json.dumps(report, indent=2))
            else:
                print("--- Mesh Audit Report ---")
                print(f"Total Devices: {report['total_devices']}")
                print(f"Average LQI: {report['average_lqi']:.2f}")
                print(f"Offline Nodes: {report['offline_nodes']}")
                if report['weak_links']:
                    print("Weak Links (LQI < 50):")
                    for name, lqi in report['weak_links']:
                        print(f"  - {name}: {lqi}")
        else:
            self.client.loop_forever()

def main():
    parser = argparse.ArgumentParser(description="Homelab Zigbee & Z-Wave MQTT Mesh Health Sentinel")
    parser.add_argument("--broker", type=str, default="localhost", help="MQTT broker host")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--audit-now", action="store_true", help="Run audit immediately and exit")
    parser.add_argument("--dry-run", action="store_true", help="Do not expose metrics")
    parser.add_argument("--json", action="store_true", help="Output audit report in JSON format")

    args = parser.parse_args()

    sentinel = MeshSentinel(
        broker=args.broker,
        port=args.port,
        dry_run=args.dry_run,
        json_output=args.json,
        audit_now=args.audit_now
    )

    sentinel.start()

if __name__ == "__main__":
    main()
