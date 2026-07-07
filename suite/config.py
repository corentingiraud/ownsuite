"""The secret seed (ADR-012): generation, derivation, and the prompt-don't-fail
acquisition every verb uses.

The seed is generated and shown ONCE; it is NEVER written anywhere (held in the
process env for the run; on re-run the operator re-exports or re-pastes it). A
non-reversible fingerprint in the machine state guards against applying with the
wrong seed, which would silently rotate every derived credential.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sys
from pathlib import Path

from .errors import SuiteError


def load_env_file(path=".env"):
    """Auto-load KEY=VALUE lines from .env into the environment (called once at CLI
    startup) so the operator never has to `source .env` first. That manual step is
    error-prone: a forgotten source leaves the external creds (S3/backup/relay keys)
    unset, and the helmfile then silently falls back to seed-derived values —
    OVERWRITING the real deployed keys on apply. Already-exported vars win (the
    documented precedence puts ambient env first), so CI/manual overrides still take
    precedence. No-op if .env is absent."""
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]  # strip matching surrounding quotes
        if key:
            os.environ.setdefault(key, val)  # ambient export wins over the file


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


