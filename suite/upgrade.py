"""`suite upgrade` — the safe apply path for version bumps (ADR-034).

Pinned versions land in `helmfile/versions/versions.yaml` via Renovate (ADR-007);
this command is how an operator applies them without losing data:

  1. refuse unless off-site backups are enabled (a destructive op needs a net);
  2. take a fresh pre-upgrade snapshot, reusing `make backup` (CNPG base backup +
     off-site object copy) — we do not reinvent the backup path;
  3. show `helmfile diff` and confirm (skippable with --yes, like `install`);
  4. `helmfile apply`;
  5. health-check the enabled apps by reusing suite.verify;
  6. on any health failure, `helm rollback` the affected release(s).

The snapshot/diff/apply/health/rollback flow is unit-tested with mocked
subprocess calls — especially the backup gate and the rollback-on-failure path.
"""

from __future__ import annotations

import contextlib
import os
import shutil

from . import config, tunnel, verify
from .errors import SuiteError
from .process import run
from .status import enabled_apps

HELMFILE = "helmfile/helmfile.yaml.gotmpl"
NS = "ownsuite"
REALM = "ownsuite"
# Health target per app/host -> the Helm release to roll back if it fails.
# Keycloak underpins every app's SSO, so it is always checked.
RELEASE_BY_HOST = {
    "auth": "keycloak",
    "docs": "docs",
    "drive": "drive",
    "grist": "grist",
    "projects": "projects",
    "messages": "messages",
}


def run_upgrade(args):
    cfg = config.load_env(args.env_file)
    ssh = getattr(args, "ssh", None) or cfg.get("OWNSUITE_SERVER_SSH", "")
    seed = os.environ.get("OWNSUITE_SECRET_SEED")
    if not seed:
        raise SuiteError(
            "OWNSUITE_SECRET_SEED must be exported — helmfile needs it to render (ADR-012)."
        )
    _require_backups_enabled(cfg)
    _preflight(args, ssh)

    domain = cfg.get("OWNSUITE_DOMAIN")
    if not domain:
        raise SuiteError("OWNSUITE_DOMAIN is required (read from .env or --env-file)")
    env = {**cfg, "OWNSUITE_SECRET_SEED": seed}
    enabled = enabled_apps(cfg)

    tunnel_ctx = (
        contextlib.nullcontext()
        if args.no_tunnel or not ssh
        else tunnel.tunnel(ssh)
    )
    with tunnel_ctx:
        _snapshot()
        _show_diff(env)
        if not args.yes and not _confirm():
            print("Aborted — no changes applied.")
            return
        print("\n==> Applying (helmfile apply)")
        run(["helmfile", "-f", HELMFILE, "apply"], env=env, step="helmfile apply")
        failed = _health_check(domain, enabled)
        if failed:
            _rollback(failed)
            raise SuiteError(
                "upgrade health check failed for: "
                + ", ".join(failed)
                + " — rolled back the affected release(s). Re-run once resolved."
            )
    print("\n==> Upgrade complete — all health checks passed.")


def _require_backups_enabled(cfg):
    """Refuse to upgrade without off-site backups: the snapshot is the only undo
    for data loss a rollback cannot recover (ADR-006, ADR-034)."""
    val = os.environ.get("OWNSUITE_BACKUP_ENABLED", cfg.get("OWNSUITE_BACKUP_ENABLED", "true"))
    if str(val).lower() != "true":
        raise SuiteError(
            "backups are disabled (OWNSUITE_BACKUP_ENABLED != true) — refusing to "
            "upgrade without a recovery net. Enable backups first."
        )


def _snapshot():
    print("\n==> Taking a pre-upgrade snapshot (CNPG base backup + off-site object copy)")
    run(["make", "backup"], step="make backup")


def _show_diff(env):
    print("\n==> Pending changes (helmfile diff):\n")
    # helmfile diff exits non-zero (2) when there ARE changes; that is not a failure.
    run(["helmfile", "-f", HELMFILE, "diff"], env=env, check=False)


def _confirm():
    return input("\nApply these changes? [y/N]: ").strip().lower() in ("y", "yes")


def _health_check(domain, enabled):
    """Return the list of hosts that failed. Keycloak is always checked; each
    enabled app is checked at its public HTTPS host."""
    targets = {
        "auth": f"https://auth.{domain}/realms/{REALM}/.well-known/openid-configuration",
    }
    for app in enabled:
        targets[app] = f"https://{app}.{domain}/"
    failed = []
    for host, url in targets.items():
        ok = verify.https_ok(url, verify=True)
        print(f"  {'OK  ' if ok else 'FAIL'} {host}: {url}")
        if not ok:
            failed.append(host)
    return failed


def _rollback(failed_hosts):
    """Roll back each failed host's Helm release to its previous revision."""
    print("\n==> Health check failed — rolling back affected release(s)")
    for host in failed_hosts:
        release = RELEASE_BY_HOST.get(host)
        if not release:
            continue
        print(f"  helm rollback {release}")
        # check=False: roll back as many as we can; a single failure must not stop
        # the rest from recovering.
        run(["helm", "-n", NS, "rollback", release], check=False, step=f"rollback {release}")


def _preflight(args, ssh):
    tools = ["helmfile", "helm", "kubectl", "make"]
    if not args.no_tunnel and ssh:
        tools.append("ssh")
    missing = [t for t in tools if not shutil.which(t)]
    if missing:
        raise SuiteError(f"missing required tools on PATH: {', '.join(missing)}")
