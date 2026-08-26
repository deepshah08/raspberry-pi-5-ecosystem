import os
from pathlib import Path
try:
    from immich_config import NAS_BINDINGS
except ImportError:
    from config import NAS_BINDINGS

def validate():
    all_valid = True
    print("Validating NAS path bindings for Immich...")
    for key, path in NAS_BINDINGS.items():
        p = Path(path)
        if p.exists() or p.parent.exists():
            print(f"✅ {key}: '{path}' path check passed.")
        else:
            print(f"⚠️ {key}: '{path}' parent directory missing.")
            all_valid = False
            
    return all_valid

if __name__ == "__main__":
    validate()
