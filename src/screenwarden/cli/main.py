import argparse
import getpass
import hashlib
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import yaml

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

cloud:
  api_url: https://screenwarden-cloud.onrender.com
  device_token: ""

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
    CONFIG_FILE.chmod(0o600)
    print(f"Config written to {CONFIG_FILE}")

    exec_path = shutil.which("screenwarden-daemon") or "/usr/bin/screenwarden-daemon"
    SERVICE_FILE.write_text(SYSTEMD_UNIT.format(exec_path=exec_path))
    subprocess.run(["systemctl", "daemon-reload"])
    subprocess.run(["systemctl", "enable", "--now", "screenwarden"])
    print("Service enabled and started.")
    print(f"\nDashboard available at http://localhost:8080")
    print(f"\nTo connect to the screenwarden cloud app, run:")
    print(f"  sudo screenwarden register <CODE>")
    print(f"(Get the code from https://screenwarden-cloud.onrender.com)")


def cmd_status(args):
    subprocess.run(["systemctl", "status", "screenwarden"])


def cmd_register(args):
    if os.geteuid() != 0:
        print("Error: 'screenwarden register' must be run as root (use sudo)", file=sys.stderr)
        sys.exit(1)

    if not CONFIG_FILE.exists():
        print(f"Error: config not found at {CONFIG_FILE}. Run 'sudo screenwarden install' first.",
              file=sys.stderr)
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        raw = yaml.safe_load(f)

    api_url = raw.get("cloud", {}).get("api_url", "https://screenwarden-cloud.onrender.com")
    device_name = socket.gethostname()

    from screenwarden.daemon.cloud_sync import CloudSync
    cloud = CloudSync(api_url, "")

    print(f"Registering device '{device_name}' with {api_url} ...")
    try:
        device_token = cloud.register(args.code, device_name)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Write device_token back to config
    if "cloud" not in raw:
        raw["cloud"] = {}
    raw["cloud"]["api_url"] = api_url
    raw["cloud"]["device_token"] = device_token

    with open(CONFIG_FILE, "w") as f:
        yaml.dump(raw, f, default_flow_style=False)
    CONFIG_FILE.chmod(0o600)

    print(f"Device registered successfully.")
    print(f"Restarting screenwarden daemon...")
    subprocess.run(["systemctl", "restart", "screenwarden"])
    print(f"Done. Cloud sync is now active.")


def main():
    parser = argparse.ArgumentParser(prog="screenwarden")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("install", help="Install and configure screenwarden")
    sub.add_parser("status", help="Show service status")

    register_parser = sub.add_parser("register", help="Register this device with the cloud app")
    register_parser.add_argument("code", help="Pairing code from the screenwarden web app (e.g. SW-ABC123)")

    args = parser.parse_args()

    if args.command == "install":
        cmd_install(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "register":
        cmd_register(args)
    else:
        parser.print_help()
