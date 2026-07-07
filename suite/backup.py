"""On-demand backups: the pre-change snapshot + the `suite backup` verb.

Python port of the old `make backup` recipe (ADR-006/017): a CNPG on-demand base
backup (Backup CR, plugin method) plus a manual Job from the `object-backup`
CronJob. `snapshot()` keeps the fire-and-forget semantics upgrade/sync relied on;
the explicit `suite backup` verb additionally polls both to completion.
"""

from __future__ import annotations

import json
import time

from . import process, spec, tunnel
from .errors import SuiteError
from .process import run

NS = "ownsuite"
PG_CLUSTER = "ownsuite-pg"

PG_BACKUP_MANIFEST = f"""\
apiVersion: postgresql.cnpg.io/v1
kind: Backup
metadata:
  generateName: {PG_CLUSTER}-ondemand-
spec:
  cluster:
    name: {PG_CLUSTER}
  method: plugin
  pluginConfiguration:
    name: barman-cloud.cloudnative-pg.io
"""


def machinery_present():
    """Both halves of the backup path exist: the CNPG cluster and the object-backup
    CronJob. Absent mid-first-bring-up or when backups are disabled."""
    checks = (
        ["kubectl", "-n", NS, "get", f"clusters.postgresql.cnpg.io/{PG_CLUSTER}"],
        ["kubectl", "-n", NS, "get", "cronjob/object-backup"],
    )
    return all(run(c, capture=True, check=False).returncode == 0 for c in checks)


def snapshot():
    """Fire-and-forget pre-change snapshot. Returns (pg_backup, job) names, or None
    when the backup machinery is not installed yet (first bring-up / a retried
    partial bring-up — nothing recoverable to lose, and nothing to run it with)."""
    if not machinery_present():
        print("  NOTE backup machinery not installed yet — skipping the snapshot.")
        return None
    print("\n==> Taking a snapshot (CNPG base backup + off-site object copy)")
    proc = run(["kubectl", "-n", NS, "create", "-o", "name", "-f", "-"],
               input_text=PG_BACKUP_MANIFEST, capture=True, step="create CNPG backup")
    pg_backup = (proc.stdout or "").strip().rpartition("/")[2]
    print(f"  created backup/{pg_backup}")
    job = f"object-backup-manual-{int(time.time())}"
    run(["kubectl", "-n", NS, "create", "job", "--from=cronjob/object-backup", job],
        step="create object-backup job")
    return pg_backup, job


def run_backup(args):
    """`suite backup` — take a backup NOW and wait until both halves complete."""
    ctx = spec.load_context()
    process.preflight(["kubectl"], ssh=ctx.ssh, no_tunnel=args.no_tunnel)
    with tunnel.maybe(ctx.ssh, no_tunnel=args.no_tunnel):
        names = snapshot()
        if not names:
            raise SuiteError(
                "backup machinery not installed — enable backups in suite.yaml "
                "(backup.enabled: true) and run `suite apply` first."
            )
        _wait(*names)
    print("\n==> Backup complete (PostgreSQL base backup + off-site object copy).")


def _wait(pg_backup, job, timeout=900):
    deadline = time.time() + timeout
    print(f"  waiting for backup/{pg_backup} ...")
    while True:
        proc = run(["kubectl", "-n", NS, "get", f"backups.postgresql.cnpg.io/{pg_backup}",
                    "-o", "jsonpath={.status.phase}"], capture=True, check=False)
        phase = (proc.stdout or "").strip()
        if phase == "completed":
            print(f"  OK   backup/{pg_backup}")
            break
        if phase == "failed":
            raise SuiteError(
                f"CNPG backup {pg_backup} failed — "
                f"`kubectl -n {NS} describe backup {pg_backup}` for details."
            )
        if time.time() > deadline:
            raise SuiteError(f"CNPG backup {pg_backup} did not complete in {timeout}s")
        time.sleep(5)
    print(f"  waiting for job/{job} ...")
    while True:
        proc = run(["kubectl", "-n", NS, "get", f"job/{job}", "-o", "json"],
                   capture=True, check=False)
        status = json.loads(proc.stdout or "{}").get("status", {})
        if status.get("succeeded"):
            print(f"  OK   job/{job}")
            return
        if any(c.get("type") == "Failed" and c.get("status") == "True"
               for c in status.get("conditions") or []):
            raise SuiteError(
                f"object-backup job {job} failed — "
                f"`kubectl -n {NS} logs job/{job}` for details."
            )
        if time.time() > deadline:
            raise SuiteError(f"object-backup job {job} did not complete in {timeout}s")
        time.sleep(5)
