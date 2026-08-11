import subprocess
import json
import sys

# Thresholds
TEMP_THRESHOLD = 80.0  # Celsius
RAM_PERCENT_THRESHOLD = 90.0
DISK_PERCENT_THRESHOLD = 90.0

def parse_cpu_temp(output: str) -> float:
    output = output.strip()
    if output.startswith("temp="):
        # temp=45.3'C
        val_str = output.replace("temp=", "").replace("'C", "")
        try:
            return float(val_str)
        except ValueError:
            return 0.0
    elif output.isdigit():
        return float(output) / 1000.0
    return 0.0

def get_cpu_temp() -> float:
    try:
        result = subprocess.run(["vcgencmd", "measure_temp"], capture_output=True, text=True, check=True)
        return parse_cpu_temp(result.stdout)
    except (subprocess.CalledProcessError, FileNotFoundError):
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                return parse_cpu_temp(f.read())
        except FileNotFoundError:
            return 0.0

def parse_meminfo(output: str) -> dict:
    mem_total = 0
    mem_available = 0
    for line in output.split('\n'):
        if line.startswith("MemTotal:"):
            try:
                mem_total = int(line.split()[1])
            except (IndexError, ValueError):
                pass
        elif line.startswith("MemAvailable:"):
            try:
                mem_available = int(line.split()[1])
            except (IndexError, ValueError):
                pass
    
    mem_used = mem_total - mem_available
    percent_used = (mem_used / mem_total * 100) if mem_total > 0 else 0.0
    return {
        "total_kb": mem_total,
        "available_kb": mem_available,
        "used_kb": mem_used,
        "percent_used": round(percent_used, 2)
    }

def get_ram_usage() -> dict:
    try:
        with open("/proc/meminfo", "r") as f:
            return parse_meminfo(f.read())
    except FileNotFoundError:
        return {"total_kb": 0, "available_kb": 0, "used_kb": 0, "percent_used": 0.0}

def parse_throttled(output: str) -> dict:
    output = output.strip()
    if output.startswith("throttled="):
        val_str = output.replace("throttled=", "")
        try:
            val = int(val_str, 16)
        except ValueError:
            val = 0
    else:
        val = 0
        
    return {
        "raw": hex(val),
        "under_voltage_detected": bool(val & 0x1),
        "arm_frequency_capped": bool(val & 0x2),
        "currently_throttled": bool(val & 0x4),
        "soft_temperature_limit_active": bool(val & 0x8),
        "under_voltage_occurred": bool(val & 0x10000),
        "arm_frequency_capped_occurred": bool(val & 0x20000),
        "throttling_occurred": bool(val & 0x40000),
        "soft_temperature_limit_occurred": bool(val & 0x80000)
    }

def get_throttled() -> dict:
    try:
        result = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, check=True)
        return parse_throttled(result.stdout)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return parse_throttled("throttled=0x0")

def parse_df(output: str) -> dict:
    disks = {}
    lines = output.strip().split('\n')
    if len(lines) > 1:
        for line in lines[1:]:
            parts = line.split()
            if len(parts) >= 6:
                fs = parts[0]
                mount_point = parts[5]
                # Monitor typically NVMe, SD, or root mount
                if "/dev/nvme" in fs or "/dev/mmcblk" in fs or "/dev/root" in fs or mount_point == "/":
                    try:
                        percent_str = parts[4].replace('%', '')
                        percent = float(percent_str)
                    except ValueError:
                        percent = 0.0
                    
                    disks[mount_point] = {
                        "filesystem": fs,
                        "size": parts[1],
                        "used": parts[2],
                        "available": parts[3],
                        "percent_used": percent
                    }
    return disks

def get_disk_space() -> dict:
    try:
        result = subprocess.run(["df", "-k"], capture_output=True, text=True, check=True)
        return parse_df(result.stdout)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {}

def main():
    temp = get_cpu_temp()
    ram = get_ram_usage()
    throttled = get_throttled()
    disks = get_disk_space()

    health_status = {
        "cpu_temperature": temp,
        "ram_usage": ram,
        "throttling": throttled,
        "disks": disks,
        "alerts": []
    }

    if temp > TEMP_THRESHOLD:
        health_status["alerts"].append(f"CPU Temperature is high: {temp}C")
        
    if ram.get("percent_used", 0) > RAM_PERCENT_THRESHOLD:
        health_status["alerts"].append(f"RAM usage is high: {ram['percent_used']}%")
        
    if throttled.get("currently_throttled", False):
        health_status["alerts"].append("System is currently throttled")
        
    if throttled.get("under_voltage_detected", False):
        health_status["alerts"].append("Under-voltage detected")

    for mount, info in disks.items():
        if info["percent_used"] > DISK_PERCENT_THRESHOLD:
            health_status["alerts"].append(f"Disk space is low on {mount}: {info['percent_used']}% used")

    print(json.dumps(health_status, indent=2))
    
    if health_status["alerts"]:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()
