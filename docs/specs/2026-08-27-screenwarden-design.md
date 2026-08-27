# screenwarden — Phase 1 Design Spec

**Date:** 2026-08-27  
**Scope:** Daily screen time limit (Phase 1 of 4)  
**Status:** Approved

---

## Overview

`screenwarden` is a Linux parental control daemon that enforces daily screen time limits for a child's Linux user account. It is distributed as a PyPI package and as `.deb`/`.rpm` system packages. The parent manages settings and grants extra time via a local web dashboard accessible from any device on the home network.

**Target setup:** Child on a Linux machine with their own user account; parent managing from a phone or separate computer on the same network.

**Target user (child):** Preteen (10–13). Moderate controls, child can see their own status.

---

## Architecture

Three components, all bundled in the `screenwarden` Python package:

### 1. Daemon (`screenwarden-daemon`)
- Runs as a **systemd service** (`screenwarden.service`) with root privileges
- Tracks active session time for the child's Linux user via `loginctl`
- Enforces daily limit: warning → grace period → lock
- Embeds the FastAPI web server (parent dashboard)
- Watches config file for changes via inotify (no restart needed)
- Logs to systemd journal (`journalctl -u screenwarden`)

### 2. Parent Web Dashboard
- Served by FastAPI on `http://<child-machine-ip>:8080`
- Password-protected (set during `sudo screenwarden install`)
- Server-rendered HTML with Jinja2 templates, minimal JavaScript, no frontend framework
- Works from any browser including mobile

### 3. Child Notifier (`screenwarden-notify`)
- GTK overlay window + `notify-send` desktop notifications
- Runs in the child's user session (launched by the daemon via `su - <child_user> -c "screenwarden-notify"`)
- Cannot be dismissed by the child without root
- Shows countdown during grace period

---

## Project Structure

```
screenwarden/
├── src/screenwarden/
│   ├── daemon/          # session tracking, enforcement logic
│   ├── api/             # FastAPI web server + REST endpoints
│   ├── notifier/        # GTK warning window + notify-send
│   └── cli/             # `screenwarden` CLI for setup/admin
├── web/                 # Parent dashboard (HTML/JS/CSS, static files)
├── packaging/
│   ├── debian/          # .deb package files
│   ├── rpm/             # .rpm spec file
│   └── systemd/         # screenwarden.service unit file
├── tests/
├── pyproject.toml       # PyPI packaging (PEP 517)
└── README.md
```

---

## Distribution

- **PyPI:** `pip install screenwarden` — works on any distro with Python 3
- **Debian/Ubuntu:** `.deb` package via `packaging/debian/`
- **Fedora/RHEL:** `.rpm` package via `packaging/rpm/`

Setup flow after `pip install`:
```bash
sudo screenwarden install   # creates config, enables systemd service
```

---

## Data Model

**SQLite database:** `/var/lib/screenwarden/usage.db`

```sql
sessions (
  id INTEGER PRIMARY KEY,
  user TEXT NOT NULL,
  started_at DATETIME NOT NULL,
  ended_at DATETIME,
  duration_seconds INTEGER
)

daily_usage (
  id INTEGER PRIMARY KEY,
  user TEXT NOT NULL,
  date DATE NOT NULL,
  total_seconds INTEGER NOT NULL,
  UNIQUE(user, date)
)

time_grants (
  id INTEGER PRIMARY KEY,
  user TEXT NOT NULL,
  granted_at DATETIME NOT NULL,
  extra_seconds INTEGER NOT NULL,
  reason TEXT
)
```

**Config file:** `/etc/screenwarden/config.yaml`

```yaml
users:
  jakob:                      # child's Linux username
    daily_limit_minutes: 120
    warning_minutes: 5        # warn child before lockout
    grace_minutes: 5          # time between warning and lock
```

Config changes are picked up live via inotify — no daemon restart required.

---

## Enforcement Flow

The daemon runs a check loop every 30 seconds:

1. **Is child's user session active?** (via `loginctl`)
   - No → pause tracking, do nothing
   - Yes → add elapsed time to `daily_usage`

2. **Check daily limit:**
   - Below `(limit - warning_minutes)` → continue normally
   - At warning threshold → send `notify-send` desktop notification + show GTK overlay with countdown
   - At limit → start grace period (fullscreen GTK overlay, child cannot dismiss)
   - Grace expired → `loginctl lock-session` (falls back to `vlock` if no display manager)

3. **Check for time grants:**
   - New row in `time_grants` → extend today's effective limit
   - Dismiss overlay if currently shown

---

## Parent Dashboard — Pages

| Page | Content |
|------|---------|
| **Today** | Usage so far, limit, time remaining, "Grant extra time" button |
| **History** | Daily usage chart, last 30 days |
| **Settings** | Daily limit, warning/grace period, child's username |

"Grant extra time" posts to the REST API; the daemon picks it up within 30 seconds (next check loop tick).

---

## Error Handling

- All unhandled daemon exceptions log to systemd journal
- Dashboard shows an alert banner if the daemon reports an error
- **Fail-safe:** if the DB is missing or corrupted, the daemon locks the child's session rather than allowing unlimited access

---

## Testing

| Layer | Approach |
|-------|----------|
| Unit | Daemon logic (time accumulation, limit calculation, grant application) with mocked `loginctl` and `sqlite3` |
| Integration | FastAPI endpoints via `httpx` + real in-memory SQLite DB |
| Smoke | `scripts/smoke-test.sh` — sets 1-minute limit, verifies warning and lock fire on a real session |

---

## Future Phases (out of scope for Phase 1)

- **Phase 2:** Schedule/bedtime blocks (no computer 9pm–7am)
- **Phase 3:** Per-app time limits (e.g., YouTube max 30 min/day)
- **Phase 4:** Homework mode (block everything except allowed apps)
- **Later:** Native mobile app (Android/iOS) as parent dashboard
- **Later:** Google Family Link integration
