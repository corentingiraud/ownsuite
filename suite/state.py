"""Machine state (`.suite-state.json`) — what the CLI must remember between runs
that is NOT operator intent (ADR-042): the provisioned SSH target, terraform-minted
credentials/values (`env`), the last-generated tfvars and firewall flags (change
detection), and a fingerprint of the seed. `suite.yaml` is the human file; this one
is machine-written only, git-ignored, mode 0600 (it holds provider-minted secrets).
The seed itself is NEVER stored (ADR-012) — `save` enforces that.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .errors import SuiteError

SEED_KEY = "OWNSUITE_SECRET_SEED"


def path() -> Path:
    """Next to suite.yaml, honouring the same OWNSUITE_CONFIG override (so e2e/tests
    never touch a developer's real state)."""
    cfg = Path(os.environ.get("OWNSUITE_CONFIG", "suite.yaml"))
    return cfg.with_name(".suite-state.json")


def load() -> dict:
    p = path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text() or "{}")
    except ValueError as exc:
        raise SuiteError(f"{p} is corrupt ({exc}) — fix or delete it.") from exc


def save(st: dict) -> None:
    if SEED_KEY in st.get("env", {}) or SEED_KEY in st:
        raise SuiteError("refusing to persist the secret seed (ADR-012)")
    p = path()
    data = json.dumps(st, indent=2, sort_keys=True) + "\n"
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(data)
