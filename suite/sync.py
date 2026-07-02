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


def run_sync(args):
    cfg = config.load_env(args.env_file)
    ssh = getattr(args, "ssh", None) or cfg.get("OWNSUITE_SERVER_SSH", "")
    seed = os.environ.get("OWNSUITE_SECRET_SEED")
    if not seed:
        raise SuiteError(
            "OWNSUITE_SECRET_SEED must be exported — helmfile needs it to render (ADR-012)."
        )
    releases = _resolve_releases(args)
    if not releases:
        raise SuiteError("nothing selected — pass --app <name> and/or -l <release>.")
    # The snapshot is the only undo for data loss; gate on backups only when we take one.
    if not args.no_snapshot:
        _require_backups_enabled(cfg)
    _preflight(args, ssh)

    domain = cfg.get("OWNSUITE_DOMAIN")
    if not domain:
        raise SuiteError("OWNSUITE_DOMAIN is required (read from .env or --env-file)")
    env = {**cfg, "OWNSUITE_SECRET_SEED": seed}
    selector = _selector_args(releases)

    with tunnel.maybe(ssh, no_tunnel=args.no_tunnel):
        env["OWNSUITE_TLS_ISSUER"] = resolve_issuer()
        if not args.no_snapshot:
            _snapshot()
        _show_diff(env, selector)
        if not args.yes and not _confirm():
            print("Aborted — no changes applied.")
            return
        print(f"\n==> Syncing {', '.join(releases)} (helmfile sync)")
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
