"""DNS + TLS building blocks for `suite apply` (ADR-018 lineage, ADR-042).

The guided `install` pipeline became `suite init` + `suite apply`; what remains
here are its reusable steps: detect the server IP, emit the DNS records/zone
file, run one full helmfile pass pinned to a TLS issuer and wait for the
certificates, and verify Keycloak + each enabled app over HTTPS.
"""

from __future__ import annotations

from pathlib import Path

from . import dns, ip, verify
from .errors import SuiteError
from .process import run

HELMFILE = "helmfile/helmfile.yaml.gotmpl"
NS = "ownsuite"
REALM = "ownsuite"
# OWNSUITE_TLS_ISSUER value per TLS mode; "prod" issues staging first (ADR-019).
PROD_ISSUER = "letsencrypt-http01"
STAGING_ISSUER = "letsencrypt-staging"


def detect_ipv4(ssh):
    ipv4 = ip.detect_over_ssh(ssh, 4) if ssh else None
    if not ipv4:
        ipv4 = input("Server public IPv4: ").strip()
    return ipv4


def emit_dns(domain, ipv4, ipv6, mail_dns, zone_path=None):
    """Print the copy-paste record table — and write the BIND zone file when a
    path is given — both from one record set, so they never drift."""
    recs = dns.records(domain, ipv4, ipv6, mail=mail_dns)
    print("\n==> Create these DNS records at your registrar:\n")
    print(dns.format_table(recs))
    if zone_path:
        Path(zone_path).write_text(dns.format_zone(recs, domain))
        print(f"\n==> BIND zone file written to {zone_path} (import it at your registrar).")
    if mail_dns:
        mail_manual_steps(ipv4, mail_dns.mail_host)


def mail_manual_steps(ipv4, mail_host):
    print(
        "\n==> Mailbox — two manual steps DNS cannot cover (ADR-027):\n"
        f"  1. rDNS / PTR: set the reverse DNS for {ipv4} to {mail_host} at your\n"
        "     server/VPS provider (mail.* must resolve back to the IP).\n"
        "  2. Confirm your provider allows INBOUND TCP port 25 (outbound 25 is\n"
        "     usually blocked — fine, we relay outbound via the relay's 587).\n"
        "  Unless provisioning stored the relay account in the machine state,\n"
        "  export it before applying:\n"
        "     export OWNSUITE_MTA_RELAY_USERNAME=... OWNSUITE_MTA_RELAY_PASSWORD=..."
    )


# Most apps expose one ingress cert named <app>-tls; tchap (ess-helm
# matrix-stack) ships several component ingresses with its own secret names.
TCHAP_CERTS = ("synapse-tls", "mas-tls", "tchap-web-tls", "well-known-tls")


def certs(enabled):
    """Certs to wait on: Keycloak always, plus each app's ingress cert(s)."""
    out = ["keycloak-tls"]
    for app in enabled:
        out += TCHAP_CERTS if app == "tchap" else [f"{app}-tls"]
    return out


def issue(env, issuer, enabled, *, verb="apply"):
    """One full helmfile pass pinned to `issuer`, then wait for the certificates.
    The issuer is stomped into the env so nothing ambient can downgrade it."""
    print(f"\n==> Applying the stack with TLS issuer '{issuer}' (helmfile {verb})")
    full = {**env, "OWNSUITE_TLS_ISSUER": issuer}
    # On a fresh cluster the operators (cert-manager, CNPG) install their CRDs in the
    # same pass that later releases' CRs (ClusterIssuer, Cluster) depend on. `apply`
    # helm-diffs every release up front, which fails to map those not-yet-installed
    # CRDs; --skip-diff-on-install skips the diff for new releases so `needs` ordering
    # installs the CRDs first. Only valid for `apply` (not `sync`).
    extra = ["--skip-diff-on-install"] if verb == "apply" else []
    try:
        run(["helmfile", "-f", HELMFILE, verb, *extra], env=full, step=f"helmfile {verb}")
    except SuiteError:
        run(["kubectl", "get", "pods", "-A"], check=False)  # diagnostics on failure
        raise
    for cert in certs(enabled):
        run(
            ["kubectl", "wait", "--for=condition=Ready", f"certificate/{cert}",
             "-n", NS, "--timeout=300s"],
            env=full, step=f"wait {cert}",
        )


def verify_https(domain, enabled, *, trusted):
    """OK/FAIL line per host; returns the hosts that failed. Keycloak (`auth`)
    underpins every app's SSO, so it is always checked. `trusted=False` accepts
    self-signed / LE-staging leaves and only proves TLS + routing."""
    targets = {
        "auth": f"https://auth.{domain}/realms/{REALM}/.well-known/openid-configuration",
    }
    for app in enabled:
        targets[app] = f"https://{app}.{domain}/"
    failed = []
    for host, url in targets.items():
        ok = verify.https_ok(url, verify=trusted)
        print(f"  {'OK  ' if ok else 'FAIL'} {host}: {url}")
        if not ok:
            failed.append(host)
    return failed
