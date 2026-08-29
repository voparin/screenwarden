# screenwarden Daemon Cloud Sync Design Spec

**Date:** 2026-08-29
**Scope:** Phase 2b — wire the screenwarden daemon to sync with the cloud backend
**Status:** Approved

---

## Overview

Add cloud synchronisation to the screenwarden daemon so that:
- Usage data is mirrored to the cloud every 30 seconds
- Commands (grants, config changes) issued via the parent web app are picked up by the daemon
- Device registration (`screenwarden register`) links the daemon to a family account

The daemon remains fully offline-resilient: if the cloud is unreachable, enforcement continues unchanged using local config and local DB.

---

## Changes Required

### 1. Config — new `cloud` section

`/etc/screenwarden/config.yaml` gains an optional `cloud` section:

```yaml
cloud:
  api_url: https://screenwarden-cloud.onrender.com
  device_token: ""   # set by 'screenwarden register'
```

`src/screenwarden/daemon/config.py` — add `CloudConfig` dataclass:

```python
@dataclass
class CloudConfig:
    api_url: str = "https://screenwarden-cloud.onrender.com"
    device_token: str = ""
```

`Config.load()` parses the `cloud:` section and populates `config.cloud`. If the section is absent, defaults are used. If `device_token` is empty, cloud sync is skipped silently.

`cli/main.py` — `DEFAULT_CONFIG` template gains the `cloud:` section with empty `device_token`.

---

### 2. New module: `src/screenwarden/daemon/cloud_sync.py`

```python
@dataclass
class SyncResult:
    commands: list[dict]        # pending commands from cloud
    config: dict[str, dict]    # {username: {daily_limit_minutes, warning_minutes, grace_minutes}}

class CloudSync:
    def __init__(self, api_url: str, device_token: str): ...
    def sync(self, users: dict[str, int], today: date) -> SyncResult: ...
    def request_pairing_code(self) -> str: ...  # for daemon-initiated registration
    def register(self, pairing_code: str, device_name: str) -> str: ...  # returns device_token
```

**`sync()` behaviour:**
- Calls `POST {api_url}/sync` with `X-Device-Token: {device_token}` header
- Request body:
  ```json
  {"users": [{"username": "jakob", "date": "2026-08-29", "total_seconds": 3420, "last_sync_at": "..."}]}
  ```
- On success: returns `SyncResult` with commands and config from response
- On any failure (network error, timeout, non-200 response): logs a warning, returns `SyncResult(commands=[], config={})`
- Uses `urllib.request` (stdlib only, no new dependencies)
- 5-second timeout

**`request_pairing_code()` behaviour:**
- Calls `POST {api_url}/devices/pairing-code` with no auth (daemon-initiated flow needs a temporary endpoint — see note below)
- Returns the 6-char code to print to the terminal

**Note on daemon-initiated pairing:** The cloud backend currently requires parent JWT auth to create a pairing code. For daemon-initiated flow, a new unauthenticated endpoint `POST /devices/pairing-code/daemon` will be needed on the cloud. This is out of scope for this phase — for now, `screenwarden register` only supports the parent-initiated flow (parent creates code first, daemon registers with it).

**`register()` behaviour:**
- Calls `POST {api_url}/devices/register` with `{"pairing_code": code, "device_name": hostname}`
- Returns `device_token` on success
- Raises `RuntimeError` with a clear message on failure (404 = code not found/expired, other = network error)

---

### 3. Daemon main loop changes (`src/screenwarden/daemon/main.py`)

**Initialisation** — create `CloudSync` if `device_token` is set:

```python
cloud = CloudSync(config.cloud.api_url, config.cloud.device_token) if config.cloud.device_token else None
```

**Each tick** — after local enforcement, add cloud sync step:

```python
if cloud:
    try:
        result = cloud.sync(
            users={u: db.get_usage_today(u, today) for u in trackers},
            today=today,
        )
        for cmd in result.commands:
            if cmd["type"] == "grant":
                db.add_time_grant(
                    cmd["username"], datetime.now(),
                    cmd["payload"]["extra_seconds"], None,
                )
            elif cmd["type"] == "config_change":
                payload = cmd["payload"]
                if cmd["username"] in config.users:
                    config.users[cmd["username"]] = UserConfig(
                        daily_limit_minutes=payload["daily_limit_minutes"],
                        warning_minutes=payload["warning_minutes"],
                        grace_minutes=payload["grace_minutes"],
                    )
                    trackers[cmd["username"]]._config = config.users[cmd["username"]]
        for username, cfg in result.config.items():
            if username in config.users:
                new_cfg = UserConfig(**cfg)
                if new_cfg != config.users[username]:
                    config.users[username] = new_cfg
                    trackers[username]._config = new_cfg
    except Exception:
        logger.exception("Unexpected error in cloud sync — continuing with local config")
```

Cloud sync errors never propagate to the main loop — the `except Exception` guard ensures local enforcement is never disrupted.

---

### 4. CLI — new `register` command (`src/screenwarden/cli/main.py`)

```bash
sudo screenwarden register <CODE>
```

- Requires root (same as `install`)
- Reads `api_url` from existing config
- Calls `CloudSync.register(code, hostname)` 
- On success: writes `device_token` to `/etc/screenwarden/config.yaml` under `cloud.device_token`
- On failure: prints error message and exits non-zero
- Restarts the daemon: `systemctl restart screenwarden`

Usage shown in `--help` and printed after `screenwarden install`.

---

### 5. Testing

**`tests/daemon/test_cloud_sync.py`:**
- `test_sync_sends_correct_payload` — mock urllib, verify request body shape
- `test_sync_returns_commands` — mock response with commands, verify SyncResult
- `test_sync_returns_empty_on_network_error` — mock urllib to raise `URLError`, verify empty SyncResult returned (no exception)
- `test_sync_returns_empty_on_non_200` — mock 401 response, verify empty SyncResult
- `test_register_returns_device_token` — mock response, verify token returned
- `test_register_raises_on_404` — mock 404, verify RuntimeError raised

---

## Files Changed

| File | Change |
|------|--------|
| `src/screenwarden/daemon/config.py` | Add `CloudConfig` dataclass, parse `cloud:` section |
| `src/screenwarden/daemon/cloud_sync.py` | New file — `CloudSync` class + `SyncResult` |
| `src/screenwarden/daemon/main.py` | Init `CloudSync`, add sync step to tick loop |
| `src/screenwarden/cli/main.py` | Add `register` subcommand, update `DEFAULT_CONFIG` |
| `tests/daemon/test_cloud_sync.py` | New file — 6 unit tests |

---

## Out of Scope

- Daemon-initiated pairing code (requires cloud backend change — future)
- Config file write-back when cloud config changes (config is updated in-memory only; file is not rewritten)
- Retry logic for failed syncs (fail-silently is sufficient for phase 2b)
