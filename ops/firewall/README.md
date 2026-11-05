# Server Hardening (Firewall)

## 1. UFW Rules (Ubuntu/Debian)
Only allow exposing the Nginx Edge port (8080/443).
Everything else should be internal-only (Docker network).

```bash
# Default Policies
ufw default deny incoming
ufw default allow outgoing

# SSH (Limit to JumpHost or VPN)
ufw allow from <VPN_CIDR> to any port 22

# Nginx Edge (Open to Public/VPC)
ufw allow 8080/tcp  # Or 443

# Deny Direct Access (Redundant if default deny, but good for clarity)
ufw deny 3000   # Grafana
ufw deny 9090   # Prometheus
ufw deny 9093   # Alertmanager
ufw deny 8000   # Backend (Metrics)

ufw enable
```

## 2. Docker Daemon Security
*   Bind Docker API to unix socket only (default).
*   Avoid exposing ports with `-p 0.0.0.0:port` unless intended. Bind to localhost `-p 127.0.0.1:port` if tunneling.

## 3. Network Segmentation (VPN)
For Production Gov-AI:
*   **Public Zone**: None (if internal tool) or LoadBalancer only.
*   **DMZ**: Nginx Edge.
*   **Internal**: Backend, Databases, VectorDB.
*   **Management**: Monitoring Stack (Prometheus/Grafana) - Access via VPN only.
