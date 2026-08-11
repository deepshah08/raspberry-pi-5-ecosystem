import sys
import re
import os

def validate_compose(content):
    if "jellyfin:" not in content:
        return False, "Jellyfin service not found."
    
    if "/mnt/nas/media_vault" not in content:
        return False, "NAS media path binding /mnt/nas/media_vault not found."
    
    if not (re.search(r"/dev/video\d+", content) or "/dev/dri" in content):
        return False, "V4L2/VAAPI hardware acceleration devices not found."

    return True, "Validation passed."

def main(filepath="docker-compose.jellyfin.yml"):
    try:
        with open(filepath, "r") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"{filepath} not found.")
        sys.exit(1)
        
    is_valid, message = validate_compose(content)
    if is_valid:
        print(message)
        sys.exit(0)
    else:
        print(f"Validation failed: {message}")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        main(sys.argv[1])
    else:
        # Default to the same directory as the script if no arg is given
        script_dir = os.path.dirname(os.path.abspath(__file__))
        default_file = os.path.join(script_dir, "docker-compose.jellyfin.yml")
        main(default_file)
