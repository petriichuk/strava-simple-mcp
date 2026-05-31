# Deploy on EC2 (Ubuntu)

Prereqs: a domain pointed at the instance's public IP, security group open on 443
(and 80 for the cert challenge).

```bash
sudo apt update && sudo apt install -y python3-venv nginx certbot python3-certbot-nginx
sudo mkdir -p /opt/strava-coach-mcp && sudo chown $USER /opt/strava-coach-mcp

# Copy src/* + requirements.txt + .env into /opt/strava-coach-mcp.
# NOTE: server.py imports cache/strava/metrics by top-level name, so put the
# files from src/ at the working-directory ROOT (or set PYTHONPATH=src).
cd /opt/strava-coach-mcp
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

Then add in claude.ai: Settings -> Connectors -> Add custom connector ->

```
https://yourdomain/<MCP_PATH_SECRET>/mcp
```

See SPEC.md for the transport/auth steps Claude Code should finalise against
current MCP SDK + Anthropic connector docs before going live.
