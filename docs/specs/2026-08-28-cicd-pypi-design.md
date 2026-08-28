# screenwarden — CI/CD + PyPI Publishing Design Spec

**Date:** 2026-08-28  
**Scope:** GitHub Actions CI/CD pipeline, PyPI publishing, curl install script, pyproject.toml metadata
**Status:** Approved

---

## Overview

Set up automated testing, building, and publishing for screenwarden so that:
- Every push to `main` runs tests and validates the package builds
- Pushing a git tag `v*` triggers a full release to PyPI
- Any user on Linux can install, update, or uninstall via a single `curl | bash` command

---

## Versioning Strategy

Manual bump before each release:

```bash
# 1. Edit pyproject.toml: version = "0.2.0"
git add pyproject.toml
git commit -m "chore: bump version to 0.2.0"
git tag v0.2.0
git push && git push --tags
```

The git tag triggers the release workflow. No version tooling needed.

---

## GitHub Actions Workflows

### CI Workflow (`.github/workflows/ci.yml`)

**Trigger:** push or PR to `main`

**Steps:**
1. Checkout code
2. Set up Python 3.11
3. Install dev dependencies (`pip install -e ".[dev]"`)
4. Run `pytest tests/`
5. Install `hatch` and build wheel + sdist (`hatch build`) — validates packaging

**Purpose:** Fast feedback on every push. Catches test failures and packaging errors before they reach a release. Target completion time: under 60 seconds.

### Release Workflow (`.github/workflows/release.yml`)

**Trigger:** push of tag matching `v*` (e.g. `v0.1.0`)

**Steps:**
1. Checkout code
2. Set up Python 3.11
3. Install `hatch`
4. Run `pytest tests/` — abort release if tests fail
5. Build wheel + sdist (`hatch build`)
6. Publish to TestPyPI using `TEST_PYPI_API_TOKEN` secret
7. Publish to PyPI using `PYPI_API_TOKEN` secret

**GitHub Secrets required:**
- `PYPI_API_TOKEN` — PyPI API token (scope: entire account initially)
- `TEST_PYPI_API_TOKEN` — TestPyPI API token (scope: entire account initially)

Both secrets are already configured in the repo settings.

---

## curl Install Script (`scripts/get-screenwarden.sh`)

Single script, three modes auto-detected:

```bash
# Install or update:
curl -fsSL https://raw.githubusercontent.com/voparin/screenwarden/main/scripts/get-screenwarden.sh | sudo bash

# Uninstall:
curl -fsSL https://raw.githubusercontent.com/voparin/screenwarden/main/scripts/get-screenwarden.sh | sudo bash -s -- --uninstall
```

### Install mode (screenwarden not present)
1. Check running as root — exit with error if not
2. Check Python 3.11+ installed — exit with clear message if not
3. `pip install screenwarden`
4. Run `screenwarden install` (interactive: prompts for child username + dashboard password)
5. Print success message with dashboard URL

### Update mode (screenwarden already installed)
1. Check running as root
2. `pip install --upgrade screenwarden`
3. `systemctl restart screenwarden`
4. Print new version

### Uninstall mode (`--uninstall` flag)
1. Check running as root
2. `systemctl stop screenwarden && systemctl disable screenwarden`
3. `pip uninstall -y screenwarden`
4. Remove `/etc/screenwarden/` (config)
5. Remove `/var/lib/screenwarden/` (database)
6. Remove `/etc/systemd/system/screenwarden.service`
7. `systemctl daemon-reload`
8. Print confirmation

### Error handling
- Script uses `set -euo pipefail` — exits on any error
- Each step prints a status line: `[screenwarden] Installing...`
- Non-zero exit on failure with clear message

---

## pyproject.toml Metadata

Add the following fields for PyPI discoverability:

```toml
[project]
authors = [{name = "voparin"}]
license = {text = "MIT"}
readme = "README.md"
keywords = ["parental-control", "screen-time", "linux", "family"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Environment :: No Input/Output (Daemon)",
    "Intended Audience :: End Users/Desktop",
    "License :: OSI Approved :: MIT License",
    "Operating System :: POSIX :: Linux",
    "Programming Language :: Python :: 3.11",
]

[project.urls]
Homepage = "https://github.com/voparin/screenwarden"
Issues = "https://github.com/voparin/screenwarden/issues"
```

---

## LICENSE File

Add `LICENSE` to the repo root with standard MIT license text, copyright `2026 voparin`.

---

## Files Created / Modified

| File | Action |
|------|--------|
| `.github/workflows/ci.yml` | Create |
| `.github/workflows/release.yml` | Create |
| `scripts/get-screenwarden.sh` | Create |
| `pyproject.toml` | Modify (add metadata) |
| `LICENSE` | Create |

---

## Out of Scope

- Automatic version bumping tools (`bump-my-version`, `release-please`)
- Dynamic versioning from git tags
- Distro packages (`.deb`/`.rpm`) — Phase 3
- GitHub Release notes automation
