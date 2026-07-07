"""`suite upgrade` — the safe apply path for version bumps (ADR-034).

Pinned versions land in `helmfile/versions/versions.yaml` via Renovate (ADR-007);
this command is how an operator applies them without losing data:

  1. refuse unless off-site backups are enabled (a destructive op needs a net);
  2. take a fresh pre-upgrade snapshot (CNPG base backup + off-site object copy);
  3. show `helmfile diff` and confirm (skippable with --yes);
  4. `helmfile apply`;
  5. health-check Keycloak + the enabled apps over HTTPS;
  6. on any health failure, `helm rollback` every release of the affected app(s).

`suite apply` shares these rails but reconciles suite.yaml (app set, TLS);
upgrade deliberately stays a separate verb with a harder gate — it exists to
absorb version bumps, a different risk profile (ADR-007).

The snapshot/diff/apply/health/rollback flow is unit-tested with mocked
subprocess calls — especially the backup gate and the rollback-on-failure path.
"""

from __future__ import annotations

import os

from . import backup, config, manifest, process, spec, state, steps, tunnel
from .errors import SuiteError
from .process import run

HELMFILE = "helmfile/helmfile.yaml.gotmpl"
NS = "ownsuite"
REALM = "ownsuite"


def run_upgrade(args):
    ctx = spec.load_context()
    config.require_seed(ctx.state)
    _require_backups_enabled(ctx.view)
    process.preflight(["helmfile", "helm", "kubectl"], ssh=ctx.ssh,
                      no_tunnel=args.no_tunnel, helm_diff=True)

    domain = ctx.spec.domain
    env = ctx.env
    enabled = ctx.spec.enabled_apps()

    with tunnel.maybe(ctx.ssh, no_tunnel=args.no_tunnel):
        env["OWNSUITE_TLS_ISSUER"] = resolve_issuer()
        if backup.snapshot() is None:
            raise SuiteError(
                "backups are enabled but the machinery is not installed — run "
                "`suite apply` first; upgrading without a net is refused (ADR-034)."
            )
        _show_diff(env)
        if not args.yes and not _confirm():
            print("Aborted — no changes applied.")
            return
        print("\n==> Applying (helmfile apply)")
        run(["helmfile", "-f", HELMFILE, "apply"], env=env, step="helmfile apply")
        failed = steps.verify_https(domain, enabled, trusted=True)
        if failed:
            _rollback(failed)
            raise SuiteError(
                "upgrade health check failed for: "
                + ", ".join(failed)
                + " — rolled back the affected release(s). Re-run once resolved."
            )
    state.save(ctx.state)
    print("\n==> Upgrade complete — all health checks passed.")


def _require_backups_enabled(cfg):
    """Refuse to upgrade without off-site backups: the snapshot is the only undo
    for data loss a rollback cannot recover (ADR-006, ADR-034)."""
    if str(cfg.get("OWNSUITE_BACKUP_ENABLED", "false")).lower() != "true":
        raise SuiteError(
            "backups are disabled (backup.enabled != true in suite.yaml) — refusing "
            "to upgrade without a recovery net. Enable backups first."
        )


def resolve_issuer():
    """The CLI owns the TLS issuer so a sync/upgrade can never silently downgrade it
    to `selfsigned` (the helmfile default — `environments/default.yaml.gotmpl`). An
    explicit `OWNSUITE_TLS_ISSUER` wins; otherwise read the issuer actually in force
    from the keycloak-tls Certificate (no persistence, no drift). Requires the tunnel,
    so call it inside `tunnel.maybe(...)`."""
    issuer = os.environ.get("OWNSUITE_TLS_ISSUER")
    if issuer:
        return issuer
    proc = run(
        ["kubectl", "-n", NS, "get", "certificate", "keycloak-tls",
         "-o", "jsonpath={.spec.issuerRef.name}"],
        capture=True, check=False, step="detect TLS issuer",
    )
    issuer = (proc.stdout or "").strip()
    if not issuer:
        raise SuiteError(
            "could not determine the live TLS issuer (keycloak-tls certificate not found). "
            "Export OWNSUITE_TLS_ISSUER=letsencrypt-http01 before running."
        )
    return issuer


def _show_diff(env, selector=()):
    print("\n==> Pending changes (helmfile diff):\n")
    # helmfile diff exits non-zero (2) when there ARE changes; that is not a failure.
    run(["helmfile", "-f", HELMFILE, "diff", *selector], env=env, check=False)


def _confirm():
    return input("\nApply these changes? [y/N]: ").strip().lower() in ("y", "yes")


def _rollback(failed_hosts):
    """Roll back every release of each failed host's app (manifest.HOST_RELEASES —
    a multi-release app like meet rolls back whole) to its previous revision."""
    print("\n==> Health check failed — rolling back affected release(s)")
    for host in failed_hosts:
        for release in manifest.HOST_RELEASES.get(host, ()):
            print(f"  helm rollback {release}")
            # check=False: roll back as many as we can; a single failure must not
            # stop the rest from recovering.
            run(["helm", "-n", NS, "rollback", release], check=False,
                step=f"rollback {release}")
