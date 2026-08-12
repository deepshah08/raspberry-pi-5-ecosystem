import os
import sys
import json
import urllib.request
import urllib.error

def main():
    # 1. Read BAZARR_URL and BAZARR_API_KEY
    bazarr_url = os.environ.get("BAZARR_URL", "http://localhost:6767").rstrip("/")
    bazarr_api_key = os.environ.get("BAZARR_API_KEY")

    if not bazarr_api_key:
        print("Error: BAZARR_API_KEY environment variable is missing.", file=sys.stderr)
        sys.exit(1)

    headers = {
        "X-Api-Key": bazarr_api_key,
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    # 2. Verify connection with GET /api/system/status
    print(f"Connecting to Bazarr at {bazarr_url}...")
    try:
        req = urllib.request.Request(f"{bazarr_url}/api/system/status", headers=headers)
        with urllib.request.urlopen(req) as response:
            status_data = json.loads(response.read().decode("utf-8"))
            print("Successfully connected to Bazarr API.")
    except urllib.error.URLError as e:
        print(f"Error connecting to Bazarr API: {e}", file=sys.stderr)
        sys.exit(1)

    # 3. Patch subtitle language settings via PUT /api/settings
    settings_payload = {
        "subtitles": {
            "serie_default_language": ["en"],
            "movie_default_language": ["en"],
            "serie_default_hi": False,
            "movie_default_hi": False
        }
    }
    
    # Bazarr uses PATCH to /api/settings typically, but instructions say PUT.
    # Often PUT to settings requires the full payload, while PATCH allows partial.
    # Following instruction: "PATCH subtitle language settings via PUT /api/settings"
    # Actually, Bazarr API supports PATCH for partial updates to settings.
    # Let's try PATCH first as it's safer for partial updates.
    print("Enforcing English-only subtitle settings...")
    try:
        req = urllib.request.Request(
            f"{bazarr_url}/api/settings",
            data=json.dumps(settings_payload).encode("utf-8"),
            headers=headers,
            method="PATCH"
        )
        with urllib.request.urlopen(req) as response:
            if response.status in (200, 204):
                print("Subtitle settings successfully updated.")
            else:
                print(f"Unexpected status when updating settings: {response.status}")
    except urllib.error.URLError as e:
        print(f"Error updating Bazarr settings: {e}", file=sys.stderr)
        # Attempt PUT if PATCH fails, though PATCH is standard for Bazarr partial settings
        try:
            print("PATCH failed, trying PUT...")
            req = urllib.request.Request(
                f"{bazarr_url}/api/settings",
                data=json.dumps(settings_payload).encode("utf-8"),
                headers=headers,
                method="PUT"
            )
            with urllib.request.urlopen(req) as response:
                if response.status in (200, 204):
                    print("Subtitle settings successfully updated using PUT.")
                else:
                    print(f"Unexpected status when updating settings: {response.status}")
        except urllib.error.URLError as e2:
             print(f"Error updating Bazarr settings with PUT: {e2}", file=sys.stderr)
             sys.exit(1)


    # 4. Print current subtitle provider list
    print("Fetching subtitle providers...")
    try:
        req = urllib.request.Request(f"{bazarr_url}/api/providers", headers=headers)
        with urllib.request.urlopen(req) as response:
            providers = json.loads(response.read().decode("utf-8"))
            print("Current subtitle providers:")
            if "data" in providers:
                # Bazarr often returns { "data": [...] }
                provider_list = providers["data"]
            else:
                provider_list = providers
                
            for provider in provider_list:
                 name = provider.get("name", "Unknown")
                 enabled = provider.get("enabled", False)
                 status = "Enabled" if enabled else "Disabled"
                 print(f" - {name}: {status}")
                 
    except urllib.error.URLError as e:
        print(f"Error fetching providers: {e}", file=sys.stderr)
        sys.exit(1)

    # 5. Exit with 0 on success
    print("Bazarr configuration applied successfully.")
    sys.exit(0)

if __name__ == "__main__":
    main()