import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
WORKSPACE_DIR = Path(os.getenv("AGENT_WORKSPACE_DIR", "/tmp/agent_swarm_workspace"))
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

REPOSITORIES = [
    "deepshah08/raspberry-pi-5-ecosystem",
    "deepshah08/Learning",
    "deepshah08/antigravity_projects"
]

POLL_INTERVAL_SECONDS = 300  # 5 minutes per Antigravity v2.0 pipeline specs
MAX_CONCURRENT_REVIEWS = 2
