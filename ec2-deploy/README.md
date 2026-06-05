# Deploy on EC2 (Ubuntu)

Prereqs: a domain pointed at the instance's public IP, security group open on 443
(and 80 for the cert challenge).

```bash
sudo apt update && sudo apt install -y python3-venv nginx certbot python3-certbot-nginx
sudo mkdir -p /opt/strava-simple-mcp && sudo chown $USER /opt/strava-simple-mcp

# Copy src/* + requirements.txt + .env into /opt/strava-simple-mcp.
# NOTE: server.py imports cache/strava/metrics by top-level name, so put the
# files from src/ at the working-directory ROOT (or set PYTHONPATH=src).
cd /opt/strava-simple-mcp
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # then edit .env with your real values

# TLS + reverse proxy (edit server_name in nginx.conf first)
sudo cp ec2-deploy/nginx.conf /etc/nginx/sites-available/strava-mcp
sudo ln -s /etc/nginx/sites-available/strava-mcp /etc/nginx/sites-enabled/
sudo certbot --nginx -d yourdomain
sudo nginx -t && sudo systemctl reload nginx

# Run as a service
sudo cp ec2-deploy/strava-mcp.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now strava-mcp
```

Set `MCP_ALLOWED_HOSTS=yourdomain` in `.env` so the MCP SDK's
DNS-rebinding protection accepts requests forwarded by nginx.

Then add in claude.ai: Settings → Connectors → Add custom connector →

```
https://yourdomain/<MCP_PATH_SECRET>/mcp
```

See the project [README](../README.md) for the full configuration table,
auth model, and known gotchas. Path-secret is the v1 auth gate; OAuth 2.1 +
PKCE is the planned follow-up.
