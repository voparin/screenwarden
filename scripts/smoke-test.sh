#!/usr/bin/env bash
# Smoke test: set a 1-minute limit and verify warning + lock fire.
# Must be run as root on a machine with a real child user session.
# Usage: sudo bash scripts/smoke-test.sh <child_username>

set -euo pipefail

USERNAME="${1:-}"
if [[ -z "$USERNAME" ]]; then
  echo "Usage: sudo $0 <child_username>" >&2
  exit 1
fi

CONFIG="/etc/screenwarden/config.yaml"
BACKUP="/etc/screenwarden/config.yaml.bak"

echo "[smoke] Backing up config to $BACKUP"
cp "$CONFIG" "$BACKUP"

echo "[smoke] Setting 1-minute limit with 0-minute warning and 1-minute grace"
cat > "$CONFIG" <<EOF
users:
  $USERNAME:
    daily_limit_minutes: 1
    warning_minutes: 0
    grace_minutes: 1
EOF

echo "[smoke] Restarting daemon"
systemctl restart screenwarden

echo "[smoke] Waiting 90 seconds for warning + lock to fire..."
sleep 90

echo "[smoke] Checking systemd journal for enforcement events"
journalctl -u screenwarden --since "2 minutes ago" --no-pager | grep -E "WARNING|GRACE|LOCKED|lock-session" && \
  echo "[smoke] PASS: enforcement events found" || \
  echo "[smoke] FAIL: no enforcement events found"

echo "[smoke] Restoring config"
cp "$BACKUP" "$CONFIG"
systemctl restart screenwarden
echo "[smoke] Done."
