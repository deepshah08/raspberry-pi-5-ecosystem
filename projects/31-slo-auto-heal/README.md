# Project 31: SLO Auto-Heal & Automated Remediation Daemon

This project implements an autonomous self-healing bridge for the homelab or production environment. It monitors the SLO Watchdog incident logs, identifies critical severity issues, and dispatches an autonomous remediation session via API to attempt remediation and open a pull request.

The system consists of a Python daemon running as a systemd service that tails a JSONL log file of incidents. When a SEV-1 or persistent SEV-2 incident is detected, it crafts a remediation prompt and dispatches an API call to the remediation agent, as well as an alert to Telegram. Duplicate detection is implemented to prevent dispatching multiple sessions for the same incident.

```mermaid
graph TD
    A[SLO Watchdog] -->|Writes to| B[/var/log/slo_watchdog/incidents.jsonl]
    B -->|Tailed by| C[Auto-Heal Daemon]
    C -->|Evaluates Incident| D{Trigger Remediation?}
    D -->|No: Resolved or Non-Persistent SEV-2| E[Ignore]
    D -->|Yes: SEV-1 or Persistent SEV-2| F[Prepare Remediation Payload]
    F -->|Duplicate Check| G{Already Handled?}
    G -->|Yes| E
    G -->|No| H[Dispatch Remediation Request]
    H -->|API Request| I[Remediation Agent API]
    I -->|Creates| J[Autonomous Remediation Session]
    H -->|Alert| K[Telegram Bot Alert]
```

## Setup & Deployment

1. Ensure the log directory exists: `/var/log/slo_watchdog/`.
2. Install dependencies: Python 3 standard library only (`urllib.request`, `json`, `logging`).
3. Configure environment variables (e.g. `REMEDIATION_API_URL`, `REMEDIATION_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`).
4. Install and enable the systemd service: `sudo cp auto-heal.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now auto-heal`.

## Verification & Testing

Unit tests cover incident evaluation, duplicate detection, payload formatting, remediation dispatch, and Telegram alerting:
```bash
PYTHONPATH=. pytest -v
```
