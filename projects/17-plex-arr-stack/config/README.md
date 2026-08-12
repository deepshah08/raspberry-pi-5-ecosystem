# Config

This directory contains configuration scripts and custom formats for Radarr and Sonarr.

## Custom Formats

We use custom formats to score releases so that Radarr and Sonarr prefer Hindi and Dual Audio releases.

The custom formats include:
- **Hindi Audio** (+500)
- **Dual Audio** (+400)
- **Hindi Dubbed** (+300)
- **English Audio** (+200)
- **Non EN-HI Audio** (-1000)

## How to Apply Configurations

To apply these configurations to Radarr and Sonarr, you can run the provided Python scripts. You must provide the API keys and URLs via environment variables.

### Applying to Radarr

```bash
export RADARR_URL="http://localhost:7878" # Defaults to this if not set
export RADARR_API_KEY="your_radarr_api_key_here"
python config/radarr_apply_config.py
```

### Applying to Sonarr

```bash
export SONARR_URL="http://localhost:8989" # Defaults to this if not set
export SONARR_API_KEY="your_sonarr_api_key_here"
python config/sonarr_apply_config.py
```

## Assigning Scores in the UI

After running the scripts to create the custom formats, you must assign scores to them in your Quality Profiles inside Radarr and Sonarr UI.

1. Go to **Settings** > **Profiles** in Radarr/Sonarr.
2. Edit your quality profile.
3. Under **Custom Formats**, add the created custom formats and assign the following scores:
   - Hindi Audio: `+500`
   - Dual Audio: `+400`
   - Hindi Dubbed: `+300`
   - English Audio: `+200`
   - Non EN-HI Audio: `-1000` (This is crucial to reject pure Tamil/Telugu/etc releases)

## Recommended Quality Profile

For the Raspberry Pi 5 ecosystem, we recommend prioritizing 1080p content as 4K is not needed. A good priority order is:

1. `1080p Bluray`
2. `1080p WEB-DL`
3. `720p WEB-DL`
