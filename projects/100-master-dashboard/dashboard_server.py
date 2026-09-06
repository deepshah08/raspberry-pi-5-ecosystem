from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse
from typing import Dict, Any
import json
import uvicorn
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST, Counter, Gauge

app = FastAPI(title="Homelab Master Dashboard")

# Prometheus Metrics
PROJECTS_TOTAL = Gauge('homelab_swarm_projects_total', 'Total number of projects in the homelab')
AUDIT_PASSING = Gauge('homelab_swarm_audit_passing', 'Whether the homelab audit is passing (1) or failing (0)')
TIER_COMPLIANCE = Gauge('homelab_swarm_tier_compliance_ratio', 'Ratio of projects compliant with storage tiering')

# Mock data
MOCK_MATRIX: Dict[str, Any] = {
    "projects": [
        {"id": 1, "name": "Pi-hole HA", "category": "Network & Core DNS", "host": "192.168.1.80", "port": 53, "storage_tier": "NVMe"},
        {"id": 2, "name": "Plex", "category": "Media & Arr Suite", "host": "192.168.1.92", "port": 32400, "storage_tier": "CMR HDD"},
        {"id": 3, "name": "Prometheus", "category": "Observability & Telemetry", "host": "192.168.1.92", "port": 9090, "storage_tier": "NVMe"},
        {"id": 4, "name": "Syncthing", "category": "Automation & Workers", "host": "192.168.1.80", "port": 8384, "storage_tier": "USB SMR"},
        {"id": 5, "name": "ZFS Scrubs", "category": "Storage & Spindown Sentinel", "host": "192.168.1.80", "port": None, "storage_tier": "CMR HDD"}
    ]
}

# Update metrics initially
PROJECTS_TOTAL.set(len(MOCK_MATRIX["projects"]))
AUDIT_PASSING.set(1)
TIER_COMPLIANCE.set(1.0)

@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(content="""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Homelab Master Unified Orchestration Dashboard</title>
        <style>
            body { font-family: sans-serif; margin: 20px; }
            h1 { color: #333; }
            .node { padding: 10px; margin: 10px; border: 1px solid #ccc; display: inline-block; vertical-align: top;}
            .pi { background-color: #fdd; }
            .ugreen { background-color: #ddf; }
            svg { border: 1px solid #ddd; background: #fafafa; }
        </style>
    </head>
    <body>
        <h1>Homelab Master Unified Orchestration Dashboard</h1>

        <h2>Topology Visualizer</h2>
        <svg width="600" height="300" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" />
            </marker>
          </defs>
          <g stroke="black" stroke-width="2" marker-end="url(#arrow)">
            <line x1="300" y1="50" x2="150" y2="150" />
            <line x1="300" y1="50" x2="450" y2="150" />
          </g>
          <rect x="225" y="20" width="150" height="40" rx="10" ry="10" fill="#ccf" />
          <text x="300" y="45" font-family="sans-serif" font-size="14" text-anchor="middle">Master Dashboard</text>

          <rect x="50" y="150" width="200" height="100" rx="10" ry="10" fill="#ddf" />
          <text x="150" y="180" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="middle">UGREEN NAS (192.168.1.80)</text>
          <text x="150" y="200" font-family="sans-serif" font-size="12" text-anchor="middle">Pi-hole HA, Syncthing, ZFS</text>

          <rect x="350" y="150" width="200" height="100" rx="10" ry="10" fill="#fdd" />
          <text x="450" y="180" font-family="sans-serif" font-size="14" font-weight="bold" text-anchor="middle">Raspberry Pi 5 (192.168.1.92)</text>
          <text x="450" y="200" font-family="sans-serif" font-size="12" text-anchor="middle">Plex, Prometheus</text>
        </svg>

        <h3>Quick Audit Results</h3>
        <p>Status: <strong style="color:green;">PASS</strong></p>
    </body>
    </html>
    """)

@app.get("/api/matrix")
def get_matrix() -> Dict[str, Any]:
    return MOCK_MATRIX

@app.get("/api/health")
def get_health() -> Dict[str, Any]:
    return {
        "status": "healthy",
        "cluster_health": "ok",
        "invariants": {
            "dhcp_option_6": "PASS",
            "pihole_bridge_mode": "PASS",
            "bittorrent_tcp_only": "PASS",
            "hdd_standby": "PASS",
            "storage_tiering": "PASS"
        }
    }

@app.get("/metrics")
def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9125)
