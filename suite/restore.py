"""`suite restore` — disaster recovery onto a CLEAN cluster (ADR-036).

The CLI counterpart of `make restore` (ADR-006, ADR-017): it rebuilds an instance
from the off-site backups. `make restore` stays the low-level mechanism this wraps;
the verb adds the operator-facing guardrails:

  1. require OWNSUITE_SECRET_SEED exported (helmfile must render — ADR-012);
  2. refuse unless off-site backups are enabled AND a target store is configured —
     restoring from nothing is meaningless (ADR-006);
  3. SAFETY GATE: refuse on a cluster that is NOT clean (an existing CNPG cluster or
     bound app PVCs). Restore assumes a fresh cluster — CNPG recovery + the restore
     Jobs would clobber live data. Override with an explicit typed confirmation, or
     --yes for unattended runs;
  4. open the SSH tunnel (ADR-014), run the restore-mode sync
     (OWNSUITE_RESTORE=true OWNSUITE_BACKUP_ENABLED=true helmfile sync), then verify
     that Keycloak and each enabled app answer over HTTPS, reusing suite.verify.

The gates and the restore-mode env are unit-tested with mocked subprocess/HTTPS
calls — no live cluster.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil

from . import config, tunnel, verify
from .errors import SuiteError
from .process import run
from .status import enabled_apps

HELMFILE = "helmfile/helmfile.yaml.gotmpl"
NS = "ownsuite"
REALM = "ownsuite"


def run_restore(args):
    cfg = config.load_env(args.env_file)
    ssh = getattr(args, "ssh", None) or cfg.get("OWNSUITE_SERVER_SSH", "")
    seed = os.environ.get("OWNSUITE_SECRET_SEED")
    if not seed:
        raise SuiteError(
            "OWNSUITE_SECRET_SEED must be exported — helmfile needs it to render (ADR-012)."
        )
    _require_backups_configured(cfg)
    _preflight(args, ssh)

    domain = cfg.get("OWNSUITE_DOMAIN")
    if not domain:
        raise SuiteError("OWNSUITE_DOMAIN is required (read from .env or --env-file)")
    # Restore mode + backups forced on, exactly as `make restore` runs it: CNPG
    # bootstraps via recovery and the object/pvc restore Jobs run (ADR-006, ADR-017).
    env = {
        **cfg,
        "OWNSUITE_SECRET_SEED": seed,
        "OWNSUITE_RESTORE": "true",
        "OWNSUITE_BACKUP_ENABLED": "true",
    }
    enabled = enabled_apps(cfg)

    tunnel_ctx = (
        contextlib.nullcontext()
        if args.no_tunnel or not ssh
        else tunnel.tunnel(ssh)
    )
    with tunnel_ctx:
        if not args.yes and not _cluster_is_clean() and not _confirm_not_clean():
            print("Aborted — cluster is not clean; nothing changed.")
            return
        print("\nRestore expects a clean cluster (no prior PVCs) with backups configured.")
        print("\n==> Restoring (helmfile sync, restore mode)")
        run(["helmfile", "-f", HELMFILE, "sync"], env=env, step="helmfile sync")
        failed = _verify(domain, enabled)
        if failed:
            raise SuiteError(
                "restore verification failed for: "
                + ", ".join(failed)
                + " — the suite did not come back cleanly. Inspect the pods/logs and "
                "the off-site backups before retrying."
            )
    print("\n==> Restore complete — Keycloak and all enabled apps answered.")


def _require_backups_configured(cfg):
    """Refuse to restore without a source: off-site backups must be enabled AND a
    target store configured — there is nothing to recover from otherwise (ADR-006,
    ADR-017)."""
    def val(key, default=""):
        return os.environ.get(key, cfg.get(key, default))

    if str(val("OWNSUITE_BACKUP_ENABLED", "false")).lower() != "true":
        raise SuiteError(
            "backups are disabled (OWNSUITE_BACKUP_ENABLED != true) — there is nothing "
            "to restore from. Restore needs the source store that backups wrote to."
        )
    if not str(val("OWNSUITE_BACKUP_S3_BUCKET", "ownsuite-backups")):
        raise SuiteError("no backup target configured (OWNSUITE_BACKUP_S3_BUCKET is empty).")
    if str(val("OWNSUITE_BACKUP_S3_TARGET", "in-cluster")) == "external" \
            and not val("OWNSUITE_BACKUP_S3_ENDPOINT"):
        raise SuiteError(
            "backup target is external but OWNSUITE_BACKUP_S3_ENDPOINT is unset — "
            "point it at the off-site store to restore from."
        )


def _cluster_is_clean():
    """A fresh cluster has no prior data: no CNPG Cluster and no bound PVCs in the
    workloads namespace. Restore (CNPG recovery + restore Jobs) assumes this."""
    if _kubectl_items(["-n", NS, "get", "clusters.postgresql.cnpg.io"]):
        return False
    bound = [p for p in _kubectl_items(["-n", NS, "get", "pvc"])
             if p.get("status", {}).get("phase") == "Bound"]
    return not bound


def _kubectl_items(argv):
    """kubectl get -o json, tolerant: a missing CRD or namespace on a truly fresh
    cluster means 'nothing there', not a hard error (unlike status._kubectl_json)."""
    proc = run(["kubectl", *argv, "-o", "json"], capture=True, check=False, step="kubectl get")
    if proc.returncode != 0:
        return []
    return json.loads(proc.stdout or "{}").get("items", [])


def _confirm_not_clean():
    print(
        "\nWARNING: this cluster is NOT clean — an existing CNPG cluster and/or bound\n"
        "PVCs were found in the 'ownsuite' namespace. Restore assumes a FRESH cluster\n"
        "(CNPG recovery + restore Jobs) and can CLOBBER existing data here.\n"
    )
    # Typed confirmation, not a bare y/N — this is destructive (use --yes to skip).
    return input("Type 'restore' to proceed anyway: ").strip().lower() == "restore"


def _verify(domain, enabled):
    """Confirm Keycloak and each enabled app answer over HTTPS after the restore.
    Keycloak underpins every app's SSO, so it is always checked. Returns failures."""
    targets = {
        "auth": f"https://auth.{domain}/realms/{REALM}/.well-known/openid-configuration",
    }
    for app in enabled:
        targets[app] = f"https://{app}.{domain}/"
    print("\n==> Verifying the restored suite:")
    failed = []
    for host, url in targets.items():
        ok = verify.https_ok(url, verify=True)
        print(f"  {'OK  ' if ok else 'FAIL'} {host}: {url}")
        if not ok:
            failed.append(host)
    return failed


def _preflight(args, ssh):
    tools = ["helmfile", "kubectl"]
    if not args.no_tunnel and ssh:
        tools.append("ssh")
    missing = [t for t in tools if not shutil.which(t)]
    if missing:
        raise SuiteError(f"missing required tools on PATH: {', '.join(missing)}")
