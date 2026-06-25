"""Capture configuration and the secret seed.

The seed is generated and shown ONCE; it is NEVER written to the repo (held in
the process env for the run; on re-run the operator re-exports it). Non-secret
``OWNSUITE_*`` values go to a git-ignored ``.env`` for reuse.
"""

from __future__ import annotations

import secrets
from pathlib import Path

# (env key, prompt, default). Advanced knobs stay in .env / the Helmfile defaults.
PROMPTS = [
    ("OWNSUITE_DOMAIN", "Base domain (e.g. assoc.example.org)", ""),
    ("OWNSUITE_ADMIN_EMAIL", "Admin email", ""),
    ("OWNSUITE_VPS_SSH", "VPS SSH target (user@host)", ""),
    ("OWNSUITE_OBJECT_STORAGE_MODE", "Object storage [external|garage]", "external"),
    ("OWNSUITE_BACKUP_ENABLED", "Enable off-site backups [true|false]", "true"),
]


def generate_seed():
    return secrets.token_hex(24)  # same format as `openssl rand -hex 24`


def load_env(path):
    cfg = {}
    p = Path(path)
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg


def write_env(path, cfg):
    """Persist non-secret config. The seed is intentionally never written here."""
    lines = [
        "# OwnSuite config written by `suite install`. The secret seed is NOT stored",
        "# here — keep OWNSUITE_SECRET_SEED in your password manager (ADR-012).",
        "",
        *(f"{k}={v}" for k, v in cfg.items() if k != "OWNSUITE_SECRET_SEED"),
    ]
    Path(path).write_text("\n".join(lines) + "\n")


def capture(existing, *, interactive=True, overrides=None):
    # Only ask in interactive mode; non-interactive uses .env + overrides and lets
    # any other OWNSUITE_* fall through from the environment / Helmfile defaults
    # (forcing prompt defaults here would clobber env vars like the e2e's settings).
    cfg = {**existing, **(overrides or {})}
    if interactive:
        for key, prompt, default in PROMPTS:
            cur = cfg.get(key, default)
            cfg[key] = input(f"{prompt} [{cur}]: ").strip() or cur
    admin = cfg.get("OWNSUITE_ADMIN_EMAIL")
    if admin and not cfg.get("OWNSUITE_ACME_EMAIL"):
        cfg["OWNSUITE_ACME_EMAIL"] = admin
    return cfg
