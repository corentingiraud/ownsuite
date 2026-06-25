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


def records(domain, ipv4, ipv6=None, ttl=DEFAULT_TTL):
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
    return recs


def format_table(recs):
    """Copy-pasteable, column-aligned table (for a registrar's web form)."""
    cols = ("Name", "Type", "Value", "TTL")
    rows = [cols] + [(r.name, r.type, r.value, str(r.ttl)) for r in recs]
    widths = [max(len(row[i]) for row in rows) for i in range(4)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    return "\n".join(fmt.format(*row).rstrip() for row in rows)
