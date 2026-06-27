"""The `install` pipeline: bare server + a domain -> all-in-HTTPS (ADR-018).

Idempotent by construction — every step (helmfile sync, kubectl wait, DNS/TLS
reads, ansible) is safe to repeat, so the replay story is simply re-running
`suite install`; there is no step-resume machinery.
"""

from __future__ import annotations

import contextlib
import os
import shutil

from . import config, dns, ip, mail, propagation, tunnel, verify
from .errors import SuiteError
from .process import run
from .status import enabled_apps

HELMFILE = "helmfile/helmfile.yaml.gotmpl"
NS = "ownsuite"
REALM = "ownsuite"
# OWNSUITE_TLS_ISSUER value per mode; "prod" issues staging first, then this.
PROD_ISSUER = "letsencrypt-http01"
STAGING_ISSUER = "letsencrypt-staging"


def install(args):
    cfg = config.load_env(args.env_file)
    overrides = {
        k: v
        for k, v in (("OWNSUITE_DOMAIN", args.domain), ("OWNSUITE_SERVER_SSH", args.ssh))
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

    ssh = cfg.get("OWNSUITE_SERVER_SSH", "")
    _preflight(args, ssh)

    # The optional mailbox (ADR-026) needs a DKIM key before we print the DNS records.
    # Generate it once and carry it like the seed (in env, never written to .env).
    mail_dns = _ensure_mail(cfg, domain) if _mailbox_enabled(cfg) else None

    if not args.skip_bootstrap:
        print("\n==> Bootstrapping the server (ansible)")
        run(["make", "bootstrap"], step="bootstrap")

    if args.tls_mode != "selfsigned" and not args.skip_dns:
        _dns_and_propagation(args, domain, ssh, mail_dns)

    env = {**cfg, "OWNSUITE_SECRET_SEED": seed}
    # Which apps the operator turned on (env > .env > defaults — all off by default,
    # ADR-035). Keycloak is always issued/verified; each enabled app is checked at its
    # own cert + public HTTPS host, so a platform-only install never waits on an app.
    enabled = enabled_apps(cfg)
    tunnel_ctx = (
        contextlib.nullcontext()
        if args.no_tunnel or not ssh
        else tunnel.tunnel(ssh)
    )
    with tunnel_ctx:
        if args.tls_mode == "selfsigned":
            _issue(env, "selfsigned", enabled)
            _verify(domain, enabled, trusted=False)
        else:
            _issue(env, STAGING_ISSUER, enabled)
            _verify(domain, enabled, trusted=False)  # staging leaf is intentionally untrusted
            if args.tls_mode == "prod":
                _issue(env, PROD_ISSUER, enabled)
                _verify(domain, enabled, trusted=True)

    print("\n==> Done. OwnSuite is serving over HTTPS.")


def _dns_and_propagation(args, domain, ssh, mail_dns=None):
    ipv4 = args.public_ip or (ip.detect_over_ssh(ssh, 4) if ssh else None)
    if not ipv4:
        ipv4 = input("Server public IPv4: ").strip()
    ipv6 = ip.detect_over_ssh(ssh, 6) if ssh else None
    print("\n==> Create these DNS records at your registrar:\n")
    print(dns.format_table(dns.records(domain, ipv4, ipv6, mail=mail_dns)))
    if mail_dns:
        _mail_manual_steps(ipv4, mail_dns.mail_host)
    if not args.skip_propagation:
        print("\n==> Waiting for DNS to propagate (before triggering ACME)...")
        if not propagation.wait(domain, ipv4):
            raise SuiteError("DNS did not propagate in time; not triggering ACME")


def _mailbox_enabled(cfg):
    return cfg.get("OWNSUITE_APP_MESSAGES", "false").lower() == "true"


def _ensure_mail(cfg, domain):
    """Build the mailbox's MailDns. Ensure a DKIM key exists in the environment
    (generate one if the operator hasn't supplied OWNSUITE_MTA_DKIM_PRIVATE_KEY_B64),
    so `helmfile sync` hands the same key to mta-out and the DKIM TXT we print matches.
    """
    private_b64 = os.environ.get("OWNSUITE_MTA_DKIM_PRIVATE_KEY_B64")
    if not private_b64:
        private_b64 = mail.generate_dkim_private_b64()
        os.environ["OWNSUITE_MTA_DKIM_PRIVATE_KEY_B64"] = private_b64
        _dkim_banner(private_b64)
    return dns.MailDns(
        mail_host=f"mail.{domain}",
        spf_include=cfg.get("OWNSUITE_MTA_SPF_INCLUDE", "spf.infomaniak.ch"),
        dkim_selector=cfg.get("OWNSUITE_MTA_DKIM_SELECTOR", "ownsuite"),
        dkim_public_key=mail.dkim_public_p(private_b64),
        dmarc_rua=cfg.get("OWNSUITE_MTA_DMARC_RUA", ""),
    )


def _mail_manual_steps(ipv4, mail_host):
    print(
        "\n==> Mailbox — two manual steps DNS cannot cover (ADR-027):\n"
        f"  1. rDNS / PTR: set the reverse DNS for {ipv4} to {mail_host} at your\n"
        "     server/VPS provider (mail.* must resolve back to the IP).\n"
        "  2. Confirm your provider allows INBOUND TCP port 25 (outbound 25 is\n"
        "     usually blocked — fine, we relay outbound via the relay's 587).\n"
        "  Also export the relay account before sync (never written to .env):\n"
        "     export OWNSUITE_MTA_RELAY_USERNAME=... OWNSUITE_MTA_RELAY_PASSWORD=..."
    )


def _dkim_banner(private_b64):
    print(
        "\n" + "=" * 70 + "\n"
        "DKIM KEY generated for the mailbox. Store it in your password manager and\n"
        "re-export it on every run (like the seed) — otherwise the DKIM TXT changes\n"
        "and outbound mail fails DKIM until DNS catches up (ADR-026).\n\n"
        f"  export OWNSUITE_MTA_DKIM_PRIVATE_KEY_B64={private_b64}\n"
        + "=" * 70
    )


def _certs(enabled):
    """Certificates to wait on: Keycloak always, plus `<app>-tls` per enabled app."""
    return ["keycloak-tls", *(f"{app}-tls" for app in enabled)]


def _issue(env, issuer, enabled):
    print(f"\n==> Syncing the stack with TLS issuer '{issuer}'")
    full = {**env, "OWNSUITE_TLS_ISSUER": issuer}
    try:
        run(["helmfile", "-f", HELMFILE, "sync"], env=full, step="helmfile sync")
    except SuiteError:
        run(["kubectl", "get", "pods", "-A"], check=False)  # diagnostics on failure
        raise
    for cert in _certs(enabled):
        run(
            ["kubectl", "wait", "--for=condition=Ready", f"certificate/{cert}",
             "-n", NS, "--timeout=300s"],
            env=full, step=f"wait {cert}",
        )


def _verify(domain, enabled, *, trusted):
    # Keycloak underpins every app's SSO, so it is always checked; each enabled app is
    # verified at its public HTTPS host (same shape as upgrade._health_check).
    targets = {"Keycloak": f"https://auth.{domain}/realms/{REALM}/.well-known/openid-configuration"}
    for app in enabled:
        targets[app.capitalize()] = f"https://{app}.{domain}/"
    failed = []
    for name, url in targets.items():
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
