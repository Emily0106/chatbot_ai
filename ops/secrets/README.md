# Ops Secrets Management

## 1. Directory Structure
This directory (`ops/secrets/`) is **.gitignored**.
Do NOT commit any files inside it (except `.gitkeep` or templates if provided).

## 2. Required Secrets
For the stack to run, you must generate the following files:

### A. Basic Auth for Nginx (`htpasswd`)
Used to protect `/metrics`, `/prometheus`, `/grafana`.
```bash
# Install htpasswd util (apache2-utils)
# Create file with user 'admin'
htpasswd -bc ops/secrets/htpasswd admin strongpassword
```

### B. Grafana Admin Password (`grafana_admin_password`)
Used to set the initial `admin` password for Grafana.
```bash
echo "strongpassword" > ops/secrets/grafana_admin_password
```

### C. TLS Certificates (`tls/`)
Used for HTTPS termination at Nginx Edge (Port 8443).

**For Staging/Local (Self-Signed):**
```bash
mkdir -p ops/secrets/tls
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout ops/secrets/tls/privkey.pem \
  -out ops/secrets/tls/fullchain.pem \
  -subj "/CN=localhost"
```

**For Production:**
Use Let's Encrypt or mount valid certificates.
Mount paths in `docker-compose.observability.yml` expect:
- `ops/secrets/tls/fullchain.pem`
- `ops/secrets/tls/privkey.pem`
