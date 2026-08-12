import os
import json
import requests

def main():
    radarr_url = os.environ.get("RADARR_URL", "http://localhost:7878")
    radarr_api_key = os.environ.get("RADARR_API_KEY")

    if not radarr_api_key:
        print("Error: RADARR_API_KEY environment variable is not set.")
        return

    config_path = os.path.join(os.path.dirname(__file__), "radarr_custom_formats.json")
    try:
        with open(config_path, "r") as f:
            custom_formats = json.load(f)
    except FileNotFoundError:
        print(f"Error: Could not find {config_path}")
        return
    except json.JSONDecodeError:
        print(f"Error: {config_path} is not valid JSON")
        return

    headers = {
        "X-Api-Key": radarr_api_key,
        "Content-Type": "application/json"
    }

    print("Fetching existing custom formats...")
    try:
        response = requests.get(f"{radarr_url}/api/v3/customformat", headers=headers)
        response.raise_for_status()
        existing_formats = response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching existing custom formats: {e}")
        return

    existing_formats_by_name = {f["name"]: f for f in existing_formats}

    for cf in custom_formats:
        name = cf["name"]
        if name in existing_formats_by_name:
            # Update
            existing_cf = existing_formats_by_name[name]
            cf["id"] = existing_cf["id"]
            print(f"Updating custom format: {name} (ID: {existing_cf['id']})")
            try:
                response = requests.put(
                    f"{radarr_url}/api/v3/customformat/{existing_cf['id']}",
                    headers=headers,
                    json=cf
                )
                response.raise_for_status()
                print(f"Successfully updated {name}")
            except requests.exceptions.RequestException as e:
                print(f"Error updating {name}: {e}")
        else:
            # Create
            print(f"Creating custom format: {name}")
            try:
                response = requests.post(
                    f"{radarr_url}/api/v3/customformat",
                    headers=headers,
                    json=cf
                )
                response.raise_for_status()
                created_cf = response.json()
                print(f"Successfully created {name} (ID: {created_cf['id']})")
            except requests.exceptions.RequestException as e:
                print(f"Error creating {name}: {e}")

    print("\nFetching existing quality profiles...")
    try:
        response = requests.get(f"{radarr_url}/api/v3/qualityprofile", headers=headers)
        response.raise_for_status()
        profiles = response.json()
        print("Existing Quality Profiles:")
        for profile in profiles:
            print(f"- {profile['name']} (ID: {profile['id']})")
    except requests.exceptions.RequestException as e:
        print(f"Error fetching quality profiles: {e}")

if __name__ == "__main__":
    main()
