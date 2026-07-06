"""Capture configuration and the secret seed.

The seed is generated and shown ONCE; it is NEVER written to the repo (held in
the process env for the run; on re-run the operator re-exports it). Non-secret
``OWNSUITE_*`` values go to a git-ignored ``.env`` for reuse.
"""

from __future__ import annotations

import hashlib
import secrets
from pathlib import Path

# Free-text fields (env key, prompt, default). SSH may be left blank — `provision`
# or the bootstrap can fill it. Advanced knobs stay in .env / the Helmfile defaults.
TEXT_PROMPTS = [
    ("OWNSUITE_DOMAIN", "Base domain (e.g. assoc.example.org)", "", True),
    ("OWNSUITE_ADMIN_EMAIL", "Admin email", "", True),
    ("OWNSUITE_SERVER_SSH", "Server SSH target (user@host, blank if unknown yet)", "", False),
]

# App toggles — every app is off by default (ADR-035); the operator opts each in
# via a checkbox (or OWNSUITE_APP_*).
# The mailbox (ADR-026) is more involved: if enabled, the installer also generates
# a DKIM key and prints MX/SPF/DKIM/DMARC + the rDNS/port-25 manual steps and needs
# the relay account (OWNSUITE_MTA_RELAY_USERNAME/PASSWORD) exported before sync.
APPS = [
    ("OWNSUITE_APP_DOCS", "Docs (collaborative documents)"),
    ("OWNSUITE_APP_DRIVE", "Drive (file storage)"),
    ("OWNSUITE_APP_GRIST", "Grist (spreadsheets/tables)"),
    ("OWNSUITE_APP_PROJECTS", "Projects (kanban)"),
    ("OWNSUITE_APP_MESSAGES", "Mailbox (email — needs extra DNS/relay setup)"),
    ("OWNSUITE_APP_MEET", "Meet (video — needs media ports via enable_meet)"),
    ("OWNSUITE_APP_TCHAP", "Tchap (Matrix/Element chat — text-only, SSO via Keycloak)"),
]


def _b(value):
    return "true" if value else "false"  # normalise a bool answer to the .env form


def _required(text):
    return True if text.strip() else "This value is required."


def generate_seed():
    return secrets.token_hex(24)  # same format as `openssl rand -hex 24`


def derive_secret(seed, secret_id, length=32):
    """Mirror the Helm chart helper (ADR-012): sha256("<seed>:<id>") truncated.

    Same (seed, id) the chart used, so a credential the platform derived in-cluster
    (e.g. the Keycloak admin password, id "keycloak-admin") is reproduced here with
    nothing secret read from the cluster.
    """
    return hashlib.sha256(f"{seed}:{secret_id}".encode()).hexdigest()[:length]


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
        from . import prompt  # local import: questionary only needed interactively

        for key, label, default, required in TEXT_PROMPTS:
            validate = _required if required else None
            cfg[key] = prompt.text(label, default=cfg.get(key, default), validate=validate)
        cfg["OWNSUITE_OBJECT_STORAGE_MODE"] = prompt.select(
            "Object storage", ["external", "garage"],
            default=cfg.get("OWNSUITE_OBJECT_STORAGE_MODE", "external"),
        )
        cfg["OWNSUITE_BACKUP_ENABLED"] = _b(prompt.confirm(
            "Enable off-site backups?",
            default=cfg.get("OWNSUITE_BACKUP_ENABLED", "true") != "false",
        ))
        # Checkbox pre-ticks apps already enabled in .env; unticked apps become false.
        enabled = prompt.checkbox(
            "Enable apps (space to toggle, enter to confirm)",
            choices=[label for _, label in APPS],
            checked=[label for key, label in APPS if cfg.get(key) == "true"],
        )
        for key, label in APPS:
            cfg[key] = _b(label in enabled)
    admin = cfg.get("OWNSUITE_ADMIN_EMAIL")
    if admin and not cfg.get("OWNSUITE_ACME_EMAIL"):
        cfg["OWNSUITE_ACME_EMAIL"] = admin
    return cfg
