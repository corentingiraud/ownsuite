"""`suite sync` — apply ONE release (or one app's release group) with the upgrade
rails, scoped (issue #62).

`suite upgrade` reconciles every release at once (`helmfile apply`), so a surgical
prod change (e.g. one media proxy) meant dropping to a hand-run `helmfile -l …` and
losing every guardrail — snapshot, health-check/rollback, and (worst) the TLS issuer,
which the bare helmfile silently defaults to `selfsigned`.

This wraps `helmfile sync -l name=<release>` while keeping those rails, scoped to the
selected releases:

  1. resolve the env like `upgrade` and inject the live TLS issuer (never `selfsigned`);
  2. optional pre-sync snapshot (`--no-snapshot` skips it for a config-only change);
  3. scoped `helmfile diff` + confirm (skippable with `--yes`);
  4. `helmfile sync -l …` — no full-tree reconciliation;
  5. health-check only the selected releases' apps, and roll back only those on failure.
"""

from __future__ import annotations

import json
import os

from . import config, tunnel, verify
from .errors import SuiteError
from .process import run
from .upgrade import (
    HELMFILE,
    NS,
    REALM,
    _confirm,
    _preflight,
    _require_backups_enabled,
    _show_diff,
    _snapshot,
    resolve_issuer,
)

# Release groups per app — the single source for both `--app` expansion and the scoped
# health check. Verified against helmfile/helmfile.yaml.gotmpl.
APP_RELEASES = {
    "docs": ["docs-ingress", "docs", "docs-media-proxy"],
    "drive": ["drive-ingress", "drive", "drive-media-proxy"],
    "grist": ["grist"],
    "projects": ["projects"],
    "messages": ["messages"],
    "meet": ["meet", "meet-media-proxy", "livekit", "livekit-egress"],
}
# Which public host answers for a release, so a scoped sync health-checks (and rolls
# back) only the affected app(s). Keycloak's host is `auth`. Releases absent here are
# platform releases with no public HTTPS endpoint — synced, but not health-checked.
RELEASE_HOST = {r: app for app, rels in APP_RELEASES.items() for r in rels}
RELEASE_HOST["keycloak"] = "auth"

# The release that owns the shared, seed-derived secrets + config every app/keycloak
# consumes by secretKeyRef (email-relay, db creds, OIDC secrets, S3 creds — ADR-012).
# Every app release `needs: platform-configuration` in the helmfile, so syncing an app
# WITHOUT it can leave the app referencing a secret that only this release creates
# (e.g. email-relay when email is first enabled) — the pod then fails to start. So a
# scoped sync of any such release pulls this one in too (helmfile orders it first).
PLATFORM_CONFIG = "platform-configuration"
NEEDS_PLATFORM_CONFIG = set(RELEASE_HOST)  # every app release + keycloak
# Helm release statuses that are healthy to sync over; anything else (failed,
# pending-*, uninstalling) is a leftover from an interrupted run worth flagging.
HEALTHY_STATUSES = {"deployed", "superseded", "not-found"}


def run_sync(args):
    cfg = config.load_env(args.env_file)
    ssh = getattr(args, "ssh", None) or cfg.get("OWNSUITE_SERVER_SSH", "")
    seed = os.environ.get("OWNSUITE_SECRET_SEED") or cfg.get("OWNSUITE_SECRET_SEED")
    if not seed:
        raise SuiteError(
            "OWNSUITE_SECRET_SEED must be set (exported or in .env) — helmfile needs "
            "it to render (ADR-012)."
        )
    releases = _add_platform_config(_resolve_releases(args))
    if not releases:
        raise SuiteError("nothing selected — pass --app <name> and/or -l <release>.")
    diff_only = getattr(args, "diff", False)
    # The snapshot is the only undo for data loss; gate on backups only when we take one.
    # --diff never mutates, so it needs neither the snapshot nor the backup gate.
    take_snapshot = not args.no_snapshot and not diff_only
    if take_snapshot:
        _require_backups_enabled(cfg)
    _preflight(args, ssh)

    domain = cfg.get("OWNSUITE_DOMAIN")
    if not domain:
        raise SuiteError("OWNSUITE_DOMAIN is required (read from .env or --env-file)")
    env = {**cfg, "OWNSUITE_SECRET_SEED": seed}
    selector = _selector_args(releases)

    with tunnel.maybe(ssh, no_tunnel=args.no_tunnel):
        env["OWNSUITE_TLS_ISSUER"] = resolve_issuer()
        _warn_stuck_releases(releases)
        if take_snapshot:
            _snapshot()
        _show_diff(env, selector)
        if diff_only:
            print("\n==> --diff: showed pending changes only, nothing applied.")
            return
        if not args.yes and not _confirm():
            print("Aborted — no changes applied.")
            return
        print(f"\n==> Syncing {', '.join(releases)} (helmfile sync)")
        print("    Waits for each release's rollout to become healthy — the first pull "
              "of a new image can take several minutes. Interrupting leaves that release "
              "mid-upgrade (helm 'failed'); just re-run to reconcile it.")
        run(["helmfile", "-f", HELMFILE, "sync", *selector], env=env, step="helmfile sync")
        failed = _health_check(domain, releases)
        if failed:
            _rollback(failed, releases)
            raise SuiteError(
                "sync health check failed for: "
                + ", ".join(failed)
                + " — rolled back the affected release(s). Re-run once resolved."
            )
    print("\n==> Sync complete — health checks passed.")


def _resolve_releases(args):
    """Expand `--app <name>` to its release group and take each `-l/--selector` value as
    a release name; dedup, preserving order."""
    releases = []
    for app in args.app or []:
        if app not in APP_RELEASES:
            raise SuiteError(
                f"unknown --app '{app}' (choose from: {', '.join(APP_RELEASES)})"
            )
        releases += APP_RELEASES[app]
    releases += args.selector or []
    seen = set()
    return [r for r in releases if not (r in seen or seen.add(r))]


def _add_platform_config(releases):
    """Prepend `platform-configuration` when any selected release depends on it, so the
    shared secrets/config it owns are reconciled before (helmfile `needs` order) the
    releases that consume them. No-op if nothing needs it or it's already selected."""
    if not any(r in NEEDS_PLATFORM_CONFIG for r in releases) or PLATFORM_CONFIG in releases:
        return releases
    print(f"  including {PLATFORM_CONFIG} (owns the shared secrets/config the selected "
          "release(s) depend on)")
    return [PLATFORM_CONFIG, *releases]


def _warn_stuck_releases(releases):
    """Flag any selected release left in a non-healthy Helm state (e.g. `failed` /
    `pending-upgrade` from an interrupted sync). Syncing reconciles it, but surfacing it
    tells the operator why a re-run was needed. Best-effort: never blocks the sync."""
    proc = run(["helm", "-n", NS, "list", "-a", "-o", "json"],
               capture=True, check=False, step="helm list")
    try:
        status = {r["name"]: r.get("status", "") for r in json.loads(proc.stdout or "[]")}
    except (ValueError, TypeError):
        return
    stuck = [(r, status[r]) for r in releases
             if r in status and status[r] not in HEALTHY_STATUSES]
    for name, st in stuck:
        print(f"  NOTE {name} is in Helm state '{st}' (likely an interrupted run) — "
              "this sync will reconcile it.")


def _selector_args(releases):
    """helmfile OR's repeated `-l`, so one `-l name=<release>` per selected release."""
    args = []
    for r in releases:
        args += ["-l", f"name={r}"]
    return args


def _health_check(domain, releases):
    """Return the hosts that failed among the selected releases' apps. Releases with no
    public host (platform releases) are synced but not checked."""
    hosts = []
    for r in releases:
        host = RELEASE_HOST.get(r)
        if host and host not in hosts:
            hosts.append(host)
    failed = []
    for host in hosts:
        url = (
            f"https://auth.{domain}/realms/{REALM}/.well-known/openid-configuration"
            if host == "auth"
            else f"https://{host}.{domain}/"
        )
        ok = verify.https_ok(url, verify=True)
        print(f"  {'OK  ' if ok else 'FAIL'} {host}: {url}")
        if not ok:
            failed.append(host)
    return failed


def _rollback(failed_hosts, releases):
    """Roll back only the selected releases whose app host failed its health check.
    covers app releases only — a platform release with no host is not rolled
    back (it has no HTTPS check to fail); re-run or `suite upgrade` if that ever matters."""
    print("\n==> Health check failed — rolling back the synced release(s)")
    for r in releases:
        if RELEASE_HOST.get(r) in failed_hosts:
            print(f"  helm rollback {r}")
            # check=False: roll back as many as we can; one failure must not stop the rest.
            run(["helm", "-n", NS, "rollback", r], check=False, step=f"rollback {r}")
