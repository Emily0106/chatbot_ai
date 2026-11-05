# Gov-AI Operations

## Observability Stack (Secure Edge + TLS + Secrets)

### 1. Components
*   **Nginx Edge**: Reverse Proxy with TLS (Port 8443) & Basic Auth.
*   **Prometheus, Grafana, Alertmanager**: Backend services (Internal).

### 2. Setup (First Run)
Secrets are NOT committed. You must generate them first:

```bash
# 1. Generate Secrets (htpasswd, certs, grafana pw)
# See ops/secrets/README.md for details
cd ops/secrets && ./generate_dummy.sh # (If script provided, or run commands manually)

# 2. Start Stack
cd ops
docker compose -f docker-compose.observability.yml up -d
```

### 3. Access (Single Entrypoint: 8443)
*   **Redirect**: http://localhost:8080 -> https://localhost:8443 (Self-Signed in Staging).
*   **Grafana**: https://localhost:8443/grafana/
*   **Prometheus**: https://localhost:8443/prometheus/
*   **Alertmanager**: https://localhost:8443/alertmanager/

### 4. Verification
*   **HTTPS Check**:
    ```bash
    curl -Ik https://localhost:8443/metrics
    # Expect: 401 Unauthorized
    ```
*   **Auth Check**:
    ```bash
    curl -Ik -u admin:admin https://localhost:8443/metrics
    # Expect: 200 OK
    ```

## Security Layout
*   **Ports**: Only 8080 (Redirect) and 8443 (TLS) exposed.
*   **Secrets**: Mounted from `ops/secrets/` into containers.
*   **Grafana Admin**: Password set via `ops/secrets/grafana_admin_password`.
