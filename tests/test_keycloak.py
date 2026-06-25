"""Unit tests for the Keycloak admin client (suite.keycloak), with the admin REST
API mocked by an in-memory fake transport — no live cluster, matching the
injectable-boundary style of test_propagation."""

import json
import urllib.parse

import pytest

from suite.errors import SuiteError
from suite.keycloak import KeycloakAdmin

BASE, REALM, ADMIN_PW = "http://kc.local", "ownsuite", "admin-pw"


class FakeKeycloak:
    """A tiny in-memory Keycloak admin API: token + the user endpoints we call.

    Usable as the KeycloakAdmin `transport`: (method, url, headers, data) ->
    (status, body, lower-cased headers). Records calls for assertions.
    """

    def __init__(self, *, admin_password=ADMIN_PW):
        self.admin_password = admin_password
        self.users = {}  # id -> representation
        self._next_id = 1
        self.calls = []

    def __call__(self, method, url, *, headers=None, data=None, timeout=30):
        self.calls.append((method, url))
        if url.endswith("/realms/master/protocol/openid-connect/token"):
            params = urllib.parse.parse_qs(data.decode())
            if params.get("password", [""])[0] != self.admin_password:
                return 401, '{"error":"invalid_grant"}', {}
            return 200, json.dumps({"access_token": "fake-token"}), {}

        prefix = f"/admin/realms/{REALM}"
        assert prefix in url, url
        assert (headers or {}).get("Authorization") == "Bearer fake-token"
        path = url.split(prefix, 1)[1]
        body = json.loads(data.decode()) if data else None

        if method == "GET" and path.startswith("/users?"):
            email = urllib.parse.parse_qs(path.split("?", 1)[1]).get("email", [""])[0]
            return 200, json.dumps([u for u in self.users.values() if u["email"] == email]), {}
        if method == "POST" and path == "/users":
            if any(u["email"] == body["email"] for u in self.users.values()):
                return 409, '{"errorMessage":"User exists"}', {}
            uid = str(self._next_id)
            self._next_id += 1
            self.users[uid] = {"id": uid, **body}
            return 201, "", {"location": f"{BASE}{prefix}/users/{uid}"}
        if method == "PUT" and path.startswith("/users/"):
            rest = path[len("/users/"):]
            if rest.endswith("/reset-password"):
                self.users[rest[: -len("/reset-password")]]["_password"] = body
            else:
                self.users[rest].update(body)
            return 204, "", {}
        return 404, "{}", {}


def admin(fake, *, password=ADMIN_PW):
    return KeycloakAdmin(BASE, REALM, "admin", password, transport=fake)


def test_add_creates_verified_enabled_user():
    fake = FakeKeycloak()
    user_id, created = admin(fake).ensure_user("alice@assoc.org")
    assert created is True
    rep = fake.users[user_id]
    assert rep["email"] == "alice@assoc.org"
    assert rep["username"] == "alice@assoc.org"
    assert rep["enabled"] is True and rep["emailVerified"] is True
    # Keycloak's user profile requires first/last name, else a direct-grant login is
    # refused ("Account is not fully set up"); default them to the email local part.
    assert rep["firstName"] == "alice" and rep["lastName"] == "alice"


def test_create_user_honors_explicit_names():
    fake = FakeKeycloak()
    admin(fake).create_user("bob@assoc.org", first_name="Bob", last_name="Smith")
    [rep] = fake.users.values()
    assert rep["firstName"] == "Bob" and rep["lastName"] == "Smith"


def test_ensure_user_is_idempotent():
    fake = FakeKeycloak()
    kc = admin(fake)
    id1, c1 = kc.ensure_user("bob@assoc.org")
    id2, c2 = kc.ensure_user("bob@assoc.org")
    assert (c1, c2) == (True, False)
    assert id1 == id2
    assert len(fake.users) == 1  # no duplicate created


def test_find_user_absent_returns_none():
    assert admin(FakeKeycloak()).find_user("ghost@assoc.org") is None


def test_create_user_resolves_id_from_location_header():
    fake = FakeKeycloak()
    user_id = admin(fake).create_user("carol@assoc.org")
    assert user_id in fake.users


def test_set_password_sends_temporary_flag():
    fake = FakeKeycloak()
    kc = admin(fake)
    uid, _ = kc.ensure_user("dan@assoc.org")
    kc.set_password(uid, "s3cret", temporary=True)
    assert fake.users[uid]["_password"] == {
        "type": "password", "value": "s3cret", "temporary": True,
    }


def test_disable_sets_enabled_false():
    fake = FakeKeycloak()
    kc = admin(fake)
    uid, _ = kc.ensure_user("erin@assoc.org")
    kc.set_enabled(uid, False)
    assert fake.users[uid]["enabled"] is False


def test_bad_admin_password_raises():
    fake = FakeKeycloak(admin_password="correct")
    kc = admin(fake, password="wrong")
    with pytest.raises(SuiteError, match="authentication failed"):
        kc.find_user("alice@assoc.org")
