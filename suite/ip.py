"""Detect the server public IP for the DNS records.

Read the host's bound global address over SSH (``ip -json addr show scope
global``), not an outbound echo service, so a NATed server reports the IP clients
reach. Parsing is pure (unit-tested against captured ``ip -json``); detection
shells out and the caller falls back to the inventory / an explicit override.
"""

from __future__ import annotations

import ipaddress
import json

from . import process


def parse_ip_json(stdout, family):
    """First global ``family`` (4 or 6) public address from ``ip -json`` output."""
    want = "inet" if family == 4 else "inet6"
    try:
        data = json.loads(stdout or "[]")
    except json.JSONDecodeError:
        return None
    for iface in data:
        for ai in iface.get("addr_info", []):
            addr = ai.get("local")
            if ai.get("family") == want and ai.get("scope") == "global" and _public(addr):
                return addr
    return None


def _public(addr):
    try:
        ip = ipaddress.ip_address(addr)
    except (ValueError, TypeError):
        return False
    return not (ip.is_private or ip.is_loopback or ip.is_link_local)


def detect_over_ssh(ssh_target, family, *, ssh_argv=("ssh", "-o", "BatchMode=yes")):
    flag = "-4" if family == 4 else "-6"
    argv = [*ssh_argv, ssh_target, "ip", flag, "-json", "addr", "show", "scope", "global"]
    proc = process.run(argv, capture=True, check=False, step="detect-ip")
    return parse_ip_json(proc.stdout, family) if proc.returncode == 0 else None
