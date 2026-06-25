"""Per-host HTTPS verification.

The TLS client already verifies the chain against the system trust store, so
that *is* the "is this a real certificate" check — no cert parsing or issuer
classification needed. ``verify=True`` (production) only succeeds with a publicly
trusted cert; ``verify=False`` (self-signed / Let's Encrypt staging) just confirms
the host answers over TLS.
"""

from __future__ import annotations

import ssl
import urllib.error
import urllib.request


def https_ok(url, *, verify=True, timeout=10):
    ctx = None
    if not verify:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(url, timeout=timeout, context=ctx) as resp:
            return resp.status < 500
    except urllib.error.HTTPError as exc:
        return exc.code < 500  # served (e.g. 401/403) — TLS + routing are fine
    except (urllib.error.URLError, ssl.SSLError, OSError):
        return False
