"""`suite info` — URLs, admin credentials, DNS records (issue #82).

Everything is derived (seed, suite.yaml, machine state) — nothing secret is read
from the cluster, and no tunnel is needed. The Keycloak admin password is
re-derived from the seed exactly like the chart derived it (ADR-012).
"""

from __future__ import annotations

import os

from . import config, ip, spec, steps
from .users import ADMIN_USER


def run_info(args):
    ctx = spec.load_context()
    domain = ctx.spec.domain
    enabled = ctx.spec.enabled_apps()

    print(f"\nOwnSuite — {domain}")
    print("=" * 40)
    print("\nURLs:")
    print(f"  auth       https://auth.{domain}/  (SSO admin console)")
    for app in enabled:
        print(f"  {app:<10} https://{app}.{domain}/")
    if not enabled:
        print("  (no apps enabled — add them under `apps:` in suite.yaml)")

    print("\nAdmin credentials (Keycloak, derived from the seed — ADR-012):")
    seed = (os.environ.get("OWNSUITE_SECRET_SEED") or "").strip()
    if seed:
        print(f"  user       {ADMIN_USER}")
        print(f"  password   {config.derive_secret(seed, 'keycloak-admin')}")
    else:
        print("  export OWNSUITE_SECRET_SEED to display them.")

    if ctx.ssh:
        ipv4 = ip.detect_over_ssh(ctx.ssh, 4)
        ipv6 = ip.detect_over_ssh(ctx.ssh, 6)
        if ipv4 or ipv6:
            # Mail DNS (DKIM TXT) needs the key from the state; plain records don't.
            steps.emit_dns(domain, ipv4, ipv6, None)
            if "messages" in enabled:
                print("\n  (mailbox MX/SPF/DKIM/DMARC records: see `suite plan`)")
        else:
            print(f"\nDNS: could not detect the server IP over SSH ({ctx.ssh}).")
    else:
        print("\nDNS: no server SSH target known — records need the server IP "
              "(`suite plan` shows them once provisioned).")
