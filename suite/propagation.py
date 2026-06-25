"""DNS propagation gate: don't fire ACME until the records resolve.

Queries a few public resolvers for a *random* probe label under the wildcard
(proving the wildcard resolves, not a stale specific record) plus the apex, and
needs a majority to return the VPS IP. The query function is injectable, so the
quorum logic is unit-tested with a fake; the real one shells out to ``dig`` (a
ubiquitous tool — no DNS-library dependency for a one-line query).
"""

from __future__ import annotations

import secrets
import time

from . import process

PUBLIC_RESOLVERS = ("1.1.1.1", "8.8.8.8", "9.9.9.9")


def dig(resolver_ip, qname, rdtype="A"):
    """Answer values for ``qname`` from one resolver, via ``dig +short``."""
    out = process.run(
        ["dig", f"@{resolver_ip}", "+short", "+time=3", "+tries=1", qname, rdtype],
        capture=True, check=False, step="dig",
    ).stdout
    return {line.strip() for line in out.splitlines() if line.strip()}


def check(domain, ipv4, *, query=dig, resolvers=PUBLIC_RESOLVERS, probe=None):
    """Return (majority_agrees, per-resolver status lines)."""
    domain = domain.strip().rstrip(".")
    probe = probe or f"_ownsuite-{secrets.token_hex(4)}"
    names = (f"{probe}.{domain}", domain)
    lines, agree = [], 0
    for rip in resolvers:
        ok = all(ipv4 in query(rip, n) for n in names)
        agree += ok
        lines.append(f"  {rip}: {'ok' if ok else 'not yet'}")
    return agree * 2 > len(resolvers), lines


def wait(domain, ipv4, *, timeout=900, interval=15, **kw):
    """Poll until a majority agrees or ``timeout`` elapses. Returns True if reached."""
    deadline = time.monotonic() + timeout
    while True:
        reached, lines = check(domain, ipv4, **kw)
        print("\n".join(lines))
        if reached or time.monotonic() >= deadline:
            return reached
        print(f"  not propagated yet; re-checking in {interval}s...")
        time.sleep(interval)
