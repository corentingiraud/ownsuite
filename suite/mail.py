"""Mailbox helpers (Phase 6, ADR-026): the DKIM signing key.

We chose the *supplied* DKIM model — messages signs outbound with a key we hand it
(`MESSAGES_DKIM_PRIVATE_KEY_B64`) rather than one it generates in its DB, so the
installer can print the public-key DNS record up front. The key is generated once
with `openssl` (the installer already shells out to ssh/kubectl/helmfile, so this
adds no Python dependency) and then carried like the seed: held in the environment
for the run, never written to the repo. Re-export it (or it is regenerated and the
DKIM TXT changes) on the next run.

`MESSAGES_DKIM_PRIVATE_KEY_B64` is base64 of the PEM private key; the DNS `p=` value
is base64 of the DER SubjectPublicKeyInfo, derived from that same private key.
"""

from __future__ import annotations

import base64
import subprocess

from .errors import SuiteError


def generate_dkim_private_b64():
    """Generate an RSA-2048 private key with openssl; return base64(PEM)."""
    priv_pem = _openssl(["openssl", "genrsa", "2048"])
    return base64.b64encode(priv_pem).decode()


def dkim_public_p(private_b64):
    """The DNS `p=` value (base64 DER public key) for a base64(PEM) private key."""
    try:
        priv_pem = base64.b64decode(private_b64)
    except (ValueError, TypeError) as exc:
        raise SuiteError(f"OWNSUITE_MTA_DKIM_PRIVATE_KEY_B64 is not valid base64: {exc}") from exc
    pub_der = _openssl(["openssl", "rsa", "-pubout", "-outform", "DER"], input_bytes=priv_pem)
    return base64.b64encode(pub_der).decode()


def _openssl(argv, input_bytes=None):
    try:
        return subprocess.run(
            argv, input=input_bytes, capture_output=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SuiteError(f"openssl failed ({' '.join(argv)}): {exc}") from exc
