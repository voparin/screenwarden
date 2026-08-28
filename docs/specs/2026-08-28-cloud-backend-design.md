# screenwarden Cloud Backend Design Spec

**Date:** 2026-08-28
**Scope:** Cloud backend — Phase 2 of screenwarden (cloud relay + family accounts + device registration)
**Status:** Approved

---

## Overview

The screenwarden cloud backend enables remote parental control by acting as a relay between child devices (running the screenwarden daemon) and the parent's browser or app. It is a separate service from the daemon, deployed to Fly.io, and backed by Fly Postgres.

**Architecture pattern:** Hybrid — the daemon remains authoritative for local enforcement (offline-resilient), while the cloud keeps a full mirror of usage history and config for the parent to view and modify from anywhere.

**Repository:** `github.com/voparin/screenwarden-cloud` (separate from the daemon repo)

---

## Architecture

```
[Child's Linux Machine]          [Cloud Backend (Fly.io)]          [Parent App]
screenwarden daemon          ←→   FastAPI + PostgreSQL          ←→   Web app (Phase 3)
• enforces limits locally          • family accounts + auth           • login
• SQLite (source of truth)         • device registry                  • see all devices
• syncs usage every 30s            • usage mirror (history)           • today + history
• polls for commands               • command queue                    • grant extra time
• works fully offline              • config mirror                    • change limits
                                   • QR/code registration
```

The daemon calls `POST /sync` every 30 seconds. If the cloud is unreachable, the daemon continues with its last known local config — no disruption to enforcement.

---

## Data Model (PostgreSQL)

```sql
families (
  id UUID PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,   -- bcrypt
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)

devices (
  id UUID PRIMARY KEY,
  family_id UUID REFERENCES families(id),
  name TEXT NOT NULL,            -- e.g. "Jakob's laptop"
  device_token TEXT NOT NULL UNIQUE,  -- SHA-256 random secret, shared with daemon
  last_seen_at TIMESTAMPTZ,
  registered_at TIMESTAMPTZ NOT NULL DEFAULT now()
)

child_users (
  id UUID PRIMARY KEY,
  device_id UUID REFERENCES devices(id),
  username TEXT NOT NULL,        -- Linux username on the device
  UNIQUE(device_id, username)
)

daily_usage_mirror (
  id UUID PRIMARY KEY,
  user_id UUID REFERENCES child_users(id),
  date DATE NOT NULL,
  total_seconds INTEGER NOT NULL DEFAULT 0,
  synced_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(user_id, date)
)

commands (
  id UUID PRIMARY KEY,
  user_id UUID REFERENCES child_users(id),
  type TEXT NOT NULL,            -- "grant" | "config_change"
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  picked_up_at TIMESTAMPTZ      -- null until daemon polls it
)

config_mirror (
  id UUID PRIMARY KEY,
  user_id UUID REFERENCES child_users(id) UNIQUE,
  daily_limit_minutes INTEGER NOT NULL,
  warning_minutes INTEGER NOT NULL,
  grace_minutes INTEGER NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)

pairing_codes (
  code TEXT PRIMARY KEY,         -- 6-char alphanumeric, e.g. "SW-A3F7K2"
  family_id UUID REFERENCES families(id),  -- null if daemon-initiated
  device_token_pending TEXT,     -- pre-generated, returned to daemon on claim
  initiated_by TEXT NOT NULL,    -- "parent" | "daemon"
  expires_at TIMESTAMPTZ NOT NULL,  -- 10 min TTL
  used_at TIMESTAMPTZ            -- null until claimed
)
```

---

## API Endpoints

### Daemon-facing (authenticated with `device_token` header)

**`POST /sync`**

Called every 30 seconds by each daemon.

Request:
```json
{
  "users": [
    {
      "username": "jakob",
      "date": "2026-08-28",
      "total_seconds": 3420,
      "last_sync_at": "2026-08-28T14:30:00Z"
    }
  ]
}
```

Response:
```json
{
  "commands": [
    {
      "id": "cmd-123",
      "username": "jakob",
      "type": "grant",
      "payload": {"extra_seconds": 900, "reason": "homework done"}
    }
  ],
  "config": {
    "jakob": {
      "daily_limit_minutes": 120,
      "warning_minutes": 5,
      "grace_minutes": 5
    }
  }
}
```

Rate-limited: 1 request per 20 seconds per device.

**`POST /devices/register`**

Called by daemon during `screenwarden register <code>`.

Request: `{ "pairing_code": "SW-A3F7K2", "device_name": "Jakob's laptop" }`
Response: `{ "device_token": "..." }`

### Parent-facing (JWT authenticated)

```
POST /auth/signup           — create family account (email + password)
POST /auth/login            — returns JWT (30d) + refresh token
POST /auth/refresh          — exchange refresh token for new JWT

GET  /devices               — list all registered devices for this family
POST /devices/pairing-code  — generate a 6-char pairing code (parent-initiated)
POST /devices/claim         — claim a daemon-initiated pairing code

GET  /devices/{id}          — device detail + last_seen_at
GET  /devices/{id}/users    — list child users on this device

GET  /users/{id}/today      — today's usage (total_seconds, limit, remaining)
GET  /users/{id}/history    — last 30 days of daily_usage_mirror
POST /users/{id}/grants     — grant extra time → inserts into commands table
PUT  /users/{id}/config     — change limits → inserts config_change command + updates config_mirror
```

---

## Device Registration (Pairing) Flow

Both directions work symmetrically:

**Daemon-initiated:**
1. `sudo screenwarden register` on child's machine
2. Daemon generates code request → cloud returns `SW-A3F7K2` (10 min TTL)
3. Terminal prints: `Enter code SW-A3F7K2 in the screenwarden web app`
4. Parent logs in → "Add device" → enters `SW-A3F7K2`
5. Cloud links device to family → returns `device_token` to daemon
6. Daemon saves `device_token` to `/etc/screenwarden/config.yaml`

**Parent-initiated:**
1. Parent logs in → "Add device" → cloud generates `SW-B9X2M1`
2. `sudo screenwarden register SW-B9X2M1` on child's machine
3. Cloud links device to family → returns `device_token` to daemon
4. Daemon saves `device_token` to `/etc/screenwarden/config.yaml`

Pairing codes are: 6-char alphanumeric, single-use, 10-minute TTL.

---

## Sync Protocol

The daemon's existing 30-second tick loop gains a cloud sync step:

1. Run local enforcement (unchanged)
2. Call `POST /sync` with today's usage for all users
3. Cloud upserts `daily_usage_mirror` rows
4. Cloud returns pending commands + current config
5. Daemon applies commands (same as local grants today)
6. Daemon updates local config if cloud version differs
7. If cloud unreachable: skip sync, continue with local config

Commands are marked `picked_up_at = now()` once returned. They are only returned once (not re-delivered).

---

## Security

- **Parent auth:** bcrypt password hashing, JWT (30d) + refresh tokens
- **Device auth:** `device_token` is a 32-byte random secret (hex-encoded), stored in `/etc/screenwarden/config.yaml` (chmod 600)
- **Pairing codes:** 6-char alphanumeric = ~2.2 billion combinations, single-use, 10-minute TTL
- **Rate limiting:** `/sync` limited to 1 req/20s per device; `/auth/login` limited to 5 req/min per IP
- **TLS:** Fly.io provides automatic HTTPS — all traffic encrypted
- **Token revocation:** Parent can revoke a device's token from the web app; daemon re-registers on next sync failure

---

## Hosting + Deployment

- **Platform:** Fly.io (`fly.toml` in repo root)
- **Database:** Fly Postgres (managed)
- **Migrations:** Alembic
- **CI/CD:** GitHub Actions — run tests + `fly deploy` on push to `main`
- **Environment variables (Fly secrets):** `DATABASE_URL`, `JWT_SECRET`, `ENVIRONMENT`

---

## Project Structure

```
screenwarden-cloud/
  src/
    api/
      routes/
        auth.py           # POST /auth/signup, /login, /refresh
        devices.py        # device list, pairing, claim
        users.py          # today, history, grants, config
        sync.py           # POST /sync (daemon endpoint)
      app.py              # FastAPI app factory
      auth.py             # JWT + device_token middleware
    db/
      models.py           # SQLAlchemy models
      session.py          # DB session dependency
      migrations/         # Alembic migration files
  tests/
    test_sync.py
    test_auth.py
    test_devices.py
    test_users.py
  fly.toml
  Dockerfile
  pyproject.toml
  alembic.ini
```

---

## Out of Scope (Future Phases)

- Parent web app UI (Phase 3)
- Native mobile app
- Push notifications (FCM/APNs)
- Google Family Link integration
- Usage analytics / reporting
- Multiple admin parents per family
