#!/bin/bash
# ============================================================
# Polymarket Alpha - One-click server deployment
# Run on a fresh Ubuntu 22.04/24.04 VPS
#
# Usage:
#   ssh root@167.99.190.152
#   curl -sSL https://raw.githubusercontent.com/TerazW/polymarket-alpha/main/deploy.sh | bash
#
# Or copy this file to the server and run:
#   chmod +x deploy.sh && ./deploy.sh
# ============================================================

set -e

echo "============================================================"
echo "  Polymarket Alpha - Server Setup"
echo "============================================================"

# 1. System updates
echo "[1/7] Updating system..."
apt-get update -qq
apt-get install -y -qq git python3 python3-pip python3-venv docker.io docker-compose-plugin > /dev/null 2>&1
systemctl enable docker
systemctl start docker

# 2. Clone repo
echo "[2/7] Cloning repository..."
cd /opt
if [ -d "polymarket-alpha" ]; then
    cd polymarket-alpha
    git pull origin main
else
    git clone https://github.com/TerazW/polymarket-alpha.git
    cd polymarket-alpha
fi

# 3. Python venv
echo "[3/7] Setting up Python environment..."
python3 -m venv venv
source venv/bin/activate
pip install -q -r requirements.txt

# 4. Start TimescaleDB
echo "[4/7] Starting TimescaleDB..."
docker compose -f infra/docker-compose.yml up -d timescaledb
sleep 5  # Wait for DB to be ready

# 5. Initialize database (init.sql runs automatically via docker-entrypoint)
echo "[5/7] Running trading tables migration..."
docker exec -i belief-reaction-db psql -U postgres -d belief_reaction < infra/migrations/v6.0_trading_tables.sql 2>/dev/null || true

# 6. Screen markets
echo "[6/7] Screening markets..."
source venv/bin/activate
python -m backend.backtest.screen_markets --markets 30 --output tokens.json

# 7. Create systemd service for collector
echo "[7/7] Creating collector service..."
cat > /etc/systemd/system/polymarket-collector.service << 'SERVICEEOF'
[Unit]
Description=Polymarket Alpha - Data Collector
After=docker.service
Requires=docker.service

[Service]
Type=simple
WorkingDirectory=/opt/polymarket-alpha
ExecStart=/opt/polymarket-alpha/venv/bin/python run_collector.py --tokens tokens.json
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICEEOF

systemctl daemon-reload
systemctl enable polymarket-collector
systemctl start polymarket-collector

echo ""
echo "============================================================"
echo "  DEPLOYMENT COMPLETE"
echo "============================================================"
echo ""
echo "  Collector is running as a systemd service."
echo ""
echo "  Useful commands:"
echo "    journalctl -u polymarket-collector -f    # View live logs"
echo "    systemctl status polymarket-collector     # Check status"
echo "    systemctl restart polymarket-collector    # Restart"
echo ""
echo "  After 5-7 days, run calibration:"
echo "    cd /opt/polymarket-alpha"
echo "    source venv/bin/activate"
echo "    python -m backend.backtest.calibrate --days 7"
echo ""
echo "============================================================"
