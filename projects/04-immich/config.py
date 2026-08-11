import os
from pathlib import Path

# NAS paths for Immich photo storage and database
NAS_MEDIA_VAULT = Path(os.getenv("NAS_MEDIA_VAULT", "/mnt/nas/media_vault"))

NAS_BINDINGS = {
    "UPLOAD_LOCATION": str(NAS_MEDIA_VAULT / "immich" / "library"),
    "DB_DATA_LOCATION": str(NAS_MEDIA_VAULT / "immich" / "postgres"),
}
