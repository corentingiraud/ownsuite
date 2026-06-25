"""Unit tests for the `suite user` dispatch (suite.users), exercising the verbs
against the in-memory FakeKeycloak — no tunnel, no kubectl, no live cluster."""

from types import SimpleNamespace

import pytest
from test_keycloak import BASE, REALM, FakeKeycloak

from suite import users
from suite.errors import SuiteError
from suite.keycloak import KeycloakAdmin


def _kc(fake):
    return KeycloakAdmin(BASE, REALM, "admin", fake.admin_password, transport=fake)


def _args(action, email, **kw):
    return SimpleNamespace(action=action, email=email,
                           password=kw.get("password"), permanent=kw.get("permanent", False))


def test_add_creates_user_and_sets_temporary_password():
    fake = FakeKeycloak()
    users._dispatch(_args("add", "alice@assoc.org"), _kc(fake))
    [rep] = fake.users.values()
    assert rep["email"] == "alice@assoc.org"
    # default add => temporary password (force reset at first login)
    assert rep["_password"]["temporary"] is True


def test_add_permanent_password():
    fake = FakeKeycloak()
    users._dispatch(_args("add", "bob@assoc.org", permanent=True, password="hunter2"), _kc(fake))
    [rep] = fake.users.values()
    assert rep["_password"] == {"type": "password", "value": "hunter2", "temporary": False}


def test_passwd_requires_existing_user():
    fake = FakeKeycloak()
    with pytest.raises(SuiteError, match="no Keycloak user"):
        users._dispatch(_args("passwd", "ghost@assoc.org"), _kc(fake))


def test_passwd_resets_existing_user():
    fake = FakeKeycloak()
    kc = _kc(fake)
    kc.ensure_user("carol@assoc.org")
    users._dispatch(_args("passwd", "carol@assoc.org", password="newpass"), kc)
    [rep] = fake.users.values()
    assert rep["_password"]["value"] == "newpass"


def test_disable_existing_user():
    fake = FakeKeycloak()
    kc = _kc(fake)
    kc.ensure_user("dan@assoc.org")
    users._dispatch(_args("disable", "dan@assoc.org"), kc)
    [rep] = fake.users.values()
    assert rep["enabled"] is False


def test_disable_requires_existing_user():
    with pytest.raises(SuiteError, match="no Keycloak user"):
        users._dispatch(_args("disable", "ghost@assoc.org"), _kc(FakeKeycloak()))


def test_resolve_password_explicit_vs_generated():
    explicit, generated = users._resolve_password(_args("add", "x@y.org", password="p"))
    assert (explicit, generated) == ("p", False)
    value, generated = users._resolve_password(_args("add", "x@y.org"))
    assert generated is True and len(value) >= 12  # secrets.token_urlsafe(12)
