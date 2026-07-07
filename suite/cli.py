"""`suite` CLI entrypoint (ADR-037/042): describe the suite in suite.yaml, then
`suite apply` reconciles reality to it. Every verb speaks admin intent — no
terraform/ansible/helmfile vocabulary on the surface."""

from __future__ import annotations

import argparse

from . import apply, backup, bootstrap, info, restore, spec, status, upgrade, users
from .errors import SuiteError


def _cluster_flags(p, *, yes_help=None):
    p.add_argument("--no-tunnel", action="store_true",
                   help="Use the ambient KUBECONFIG instead of the managed SSH tunnel")
    if yes_help:
        p.add_argument("--yes", action="store_true", help=yes_help)
    return p


def build_parser():
    p = argparse.ArgumentParser(
        prog="suite",
        description="OwnSuite admin CLI — describe your suite in suite.yaml; "
                    "`suite apply` makes it real.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Interactive questionnaire -> writes suite.yaml.")
    _cluster_flags(sub.add_parser(
        "plan", help="Preview what apply would change (infra, apps, DNS) — read-only."))
    ap = _cluster_flags(sub.add_parser(
        "apply", help="Reconcile everything to suite.yaml: provision, bootstrap, "
                      "DNS, deploy/prune apps, verify, print URLs."),
        yes_help="Skip every confirmation (non-interactive)")
    ap.add_argument("--no-snapshot", action="store_true",
                    help="Skip the pre-change backup (config-only change, no data risk)")

    _cluster_flags(sub.add_parser(
        "status", help="Show a health summary (node, DB, certs, backup, apps)."))
    _cluster_flags(sub.add_parser(
        "apps", help="App catalog: available / enabled / installed / healthy / URL."))
    lg = _cluster_flags(sub.add_parser("logs", help="Show an app's pod logs."))
    lg.add_argument("app", help="App name (e.g. tchap)")
    lg.add_argument("--tail", type=int, default=100,
                    help="Lines per pod (default: 100)")
    sub.add_parser("info", help="URLs, admin credentials, DNS records.")

    _cluster_flags(sub.add_parser(
        "upgrade", help="Safely apply pending chart/image upgrades (backup-gated)."),
        yes_help="Skip the diff confirmation (non-interactive)")
    _cluster_flags(sub.add_parser(
        "backup", help="Take a backup now and wait for it to complete."))
    _cluster_flags(sub.add_parser(
        "restore", help="Restore a CLEAN cluster from off-site backups."),
        yes_help="Skip the not-clean safety confirmation (non-interactive)")
    _cluster_flags(sub.add_parser(
        "destroy", help="Uninstall the whole suite from the cluster (data kept)."),
        yes_help="Skip the typed confirmation (non-interactive)")

    # `suite user <verb> <email>` — Keycloak user provisioning (JIT to all apps).
    u = sub.add_parser("user", help="Manage Keycloak users (one identity, all apps via JIT).")
    uver = u.add_subparsers(dest="action", required=True)
    for verb, helptext in (
        ("add", "Create (or update) a user and set an initial password."),
        ("passwd", "Reset a user's password."),
        ("disable", "Deactivate a user (revokes access across all apps)."),
    ):
        sp = uver.add_parser(verb, help=helptext)
        sp.add_argument("email", help="The user's email (also their username).")
        sp.add_argument("--no-tunnel", action="store_true", help="Use the ambient KUBECONFIG")
        sp.add_argument("--local-port", type=int, default=8081, help="Local port-forward port")
        if verb in ("add", "passwd"):
            sp.add_argument("--password", help="Set this password (else generated, shown once)")
            sp.add_argument(
                "--permanent", action="store_true",
                help="Do not force a password change at next login",
            )
        if verb == "add":
            # Keycloak's user profile requires first/last name; default to the email
            # local part so the account is usable (login works) without prompting.
            sp.add_argument("--first-name", help="First name (default: email local part)")
            sp.add_argument("--last-name", help="Last name (default: email local part)")

    sub.add_parser("deps", help="Install Python tooling + Ansible collections (workstation).")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    handlers = {
        "init": spec.run_init,
        "plan": apply.run_plan,
        "apply": apply.run_apply,
        "status": status.run_status,
        "apps": status.run_apps,
        "logs": status.run_logs,
        "info": info.run_info,
        "upgrade": upgrade.run_upgrade,
        "backup": backup.run_backup,
        "restore": restore.run_restore,
        "destroy": apply.run_destroy,
        "user": users.run,
        "deps": bootstrap.run_deps,
    }
    try:
        handlers[args.command](args)
    except SuiteError as exc:
        print(f"\nERROR: {exc}")
        return 1
    except KeyboardInterrupt:
        print("\nAborted.")
        return 130
    return 0
