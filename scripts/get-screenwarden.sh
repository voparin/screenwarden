#!/usr/bin/env bash
# screenwarden install/update/uninstall script
# Usage:
#   Install/update: curl -fsSL https://raw.githubusercontent.com/voparin/screenwarden/main/scripts/get-screenwarden.sh | sudo bash
#   Uninstall:      curl -fsSL https://raw.githubusercontent.com/voparin/screenwarden/main/scripts/get-screenwarden.sh | sudo bash -s -- --uninstall

set -euo pipefail

UNINSTALL=0
for arg in "${@:-}"; do
  [[ "$arg" == "--uninstall" ]] && UNINSTALL=1
done

log() { echo "[screenwarden] $*"; }
err() { echo "[screenwarden] ERROR: $*" >&2; exit 1; }

# Must run as root
[[ "$(id -u)" -eq 0 ]] || err "This script must be run as root. Use: sudo bash"

if [[ "$UNINSTALL" -eq 1 ]]; then
  log "Uninstalling screenwarden..."

  if systemctl is-active --quiet screenwarden 2>/dev/null; then
    log "Stopping service..."
    systemctl stop screenwarden
  fi

  if systemctl is-enabled --quiet screenwarden 2>/dev/null; then
    log "Disabling service..."
    systemctl disable screenwarden
  fi

  if command -v screenwarden &>/dev/null; then
    log "Removing Python package..."
    pip uninstall -y screenwarden
  fi

  [[ -d /etc/screenwarden ]] && { log "Removing config..."; rm -rf /etc/screenwarden; }
  [[ -d /var/lib/screenwarden ]] && { log "Removing database..."; rm -rf /var/lib/screenwarden; }
  [[ -f /etc/systemd/system/screenwarden.service ]] && {
    log "Removing systemd unit..."
    rm -f /etc/systemd/system/screenwarden.service
    systemctl daemon-reload
  }

  log "screenwarden has been uninstalled."
  exit 0
fi

# Check Python 3.11+
if ! command -v python3 &>/dev/null; then
  err "Python 3 is not installed. Install it first: sudo apt install python3 (Debian/Ubuntu) or sudo dnf install python3 (Fedora)"
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [[ "$PYTHON_MAJOR" -lt 3 ]] || { [[ "$PYTHON_MAJOR" -eq 3 ]] && [[ "$PYTHON_MINOR" -lt 11 ]]; }; then
  err "Python 3.11+ is required (found $PYTHON_VERSION). Upgrade Python first."
fi

log "Python $PYTHON_VERSION found."

if command -v screenwarden &>/dev/null; then
  # Update mode
  CURRENT=$(screenwarden --version 2>/dev/null || echo "unknown")
  log "screenwarden already installed ($CURRENT). Upgrading..."
  pip install --upgrade screenwarden
  NEW=$(screenwarden --version 2>/dev/null || echo "unknown")
  log "Upgraded to $NEW."
  log "Restarting service..."
  systemctl restart screenwarden
  log "Done. screenwarden is running."
else
  # Fresh install
  log "Installing screenwarden..."
  pip install screenwarden
  log "Running setup..."
  screenwarden install
fi
