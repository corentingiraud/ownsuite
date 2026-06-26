import base64
import shutil

import pytest

from suite import mail

openssl = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not on PATH")


@openssl
def test_generate_dkim_private_is_b64_pem():
    b64 = mail.generate_dkim_private_b64()
    pem = base64.b64decode(b64)
    assert pem.startswith(b"-----BEGIN") and b"PRIVATE KEY-----" in pem


@openssl
def test_dkim_public_p_is_stable_b64_der():
    priv = mail.generate_dkim_private_b64()
    p1 = mail.dkim_public_p(priv)
    p2 = mail.dkim_public_p(priv)
    # Deterministic for a given key, valid base64, and a real RSA-2048 SPKI (~294 bytes).
    assert p1 == p2
    assert len(base64.b64decode(p1)) > 250


def test_dkim_public_p_rejects_garbage():
    from suite.errors import SuiteError

    with pytest.raises(SuiteError):
        mail.dkim_public_p("not%%%base64")
