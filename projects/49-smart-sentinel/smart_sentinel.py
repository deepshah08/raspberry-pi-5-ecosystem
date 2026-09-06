import json
import logging
import subprocess
import time
import os
import requests
from prometheus_client import start_http_server, Gauge, Enum

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Metrics
SMART_NVME_PERCENTAGE_USED = Gauge('smart_nvme_percentage_used', 'NVMe Percentage Used', ['device'])
SMART_NVME_AVAILABLE_SPARE = Gauge('smart_nvme_available_spare', 'NVMe Available Spare', ['device'])
SMART_NVME_TBW_WRITTEN_TERABYTES = Gauge('smart_nvme_tbw_written_terabytes', 'NVMe TBW Written in Terabytes', ['device'])
SMART_NVME_LIFESPAN_REMAINING_PERCENT = Gauge('smart_nvme_lifespan_remaining_percent', 'Predicted NVMe Lifespan Remaining Percent vs Rated TBW', ['device'])
SMART_HDD_REALLOCATED_SECTORS = Gauge('smart_hdd_reallocated_sectors', 'HDD Reallocated Sector Count', ['device'])
SMART_HDD_SPIN_RETRY_COUNT = Gauge('smart_hdd_spin_retry_count', 'HDD Spin Retry Count', ['device'])
SMART_DRIVE_TEMPERATURE_CELSIUS = Gauge('smart_drive_temperature_celsius', 'Drive Temperature in Celsius', ['device'])
SMART_DISK_STANDBY_STATE = Gauge('smart_disk_standby_state', 'Disk Standby State (1 = active/idle, 0 = standby)', ['device'])

# Target Drives configuration (paths could be overridden for testing)
DRIVES = {
    '/dev/nvme0n1': {'type': 'nvme', 'name': '4TB WD_BLACK SN850X'},
    '/dev/sda': {'type': 'hdd', 'name': '10TB Seagate IronWolf'},
    '/dev/sdb': {'type': 'usb', 'name': '8TB Seagate Expansion'}
}

# Constants
NVME_LBA_SIZE_BYTES = 512000  # "Data Units Written" typically means thousands of 512-byte blocks. NVMe spec uses 512,000 bytes per unit.
NVME_RATED_TBW = 2400 # 2400 TBW for 4TB SN850X
MAX_TEMP_CELSIUS = 70
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

def send_telegram_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning(f"Telegram credentials missing, cannot send alert: {message}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": f"🚨 SMART Sentinel Alert 🚨\n{message}"
    }
    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to send Telegram alert: {e}")

def run_smartctl(device):
    # -i ensures it only gets info first if standby is true, but -a gets all info.
    # -n standby skips querying smart info if the drive is in standby.
    cmd = ['smartctl', '-a', '-j', '-n', 'standby', device]
    try:
        # Exit code bit 0 (command line did not parse) and 1 (device open failed) are critical.
        # Exit code bit 1 (device open failed) is usually set if it's in standby and -n standby is given, but smartctl exits with code 2 for SLEEP/STANDBY.
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        # Even with non-zero exit code, smartctl outputs valid JSON for standby state usually.
        return result.stdout, result.returncode
    except Exception as e:
        logger.error(f"Error executing smartctl for {device}: {e}")
        return "{}", -1

def parse_smart_data(device, data_json, device_info):
    try:
        data = json.loads(data_json)
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON output from smartctl for {device}")
        return

    # Check power mode
    power_mode = data.get('power_cycle_info', {}).get('power_mode', 'active') # Default to active if unknown

    # smartctl returns "STANDBY" in messages if -n standby aborted it.
    messages = data.get('smartctl', {}).get('messages', [])
    in_standby = False
    for msg in messages:
        if 'STANDBY' in msg.get('string', '').upper() or 'SLEEP' in msg.get('string', '').upper():
            in_standby = True
            break

    if data.get('power_mode') == 'standby' or data.get('power_mode') == 'sleep':
        in_standby = True

    if in_standby:
        logger.info(f"Device {device} ({device_info['name']}) is in STANDBY/SLEEP. Skipping SMART data collection.")
        SMART_DISK_STANDBY_STATE.labels(device=device).set(0)
        return

    SMART_DISK_STANDBY_STATE.labels(device=device).set(1)

    # Process NVMe metrics
    if device_info['type'] == 'nvme':
        nvme_smart = data.get('nvme_smart_health_information_log', {})
        if nvme_smart:
            percentage_used = nvme_smart.get('percentage_used', 0)
            available_spare = nvme_smart.get('available_spare', 100)
            data_units_written = nvme_smart.get('data_units_written', 0)
            temp = nvme_smart.get('temperature', 0)
            critical_warning = nvme_smart.get('critical_warning', 0)

            SMART_NVME_PERCENTAGE_USED.labels(device=device).set(percentage_used)
            SMART_NVME_AVAILABLE_SPARE.labels(device=device).set(available_spare)

            # Calculate TBW (Terabytes Written)
            tbw = (data_units_written * NVME_LBA_SIZE_BYTES) / (10**12)
            SMART_NVME_TBW_WRITTEN_TERABYTES.labels(device=device).set(tbw)

            # Predict Remaining Lifespan
            remaining_tbw = max(0, NVME_RATED_TBW - tbw)
            lifespan_percent = (remaining_tbw / NVME_RATED_TBW) * 100.0
            SMART_NVME_LIFESPAN_REMAINING_PERCENT.labels(device=device).set(lifespan_percent)

            SMART_DRIVE_TEMPERATURE_CELSIUS.labels(device=device).set(temp)

            if critical_warning > 0:
                send_telegram_alert(f"Critical Warning on {device_info['name']} ({device}): {critical_warning}")

            if temp > MAX_TEMP_CELSIUS:
                send_telegram_alert(f"High Temperature on {device_info['name']} ({device}): {temp}°C")

    # Process HDD/USB CMR/SMR metrics
    elif device_info['type'] in ['hdd', 'usb']:
        temp = data.get('temperature', {}).get('current', 0)
        if temp:
            SMART_DRIVE_TEMPERATURE_CELSIUS.labels(device=device).set(temp)
            if temp > MAX_TEMP_CELSIUS:
                send_telegram_alert(f"High Temperature on {device_info['name']} ({device}): {temp}°C")

        ata_smart = data.get('ata_smart_attributes', {}).get('table', [])
        for attr in ata_smart:
            name = attr.get('name', '')
            raw_value = attr.get('raw', {}).get('value', 0)

            if name == 'Reallocated_Sector_Ct':
                SMART_HDD_REALLOCATED_SECTORS.labels(device=device).set(raw_value)
                if raw_value > 0:
                    send_telegram_alert(f"Reallocated Sectors on {device_info['name']} ({device}): {raw_value}")
            elif name == 'Spin_Retry_Count':
                SMART_HDD_SPIN_RETRY_COUNT.labels(device=device).set(raw_value)
                if raw_value > 0:
                    send_telegram_alert(f"Spin Retry Count > 0 on {device_info['name']} ({device}): {raw_value}")

def collect_metrics():
    for device, info in DRIVES.items():
        if not os.path.exists(device) and not os.environ.get('TESTING'):
            logger.warning(f"Device {device} not found. Skipping.")
            continue

        stdout, rc = run_smartctl(device)
        if stdout:
            parse_smart_data(device, stdout, info)

if __name__ == '__main__':
    port = 9106
    start_http_server(port)
    logger.info(f"Started SMART Sentinel Prometheus exporter on port {port}")

    while True:
        collect_metrics()
        time.sleep(60)
