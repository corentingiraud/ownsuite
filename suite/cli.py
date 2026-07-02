"""`suite` CLI entrypoint (Phase 4). One command — `install` — prefiguring the
Phase 5 `suite <verb>` surface (ADR-007)."""

from __future__ import annotations

import argparse

from . import bootstrap, provision, restore, status, steps, sync, upgrade, users
from .errors import SuiteError


def build_parser():
    p = argparse.ArgumentParser(prog="suite", description="OwnSuite installer + admin CLI.")
    sub = p.add_subparsers(dest="command", required=True)

    # Workstation tooling + server provisioning (ADR-037). Flag-free: deps reads the
    # repo's requirements files; bootstrap/check read the Ansible inventory.
    sub.add_parser("deps", help="Install Python tooling + Ansible collections.")
    sub.add_parser("bootstrap", help="Provision a bare server into a single-node K3s cluster.")
    sub.add_parser("check", help="Dry-run the bootstrap (--check --diff); applies nothing.")

    i = sub.add_parser("install", help="Guided install: bare server + domain -> HTTPS.")
    i.add_argument("--env-file", default=".env")
    i.add_argument("--domain", help="Base domain (else prompted / read from .env)")
    i.add_argument("--ssh", help="Server SSH target user@host (for bootstrap/tunnel/IP)")
    i.add_argument("--public-ip", help="Override the detected server public IPv4")
    i.add_argument(
        "--tls-mode", choices=("selfsigned", "staging", "prod"), default="prod",
        help="selfsigned (CI), staging (LE staging only), prod (staging then prod)",
    )
    i.add_argument("--non-interactive", action="store_true", help="No prompts (CI)")
    i.add_argument("--no-tunnel", action="store_true", help="Use the ambient KUBECONFIG")
    i.add_argument("--skip-provision", action="store_true",
                   help="Do not offer to provision a server with Terraform")
    i.add_argument("--skip-bootstrap", action="store_true")
    i.add_argument("--skip-dns", action="store_true")
    i.add_argument("--skip-propagation", action="store_true")
    # provision (when offered from install) reuses these:
    i.add_argument("--provider", choices=provision.PROVIDERS,
                   help="Cloud provider for `suite provision`")
    i.add_argument("--force-tfvars", action="store_true",
                   help="Regenerate terraform.tfvars from prompts")
    i.add_argument("--yes", action="store_true",
                   help="Auto-approve the Terraform apply (non-interactive)")

    # `suite provision` — run the Terraform step (server + object storage) and wire
    # its outputs into .env + the Ansible inventory (ADR-038). Optional prerequisite.
    pv = sub.add_parser("provision", help="Provision infra with Terraform (server + S3).")
    pv.add_argument("--env-file", default=".env")
    pv.add_argument("--provider", choices=provision.PROVIDERS,
                    help="Cloud provider (else prompted)")
    pv.add_argument("--force-tfvars", action="store_true",
                    help="Regenerate terraform.tfvars from prompts even if it exists")
    pv.add_argument("--yes", action="store_true",
                    help="Skip the plan confirmation (auto-approve apply)")

    # `suite dns` — print the records + write the BIND zone file, without installing.
    d = sub.add_parser("dns", help="Print DNS records + write the BIND zone file (no install).")
    d.add_argument("--env-file", default=".env")
    d.add_argument("--domain", help="Base domain (else read from .env)")
    d.add_argument("--ssh", help="Server SSH target user@host (else from .env; used to detect IP)")
    d.add_argument("--public-ip", help="Server public IPv4 (else detected over SSH / prompted)")
    d.add_argument("--out", help="Zone file path (default: <domain>.zone)")

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
        sp.add_argument("--env-file", default=".env")
        sp.add_argument("--ssh", help="Server SSH target user@host (else read from .env)")
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

    # `suite status` — read-only health summary over the tunnel (ADR-033).
    st = sub.add_parser("status", help="Show a health summary (node, DB, certs, backup, apps).")
    st.add_argument("--env-file", default=".env")
    st.add_argument("--ssh", help="Server SSH target user@host (else read from .env)")
    st.add_argument("--no-tunnel", action="store_true", help="Use the ambient KUBECONFIG")

    # `suite upgrade` — backup-gated snapshot -> diff -> apply -> health -> rollback (ADR-034).
    up = sub.add_parser("upgrade", help="Safely apply pending chart/image upgrades (backup-gated).")
    up.add_argument("--env-file", default=".env")
    up.add_argument("--ssh", help="Server SSH target user@host (else read from .env)")
    up.add_argument("--no-tunnel", action="store_true", help="Use the ambient KUBECONFIG")
    up.add_argument("--yes", action="store_true",
                    help="Skip the diff confirmation (non-interactive)")

    # `suite sync` — targeted: snapshot -> scoped diff -> `helmfile sync -l …` -> scoped
    # health -> scoped rollback, injecting the live TLS issuer (issue #62).
    sy = sub.add_parser("sync", help="Apply ONE release/app with the upgrade rails (targeted).")
    sy.add_argument("--env-file", default=".env")
    sy.add_argument("--ssh", help="Server SSH target user@host (else read from .env)")
    sy.add_argument("--no-tunnel", action="store_true", help="Use the ambient KUBECONFIG")
    sy.add_argument("--yes", action="store_true",
                    help="Skip the diff confirmation (non-interactive)")
    sy.add_argument("--diff", action="store_true",
                    help="Show the scoped diff and exit — apply nothing (no snapshot needed)")
    sy.add_argument("--no-snapshot", action="store_true",
                    help="Skip the pre-sync backup (config-only change, no data risk)")
    sy.add_argument("-l", "--selector", action="append", metavar="RELEASE",
                    help="Release to sync, repeatable (e.g. -l drive-media-proxy)")
    sy.add_argument("--app", action="append", metavar="NAME",
                    help="Sync a whole app's release group, repeatable (e.g. --app drive)")

    # `suite restore` — disaster recovery onto a CLEAN cluster from off-site backups (ADR-036).
    rs = sub.add_parser("restore", help="Restore a CLEAN cluster from off-site backups.")
    rs.add_argument("--env-file", default=".env")
    rs.add_argument("--ssh", help="Server SSH target user@host (else read from .env)")
    rs.add_argument("--no-tunnel", action="store_true", help="Use the ambient KUBECONFIG")
    rs.add_argument("--yes", action="store_true",
                    help="Skip the not-clean safety confirmation (non-interactive)")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "deps":
            bootstrap.run_deps(args)
        elif args.command == "bootstrap":
            bootstrap.run_bootstrap(args)
        elif args.command == "check":
            bootstrap.run_check(args)
        elif args.command == "user":
            users.run(args)
        elif args.command == "status":
            status.run_status(args)
        elif args.command == "upgrade":
            upgrade.run_upgrade(args)
        elif args.command == "sync":
            sync.run_sync(args)
        elif args.command == "restore":
            restore.run_restore(args)
        elif args.command == "provision":
            provision.run_provision(args)
        elif args.command == "dns":
            steps.run_dns(args)
        else:
            steps.install(args)
    except SuiteError as exc:
        print(f"\nERROR: {exc}")
        return 1
    except KeyboardInterrupt:
        print("\nAborted.")
        return 130
    return 0
