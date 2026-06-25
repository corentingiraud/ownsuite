"""The `install` pipeline: bare VPS + a domain -> all-in-HTTPS (ADR-018).

Idempotent by construction — every step (helmfile sync, kubectl wait, DNS/TLS
reads, ansible) is safe to repeat, so the replay story is simply re-running
`suite install`; there is no step-resume machinery.
"""

from __future__ import annotations

import contextlib
import os
import shutil

from . import config, dns, ip, propagation, tunnel, verify
from .errors import SuiteError
from .process import run

HELMFILE = "helmfile/helmfile.yaml.gotmpl"
NS = "ownsuite"
REALM = "ownsuite"
CERTS = ("keycloak-tls", "docs-tls")
# OWNSUITE_TLS_ISSUER value per mode; "prod" issues staging first, then this.
PROD_ISSUER = "letsencrypt-http01"
STAGING_ISSUER = "letsencrypt-staging"


def install(args):
    cfg = config.load_env(args.env_file)
    overrides = {
        k: v
        for k, v in (("OWNSUITE_DOMAIN", args.domain), ("OWNSUITE_VPS_SSH", args.ssh))
        if v
    }
    cfg = config.capture(cfg, interactive=not args.non_interactive, overrides=overrides)
    domain = cfg.get("OWNSUITE_DOMAIN")
    if not domain:
        raise SuiteError("OWNSUITE_DOMAIN is required")
    config.write_env(args.env_file, cfg)

    seed = os.environ.get("OWNSUITE_SECRET_SEED")
    if not seed:
        seed = config.generate_seed()
        _seed_banner(seed)

    ssh = cfg.get("OWNSUITE_VPS_SSH", "")
    _preflight(args, ssh)

    if not args.skip_bootstrap:
        print("\n==> Bootstrapping the VPS (ansible)")
        run(["make", "bootstrap"], step="bootstrap")

    if args.tls_mode != "selfsigned" and not args.skip_dns:
        _dns_and_propagation(args, domain, ssh)

    env = {**cfg, "OWNSUITE_SECRET_SEED": seed}
    tunnel_ctx = (
        contextlib.nullcontext()
        if args.no_tunnel or not ssh
        else tunnel.tunnel(ssh)
    )
    with tunnel_ctx:
        if args.tls_mode == "selfsigned":
            _issue(env, "selfsigned")
            _verify(domain, trusted=False)
        else:
            _issue(env, STAGING_ISSUER)
            _verify(domain, trusted=False)  # staging leaf is intentionally untrusted
            if args.tls_mode == "prod":
                _issue(env, PROD_ISSUER)
                _verify(domain, trusted=True)

    print("\n==> Done. OwnSuite is serving over HTTPS.")


def _dns_and_propagation(args, domain, ssh):
    ipv4 = args.public_ip or (ip.detect_over_ssh(ssh, 4) if ssh else None)
    if not ipv4:
        ipv4 = input("VPS public IPv4: ").strip()
    ipv6 = ip.detect_over_ssh(ssh, 6) if ssh else None
    print("\n==> Create these DNS records at your registrar:\n")
    print(dns.format_table(dns.records(domain, ipv4, ipv6)))
    if not args.skip_propagation:
        print("\n==> Waiting for DNS to propagate (before triggering ACME)...")
        if not propagation.wait(domain, ipv4):
            raise SuiteError("DNS did not propagate in time; not triggering ACME")


def _issue(env, issuer):
    print(f"\n==> Syncing the stack with TLS issuer '{issuer}'")
    full = {**env, "OWNSUITE_TLS_ISSUER": issuer}
    try:
        run(["helmfile", "-f", HELMFILE, "sync"], env=full, step="helmfile sync")
    except SuiteError:
        run(["kubectl", "get", "pods", "-A"], check=False)  # diagnostics on failure
        raise
    for cert in CERTS:
        run(
            ["kubectl", "wait", "--for=condition=Ready", f"certificate/{cert}",
             "-n", NS, "--timeout=300s"],
            env=full, step=f"wait {cert}",
        )


def _verify(domain, *, trusted):
    targets = {
        f"https://auth.{domain}/realms/{REALM}/.well-known/openid-configuration": "Keycloak",
        f"https://docs.{domain}/": "Docs",
    }
    failed = []
    for url, name in targets.items():
        ok = verify.https_ok(url, verify=trusted)
        print(f"  {'OK ' if ok else 'FAIL'} {name}: {url}")
        if not ok:
            failed.append(name)
    if failed:
        raise SuiteError(f"HTTPS verification failed for: {', '.join(failed)}")


def _preflight(args, ssh):
    tools = ["helmfile", "kubectl"]
    if not args.skip_bootstrap:
        tools.append("make")
    if not args.no_tunnel and ssh:
        tools.append("ssh")
    if args.tls_mode != "selfsigned" and not args.skip_dns:
        tools.append("dig")
    missing = [t for t in tools if not shutil.which(t)]
    if missing:
        raise SuiteError(f"missing required tools on PATH: {', '.join(missing)}")


def _seed_banner(seed):
    print(
        "\n" + "=" * 70 + "\n"
        "SECRET SEED — store this in your password manager NOW. It is shown once\n"
        "and is NEVER written to the repo. Every credential derives from it; lose\n"
        "it and you must rotate everything (ADR-012).\n\n"
        f"  OWNSUITE_SECRET_SEED={seed}\n\n"
        "Re-run with it exported (export OWNSUITE_SECRET_SEED=...) to resume.\n"
        + "=" * 70
    )
