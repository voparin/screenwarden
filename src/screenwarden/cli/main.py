import argparse
import getpass
import hashlib
import os
import subprocess
import sys
from pathlib import Path

CONFIG_DIR = Path("/etc/screenwarden")
CONFIG_FILE = CONFIG_DIR / "config.yaml"
DATA_DIR = Path("/var/lib/screenwarden")
SERVICE_FILE = Path("/etc/systemd/system/screenwarden.service")


SYSTEMD_UNIT = """\
[Unit]
Description=screenwarden parental control daemon
After=network.target

[Service]
Type=simple
ExecStart={exec_path}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""

DEFAULT_CONFIG = """\
# screenwarden configuration
# Edit directly or via the web dashboard at http://localhost:8080
dashboard:
  port: 8080
  password_hash: "{password_hash}"

users:
  {username}:
    daily_limit_minutes: 120
    warning_minutes: 5
    grace_minutes: 5
"""


def cmd_install(args):
    if os.geteuid() != 0:
        print("Error: 'screenwarden install' must be run as root (use sudo)", file=sys.stderr)
        sys.exit(1)

    print("screenwarden install")
    print("====================")

    username = input("Child's Linux username: ").strip()
    password = getpass.getpass("Dashboard password: ")
    password_hash = hashlib.sha256(password.encode()).hexdigest()

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    CONFIG_FILE.write_text(DEFAULT_CONFIG.format(
        username=username,
        password_hash=password_hash,
    ))
    print(f"Config written to {CONFIG_FILE}")

    exec_path = subprocess.run(
        ["which", "screenwarden-daemon"], capture_output=True, text=True
    ).stdout.strip()
    SERVICE_FILE.write_text(SYSTEMD_UNIT.format(exec_path=exec_path))
    subprocess.run(["systemctl", "daemon-reload"])
    subprocess.run(["systemctl", "enable", "--now", "screenwarden"])
    print("Service enabled and started.")
    print(f"\nDashboard available at http://localhost:8080")


def cmd_status(args):
    subprocess.run(["systemctl", "status", "screenwarden"])


def main():
    parser = argparse.ArgumentParser(prog="screenwarden")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("install", help="Install and configure screenwarden")
    sub.add_parser("status", help="Show service status")

    args = parser.parse_args()

    if args.command == "install":
        cmd_install(args)
    elif args.command == "status":
        cmd_status(args)
    else:
        parser.print_help()
