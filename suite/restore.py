"""`suite restore` — disaster recovery onto a CLEAN cluster (ADR-036).

The CLI counterpart of `make restore` (ADR-006, ADR-017): it rebuilds an instance
from the off-site backups. `make restore` stays the low-level mechanism this wraps;
the verb adds the operator-facing guardrails:

  1. require the secret seed (prompted if interactive — helmfile must render,
     ADR-012);
  2. refuse unless off-site backups are enabled AND a target store is configured
     in suite.yaml — restoring from nothing is meaningless (ADR-006);
  3. SAFETY GATE: refuse on a cluster that is NOT clean (an existing CNPG cluster or
     bound app PVCs). Restore assumes a fresh cluster — CNPG recovery + the restore
     Jobs would clobber live data. Override with an explicit typed confirmation, or
     --yes for unattended runs;
  4. open the SSH tunnel (ADR-014), pin the live TLS issuer (like apply/upgrade, so a
     restore never silently downgrades certs to `selfsigned` — the helmfile default),
     run the restore-mode sync (OWNSUITE_RESTORE=true OWNSUITE_BACKUP_ENABLED=true
     helmfile sync), then verify that Keycloak and each enabled app answer over HTTPS.

The gates and the restore-mode env are unit-tested with mocked subprocess/HTTPS
calls — no live cluster.
"""

from __future__ import annotations

import json

from . import config, process, spec, state, steps, tunnel
from .errors import SuiteError
from .process import run
from .upgrade import resolve_issuer

HELMFILE = "helmfile/helmfile.yaml.gotmpl"
NS = "ownsuite"
REALM = "ownsuite"


def run_restore(args):
    ctx = spec.load_context()
    config.require_seed(ctx.state)
    _require_backups_configured(ctx.view)
    process.preflight(["helmfile", "kubectl"], ssh=ctx.ssh, no_tunnel=args.no_tunnel)

    domain = ctx.spec.domain
    # Restore mode + backups forced on, exactly as `make restore` runs it: CNPG
    # bootstraps via recovery and the object/pvc restore Jobs run (ADR-006, ADR-017).
    env = {
        **ctx.env,
        "OWNSUITE_RESTORE": "true",
        "OWNSUITE_BACKUP_ENABLED": "true",
    }
    enabled = ctx.spec.enabled_apps()

    with tunnel.maybe(ctx.ssh, no_tunnel=args.no_tunnel):
        if not args.yes and not _cluster_is_clean() and not _confirm_not_clean():
            print("Aborted — cluster is not clean; nothing changed.")
            return
        # Pin the issuer the same way upgrade does: an explicit OWNSUITE_TLS_ISSUER
        # wins, else detect the one in force from the keycloak-tls cert. Without this,
        # restore-mode sync would default to `selfsigned` and downgrade live certs. On a
        # truly bare cluster (no cert yet) resolve_issuer tells the operator to export it.
        env["OWNSUITE_TLS_ISSUER"] = resolve_issuer()
        print("\nRestore expects a clean cluster (no prior PVCs) with backups configured.")
        print("\n==> Restoring (helmfile sync, restore mode)")
        run(["helmfile", "-f", HELMFILE, "sync"], env=env, step="helmfile sync")
        print("\n==> Verifying the restored suite:")
        failed = steps.verify_https(domain, enabled, trusted=True)
        if failed:
            raise SuiteError(
                "restore verification failed for: "
                + ", ".join(failed)
                + " — the suite did not come back cleanly. Inspect the pods/logs and "
                "the off-site backups before retrying."
            )
    state.save(ctx.state)
    print("\n==> Restore complete — Keycloak and all enabled apps answered.")


def _require_backups_configured(cfg):
    """Refuse to restore without a source: off-site backups must be enabled AND a
    target store configured — there is nothing to recover from otherwise (ADR-006,
    ADR-017)."""
    def val(key, default=""):
        return cfg.get(key, default)

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
