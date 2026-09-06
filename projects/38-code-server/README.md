# Nomad Web IDE / Code-Server Runbook

This runbook covers the setup, access, and operation of the Nomad Web IDE running via code-server.

## Quick Start

Start the service using Docker Compose:
```bash
docker-compose up -d
```
The service will be available on port 8443. The workspace, git configs, and extensions are persisted in local directories.

## Tailscale Access Configuration

To access the IDE securely over Tailscale:
1. Ensure Tailscale is installed on the host running the docker containers.
2. Bind the code-server to the Tailscale IP or use a reverse proxy (like Caddy/Nginx) bound to the Tailnet interface to forward traffic to port 8443.
3. Access via `http://<tailscale-machine-name>:8443` or your configured domain.

## iPad/Tablet Browser Optimizations

For the best experience on iPads or tablets:
- "Add to Home Screen": Open the Web IDE in Safari and select "Add to Home Screen" to run it in a full-screen standalone mode.
- Use an external keyboard (like the Magic Keyboard).
- Touch interactions are supported natively by code-server.

## Keybindings

Code-server supports standard VS Code keybindings.
- *Ctrl+P* (or Cmd+P on iPad with Magic Keyboard) for Quick Open.
- *Ctrl+Shift+P* (or Cmd+Shift+P) for the Command Palette.
- Custom keybindings can be synced via the Settings Sync extension or stored in the `./workspace` directory.

## Disaster Recovery

In case of container failure or host migration:
1. **State:** All important state is stored in the `./workspace`, `./git-configs`, and `./extensions` folders.
2. **Backup:** Regularly backup these directories.
3. **Restore:** Copy the backup directories to a new host and re-run `docker-compose up -d`.
4. **Bootstrap Script:** If starting fresh, run `python3 init_workspace.py` to quickly scaffold your Python venvs and pull down necessary repositories.
