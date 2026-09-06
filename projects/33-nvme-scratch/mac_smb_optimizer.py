import os
import subprocess
from pathlib import Path
from typing import Dict, Any


class MacSMBOptimizer:
    def __init__(self, nsmb_path: str = "~/Library/Preferences/nsmb.conf"):
        self.nsmb_path = Path(nsmb_path).expanduser()
        self.default_config: Dict[str, Dict[str, str]] = {
            "default": {
                "mc_on": "yes",
                "mc_prefer_wired": "yes",
                "client_signing": "no",
                "dir_cache_max_cnt": "0",
                "dir_cache_max": "0",
                "dir_cache_min": "0"
            }
        }

    def generate_nsmb_conf_content(self, config: Dict[str, Dict[str, str]]) -> str:
        content = ""
        for section, params in config.items():
            content += f"[{section}]\n"
            for key, value in params.items():
                content += f"{key}={value}\n"
            content += "\n"
        return content.strip() + "\n"

    def apply_nsmb_tuning(self) -> None:
        """Applies SMB3 multichannel and tuning parameters to nsmb.conf"""
        self.nsmb_path.parent.mkdir(parents=True, exist_ok=True)
        content = self.generate_nsmb_conf_content(self.default_config)
        self.nsmb_path.write_text(content)
        print(f"Applied nsmb.conf tuning at {self.nsmb_path}")

    def disable_ds_store_on_network(self) -> None:
        """Disables .DS_Store generation on network mounts"""
        try:
            subprocess.run(
                ["defaults", "write", "com.apple.desktopservices", "DSDontWriteNetworkStores", "-bool", "TRUE"],
                check=True,
                capture_output=True,
                text=True
            )
            print("Successfully disabled .DS_Store generation on network mounts.")
        except subprocess.CalledProcessError as e:
            print(f"Failed to disable .DS_Store: {e.stderr}")

    def configure_tcp_window_scaling(self) -> None:
        """Configures TCP window scaling"""
        try:
            subprocess.run(
                ["sysctl", "-w", "net.inet.tcp.rfc1323=1"],
                check=True,
                capture_output=True,
                text=True
            )
            print("Successfully enabled TCP window scaling.")
        except subprocess.CalledProcessError as e:
            print(f"Failed to configure TCP window scaling: {e.stderr}")

    def validate_nvme_permissions(self, mount_point: str = "/volume2/scratch") -> bool:
        """Validates NVMe mount point permissions"""
        path = Path(mount_point)
        if not path.exists():
            print(f"Mount point {mount_point} does not exist.")
            return False

        if not os.access(path, os.R_OK | os.W_OK | os.X_OK):
            print(f"Insufficient permissions on {mount_point}. Require read, write, and execute.")
            return False

        print(f"Permissions validated on {mount_point}.")
        return True

    def optimize_all(self):
        self.apply_nsmb_tuning()
        self.disable_ds_store_on_network()
        self.configure_tcp_window_scaling()
        self.validate_nvme_permissions()

if __name__ == "__main__":
    optimizer = MacSMBOptimizer()
    optimizer.optimize_all()
