# Project 74: Tailscale ACL & Subnet Route Watchdog

## Ecosystem Purpose
Audits Tailscale tailnet state, advertised subnet routes (192.168.1.0/24), and node key expiration to ensure continuous mesh access and prevent unauthorized route injection.

## Architecture Guide

### Tailnet Mesh Topology

```mermaid
graph TD
    subgraph Tailnet
    A[NAS (192.168.1.80)] -- Tailnet --> B[Tailscale Watchdog]
    C[Pi (192.168.1.92)] -- Tailnet --> B
    D[Rogue Node] -- Tailnet --> B
    end
    
    subgraph Subnets
    A -- Subnet Route --> Z(192.168.1.0/24)
    C -- Subnet Route --> Z
    end

    B -- Audit --> E[Alert Router]
```

### Route Authorization Policy
Only authorized gateways (NAS or Pi) are permitted to advertise routes for the `192.168.1.0/24` subnet. If any other node is found advertising this subnet, the Watchdog triggers a security alert.

### Key Rotation Runbook
1. Ensure the Tailscale node auth key is properly rotated before expiry (<14 days warning).
2. The Watchdog monitors `KeyExpiry` in Tailscale node states.
3. Upon alert generation, an administrator must log into the Tailscale admin console, generate a new auth key, and rotate it on the affected node:
   ```bash
   sudo tailscale up --authkey <NEW_AUTH_KEY>
   ```
