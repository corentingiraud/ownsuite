"""`suite` CLI entrypoint (Phase 4). One command — `install` — prefiguring the
Phase 5 `suite <verb>` surface (ADR-007)."""

from __future__ import annotations

import argparse

from . import steps
from .errors import SuiteError


def build_parser():
    p = argparse.ArgumentParser(prog="suite", description="OwnSuite installer (Phase 4).")
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
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        steps.install(args)
    except SuiteError as exc:
        print(f"\nERROR: {exc}")
        return 1
    except KeyboardInterrupt:
        print("\nAborted.")
        return 130
    return 0
