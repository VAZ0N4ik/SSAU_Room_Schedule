#!/bin/bash

# SSAU Schedule Updater Service Installation Script

set -e

# Configuration
SERVICE_NAME="ssau-schedule-updater"
SERVICE_USER="ssau-schedule"
INSTALL_DIR="/opt/ssau-schedule"
REPO_URL="https://github.com/your-username/SSAU_Room_Schedule.git"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   log_error "This script must be run as root (use sudo)"
   exit 1
fi

log_info "Starting SSAU Schedule Updater Service installation..."

# Install dependencies
log_info "Installing system dependencies..."
apt-get update
apt-get install -y python3 python3-pip python3-venv git curl

# Create service user
log_info "Creating service user..."
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd --system --shell /bin/false --home-dir "$INSTALL_DIR" --create-home "$SERVICE_USER"
    log_info "Created user: $SERVICE_USER"
else
    log_warn "User $SERVICE_USER already exists"
fi

# Create installation directory
log_info "Setting up installation directory..."
mkdir -p "$INSTALL_DIR"
chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

# Clone or update repository
if [ -d "$INSTALL_DIR/.git" ]; then
    log_info "Updating existing repository..."
    cd "$INSTALL_DIR"
    sudo -u "$SERVICE_USER" git pull
else
    log_info "Cloning repository..."
    sudo -u "$SERVICE_USER" git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# Create Python virtual environment
log_info "Setting up Python virtual environment..."
sudo -u "$SERVICE_USER" python3 -m venv .venv
sudo -u "$SERVICE_USER" .venv/bin/pip install --upgrade pip

# Install Python dependencies
log_info "Installing Python dependencies..."
sudo -u "$SERVICE_USER" .venv/bin/pip install -r requirements.txt

# Create .env file if it doesn't exist
if [ ! -f "$INSTALL_DIR/.env" ]; then
    log_info "Creating environment file..."
    sudo -u "$SERVICE_USER" cp .env.example .env
    log_warn "Please edit $INSTALL_DIR/.env with your configuration"
fi

# Set permissions for environment file
chmod 600 "$INSTALL_DIR/.env"
chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/.env"

# Create log directory
log_info "Setting up logging..."
mkdir -p /var/log
touch /var/log/ssau-schedule-updater.log
chown "$SERVICE_USER:$SERVICE_USER" /var/log/ssau-schedule-updater.log

# Install systemd service files
log_info "Installing systemd service files..."
cp "$INSTALL_DIR/${SERVICE_NAME}.service" "/etc/systemd/system/"
cp "$INSTALL_DIR/${SERVICE_NAME}.timer" "/etc/systemd/system/"

# Reload systemd
log_info "Reloading systemd..."
systemctl daemon-reload

# Enable and start timer
log_info "Enabling service timer..."
systemctl enable "${SERVICE_NAME}.timer"
systemctl start "${SERVICE_NAME}.timer"

# Test the service
log_info "Testing service installation..."
if sudo -u "$SERVICE_USER" "$INSTALL_DIR/.venv/bin/python" "$INSTALL_DIR/schedule_updater.py" --health-check; then
    log_info "Service test passed!"
else
    log_warn "Service test failed - please check configuration"
fi

# Show status
log_info "Service status:"
systemctl status "${SERVICE_NAME}.timer" --no-pager

log_info "Installation completed!"
echo
log_info "Next steps:"
echo "1. Edit $INSTALL_DIR/.env with your SSAU credentials"
echo "2. Test the service: sudo systemctl start ${SERVICE_NAME}.service"
echo "3. Check logs: journalctl -u ${SERVICE_NAME}.service"
echo "4. Check timer status: systemctl status ${SERVICE_NAME}.timer"
echo
log_info "The service will run daily at 2:00 AM"

# Show useful commands
echo
log_info "Useful commands:"
echo "- Start service now: sudo systemctl start ${SERVICE_NAME}.service"
echo "- Check service logs: sudo journalctl -u ${SERVICE_NAME}.service -f"
echo "- Check timer status: sudo systemctl list-timers ${SERVICE_NAME}.timer"
echo "- Disable timer: sudo systemctl disable ${SERVICE_NAME}.timer"
echo "- Manual update: sudo -u $SERVICE_USER $INSTALL_DIR/.venv/bin/python $INSTALL_DIR/schedule_updater.py --once"