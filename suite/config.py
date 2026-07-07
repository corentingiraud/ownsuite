"""Capture configuration and the secret seed.

The seed is generated and shown ONCE; it is NEVER written to the repo (held in
the process env for the run; on re-run the operator re-exports it). Non-secret
``OWNSUITE_*`` values go to a git-ignored ``.env`` for reuse.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sys
from pathlib import Path

from . import manifest
from .errors import SuiteError

# Free-text fields (env key, prompt, default). SSH may be left blank — `provision`
# or the bootstrap can fill it. Advanced knobs stay in .env / the Helmfile defaults.
TEXT_PROMPTS = [
    ("OWNSUITE_DOMAIN", "Base domain (e.g. assoc.example.org)", "", True),
    ("OWNSUITE_ADMIN_EMAIL", "Admin email", "", True),
    ("OWNSUITE_SERVER_SSH", "Server SSH target (user@host, blank if unknown yet)", "", False),
]

# App toggles — every app is off by default (ADR-035); the operator opts each in
# via a checkbox (or OWNSUITE_APP_*). Derived from the single app manifest.
APPS = [(a.env_key, a.label) for a in manifest.APPS.values()]


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


def seed_fingerprint(seed):
    """Non-reversible check value stored in the machine state: lets a later run
    refuse a WRONG seed (which would silently re-derive — i.e. rotate — every
    credential) without ever persisting the seed itself (ADR-012)."""
    return hashlib.sha256(seed.encode()).hexdigest()[:12]


def require_seed(st, *, interactive=None):
    """Return the secret seed, prompting instead of failing mid-run (issue #82).

    Exported OWNSUITE_SECRET_SEED wins. Otherwise, interactively: offer to
    generate one on a genuinely new deployment (no fingerprint in the state yet),
    else prompt for a paste. Non-interactive (CI) without an export is a hard
    error. Whatever seed is used is validated against the state fingerprint and
    exported to os.environ for every subprocess this run spawns.
    """
    if interactive is None:
        interactive = sys.stdin.isatty()
    seed = (os.environ.get("OWNSUITE_SECRET_SEED") or "").strip()
    if not seed:
        if not interactive:
            raise SuiteError(
                "OWNSUITE_SECRET_SEED must be exported — every credential derives "
                "from it and it is never stored (ADR-012)."
            )
        from . import prompt  # local import: questionary only needed interactively

        if not st.get("seed_check") and prompt.confirm(
            "No OWNSUITE_SECRET_SEED exported. Generate a NEW seed (first "
            "deployment only — a wrong answer rotates every credential)?",
            default=False,
        ):
            seed = generate_seed()
            seed_banner(seed)
        else:
            seed = prompt.password("Paste OWNSUITE_SECRET_SEED (from your password manager)")
        if not seed:
            raise SuiteError("no seed provided — aborting (ADR-012).")
    check = seed_fingerprint(seed)
    known = st.get("seed_check")
    if known and known != check:
        raise SuiteError(
            "this OWNSUITE_SECRET_SEED is NOT the seed this deployment was created "
            "with — applying would silently rotate every derived credential "
            "(Keycloak admin, DB passwords, S3 keys). Export the original seed, or "
            "delete .suite-state.json if the rotation is intentional."
        )
    st["seed_check"] = check  # callers persist the state after a successful run
    os.environ["OWNSUITE_SECRET_SEED"] = seed
    return seed


def seed_banner(seed):
    print(
        "\n" + "=" * 70 + "\n"
        "SECRET SEED — store this in your password manager NOW. It is shown once\n"
        "and is NEVER written to the repo. Every credential derives from it; lose\n"
        "it and you must rotate everything (ADR-012).\n\n"
        f"  OWNSUITE_SECRET_SEED={seed}\n\n"
        "Re-run with it exported (export OWNSUITE_SECRET_SEED=...) to resume.\n"
        + "=" * 70
    )


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
