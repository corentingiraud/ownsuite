"""Docs 6.0 backfill: hand every legacy document to the yhub collaboration server.

Docs 6.0 replaced y-provider with yhub. A document is seeded lazily the first time it
is opened, but one nobody opens stays in S3 forever, so after `helmfile apply` the
backend's `migrate_documents` command is run over the whole corpus. It is idempotent
(per-document status lives in the `impress_document_migration` table), so it runs on
every apply: a fresh install has 0 documents and the run is a no-op.

Flow: `--dry-run` (cheap sanity check of the command and the DB), the real run with a
conservative concurrency and rate (single node, 4 GB), then `--retry-failed` until no
document is left failed, within a bounded number of attempts. On success the flag
`docs_yhub_migrated` is recorded in `.suite-state.json`.
"""

from __future__ import annotations

import re

from .errors import SuiteError
from .process import run

NS = "ownsuite"
DEPLOY = "deploy/docs-backend"
STATE_FLAG = "docs_yhub_migrated"

# Conservative for a single 4 GB node: few documents in flight, throttled hand-over.
CONCURRENCY = "2"
RATE = "5"
MAX_RETRIES = 5

_FAILED_COUNT = re.compile(r"(\d+)\s+failed|failed\D{0,3}(\d+)", re.IGNORECASE)


def _manage(*flags: str, check: bool = True):
    return run(
        ["kubectl", "-n", NS, "exec", DEPLOY, "--", "python", "manage.py",
         "migrate_documents", *flags],
        capture=True, check=check, step="docs migrate_documents",
    )


def _failed_left(proc) -> bool:
    """True when documents are still failed after a run: a non-zero exit, or a
    non-zero failed count in the output (when the command reports one)."""
    if proc.returncode != 0:
        return True
    out = (proc.stdout or "") + (proc.stderr or "")
    return any(int(n) > 0 for m in _FAILED_COUNT.finditer(out)
               for n in m.groups() if n)


def backfill(st: dict) -> None:
    """Run the backfill and set `docs_yhub_migrated` in `st` (caller saves it)."""
    print("\n==> Docs backfill (migrate_documents)")
    _manage("--dry-run")
    proc = _manage("--concurrency", CONCURRENCY, "--rate", RATE, check=False)
    attempts = 0
    while _failed_left(proc):
        if attempts >= MAX_RETRIES:
            tail = ((proc.stderr or "") + (proc.stdout or ""))[-1000:]
            raise SuiteError(
                f"docs backfill: documents still failed after {MAX_RETRIES} "
                "--retry-failed attempts. Fix the cause (yhub logs, legacy S3 "
                "access) and re-run `suite apply`; SOFT_MIGRATION stays on so "
                f"nothing is lost.\n{tail}".rstrip()
            )
        attempts += 1
        print(f"    retrying failed documents ({attempts}/{MAX_RETRIES})")
        proc = _manage("--retry-failed", "--concurrency", CONCURRENCY, "--rate", RATE,
                       check=False)
    st[STATE_FLAG] = True
    print("    all documents migrated.")


def run_if_enabled(enabled, st: dict) -> None:
    """Post-apply hook: only when Docs is enabled."""
    if "docs" in enabled:
        backfill(st)
