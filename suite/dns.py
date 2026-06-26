"""The exact DNS records to create for a domain. Pure (no I/O), so unit-tested
for an exact domain + IP.

A wildcard ``A`` covers every current and future subdomain (``auth.``, ``docs.``,
...); the apex makes the bare domain resolve; ``AAAA`` only when the server has
public IPv6; ``CAA`` authorises Let's Encrypt. A wildcard *A record* is independent
of a wildcard *certificate* — Phase 4 issues per-host certs over it (ADR-013/019).
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_TTL = 300


@dataclass(frozen=True)
class DnsRecord:
    name: str
    type: str
    value: str
    ttl: int = DEFAULT_TTL


@dataclass(frozen=True)
class MailDns:
    """The mailbox's mail-flow records (Phase 6, ADR-026). Added only when the
    optional mailbox is enabled. ``mail_host`` is the MX target / MTA HELO name
    (covered by the wildcard A); ``spf_include`` authorises the outbound relay;
    ``dkim_public_key`` is the base64 the installer derived from its generated key.
    rDNS/PTR is set at the host, not here (ADR-027)."""

    mail_host: str
    spf_include: str
    dkim_selector: str
    dkim_public_key: str
    dmarc_rua: str = ""


def records(domain, ipv4, ipv6=None, ttl=DEFAULT_TTL, mail=None):
    domain = domain.strip().rstrip(".")
    if not domain:
        raise ValueError("domain must not be empty")
    if not ipv4 and not ipv6:
        raise ValueError("at least one of ipv4/ipv6 is required")
    recs = []
    if ipv4:
        recs += [DnsRecord(f"*.{domain}", "A", ipv4, ttl), DnsRecord(domain, "A", ipv4, ttl)]
    if ipv6:
        recs += [DnsRecord(f"*.{domain}", "AAAA", ipv6, ttl), DnsRecord(domain, "AAAA", ipv6, ttl)]
    recs.append(DnsRecord(domain, "CAA", '0 issue "letsencrypt.org"', ttl))
    if mail:
        recs += mail_records(domain, mail, ttl)
    return recs


def mail_records(domain, mail, ttl=DEFAULT_TTL):
    """MX/SPF/DKIM/DMARC for the mailbox. SPF `include`s the relay (outbound leaves
    the relay's reputable IP, ADR-021); DKIM publishes the installer's public key;
    DMARC defaults to `quarantine`."""
    domain = domain.strip().rstrip(".")
    dmarc = "v=DMARC1; p=quarantine"
    if mail.dmarc_rua:
        dmarc += f"; rua=mailto:{mail.dmarc_rua}"
    return [
        DnsRecord(domain, "MX", f"10 {mail.mail_host}.", ttl),
        DnsRecord(domain, "TXT", f"v=spf1 include:{mail.spf_include} ~all", ttl),
        DnsRecord(
            f"{mail.dkim_selector}._domainkey.{domain}", "TXT",
            f"v=DKIM1; k=rsa; p={mail.dkim_public_key}", ttl,
        ),
        DnsRecord(f"_dmarc.{domain}", "TXT", dmarc, ttl),
    ]


def format_table(recs):
    """Copy-pasteable, column-aligned table (for a registrar's web form)."""
    cols = ("Name", "Type", "Value", "TTL")
    rows = [cols] + [(r.name, r.type, r.value, str(r.ttl)) for r in recs]
    widths = [max(len(row[i]) for row in rows) for i in range(4)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    return "\n".join(fmt.format(*row).rstrip() for row in rows)
