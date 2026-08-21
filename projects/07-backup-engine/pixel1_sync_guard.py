import os
import hashlib
import subprocess
import time

class PixelSyncGuard:
    def __init__(self, staging_dir="/mnt/nas/photos_staging", remote_dir="/sdcard/DCIM/NAS_Sync"):
        self.staging_dir = staging_dir
        self.remote_dir = remote_dir

    def get_local_checksum(self, file_path):
        if not os.path.exists(file_path):
            return None
        hash_md5 = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception:
            return None

    def get_remote_checksum(self, file_name):
        import shlex
        remote_path = f"{self.remote_dir}/{file_name}"
        quoted_remote_path = shlex.quote(remote_path)
        try:
            result = subprocess.run(
                ["adb", "shell", f"md5sum {quoted_remote_path}"],
                capture_output=True,
                text=True,
                check=True
            )
            output = result.stdout.strip()
            if output:
                return output.split()[0]
            return None
        except subprocess.CalledProcessError:
            return None

    def should_purge(self, file_path, days=3):
        if not os.path.exists(file_path):
            return False
        file_age_seconds = time.time() - os.path.getmtime(file_path)
        return file_age_seconds > (days * 24 * 60 * 60)

    def run(self, days=3):
        if not os.path.exists(self.staging_dir):
            return

        for filename in os.listdir(self.staging_dir):
            file_path = os.path.join(self.staging_dir, filename)

            if not os.path.isfile(file_path):
                continue

            local_md5 = self.get_local_checksum(file_path)
            remote_md5 = self.get_remote_checksum(filename)

            if local_md5 and remote_md5 and local_md5 == remote_md5:
                if self.should_purge(file_path, days=days):
                    try:
                        os.remove(file_path)
                    except Exception:
                        pass


if __name__ == "__main__":
    guard = PixelSyncGuard()
    guard.run()