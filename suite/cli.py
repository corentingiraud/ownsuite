"""`suite` CLI entrypoint (Phase 4). One command — `install` — prefiguring the
Phase 5 `suite <verb>` surface (ADR-007)."""

from __future__ import annotations

import argparse

from . import steps, users
from .errors import SuiteError


def build_parser():
    p = argparse.ArgumentParser(prog="suite", description="OwnSuite installer + admin CLI.")
    sub = p.add_subparsers(dest="command", required=True)

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
    i.add_argument("--skip-bootstrap", action="store_true")
    i.add_argument("--skip-dns", action="store_true")
    i.add_argument("--skip-propagation", action="store_true")

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
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "user":
            users.run(args)
        else:
            steps.install(args)
    except SuiteError as exc:
        print(f"\nERROR: {exc}")
        return 1
    except KeyboardInterrupt:
        print("\nAborted.")
        return 130
    return 0
