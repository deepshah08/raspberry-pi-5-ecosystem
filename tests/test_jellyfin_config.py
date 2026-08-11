import unittest
import sys
import os

# Add the project directory to sys.path so we can import validate_setup
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../projects/05-jellyfin')))

import validate_setup

class TestJellyfinConfig(unittest.TestCase):

    def test_valid_config(self):
        valid_config = """
version: '3.8'
services:
  jellyfin:
    image: lscr.io/linuxserver/jellyfin:latest
    container_name: jellyfin
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=Etc/UTC
    volumes:
      - ./config:/config
      - /mnt/nas/media_vault:/data/media
    devices:
      - /dev/dri:/dev/dri
      - /dev/video10:/dev/video10
      - /dev/video11:/dev/video11
      - /dev/video12:/dev/video12
    ports:
      - 8096:8096
    restart: unless-stopped
        """
        is_valid, message = validate_setup.validate_compose(valid_config)
        self.assertTrue(is_valid)
        self.assertEqual(message, "Validation passed.")

    def test_missing_jellyfin_service(self):
        missing_service_config = """
version: '3.8'
services:
  plex:
    image: linuxserver/plex
        """
        is_valid, message = validate_setup.validate_compose(missing_service_config)
        self.assertFalse(is_valid)
        self.assertEqual(message, "Jellyfin service not found.")

    def test_missing_nas_binding(self):
        missing_nas_config = """
version: '3.8'
services:
  jellyfin:
    image: lscr.io/linuxserver/jellyfin:latest
    volumes:
      - ./config:/config
    devices:
      - /dev/dri:/dev/dri
        """
        is_valid, message = validate_setup.validate_compose(missing_nas_config)
        self.assertFalse(is_valid)
        self.assertEqual(message, "NAS media path binding /mnt/nas/media_vault not found.")

    def test_missing_hardware_acceleration(self):
        missing_hw_config = """
version: '3.8'
services:
  jellyfin:
    image: lscr.io/linuxserver/jellyfin:latest
    volumes:
      - ./config:/config
      - /mnt/nas/media_vault:/data/media
        """
        is_valid, message = validate_setup.validate_compose(missing_hw_config)
        self.assertFalse(is_valid)
        self.assertEqual(message, "V4L2/VAAPI hardware acceleration devices not found.")

if __name__ == '__main__':
    unittest.main()
