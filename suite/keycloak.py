"""Keycloak admin REST client for the `suite user` verbs (Phase 5).

Talks the Keycloak admin REST API over the in-cluster HTTP service, reached through
the existing SSH tunnel + a kubectl port-forward (ADR-014) — admin traffic stays
private, never the public auth endpoint. The HTTP transport is injectable, so the
create/disable/reset logic is unit-tested with a fake (no live Keycloak); the real
transport uses urllib (no HTTP-client dependency, ADR-018).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from .errors import SuiteError


def urllib_transport(method, url, *, headers=None, data=None, timeout=30):
    """One HTTP round-trip. Returns (status, body_text, headers) with lower-cased
    header keys. HTTP error responses are returned (not raised) so callers see the
    status; only transport-level failures propagate."""
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body, status, hdrs = resp.read().decode(), resp.status, resp.headers
    except urllib.error.HTTPError as exc:
        body, status, hdrs = exc.read().decode(), exc.code, exc.headers
    except urllib.error.URLError as exc:
        raise SuiteError(f"cannot reach Keycloak at {url}: {exc.reason}") from exc
    return status, body, {k.lower(): v for k, v in hdrs.items()}


class KeycloakAdmin:
    """Minimal admin client: token + the handful of user operations we need."""

    def __init__(
        self, base_url, realm, username, password,
        *, admin_realm="master", client_id="admin-cli", transport=urllib_transport,
    ):
        self.base = base_url.rstrip("/")
        self.realm = realm
        self.username = username
        self.password = password
        self.admin_realm = admin_realm
        self.client_id = client_id
        self._transport = transport
        self._token_cache = None

    # --- low level --------------------------------------------------------
    def _token(self):
        if self._token_cache:
            return self._token_cache
        body = urllib.parse.urlencode({
            "grant_type": "password",
            "client_id": self.client_id,
            "username": self.username,
            "password": self.password,
        }).encode()
        status, text, _ = self._transport(
            "POST",
            f"{self.base}/realms/{self.admin_realm}/protocol/openid-connect/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=body,
        )
        if status != 200:
            raise SuiteError(f"Keycloak admin authentication failed (status {status})")
        self._token_cache = json.loads(text)["access_token"]
        return self._token_cache

    def _api(self, method, path, *, data=None):
        headers = {"Authorization": f"Bearer {self._token()}"}
        body = None
        if data is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(data).encode()
        status, text, resp_headers = self._transport(
            method, f"{self.base}/admin/realms/{self.realm}{path}",
            headers=headers, data=body,
        )
        if status >= 400:
            raise SuiteError(f"Keycloak {method} {path} failed (status {status}): {text[:200]}")
        return status, text, resp_headers

    # --- user operations --------------------------------------------------
    def find_user(self, email):
        """Return the user representation for an exact email, or None."""
        query = urllib.parse.urlencode({"email": email, "exact": "true"})
        _, text, _ = self._api("GET", f"/users?{query}")
        for user in json.loads(text):
            if (user.get("email") or "").lower() == email.lower():
                return user
        return None

    def create_user(self, email):
        """Create a user (username = email, email-verified) and return its id."""
        _, _, headers = self._api("POST", "/users", data={
            "username": email,
            "email": email,
            "enabled": True,
            "emailVerified": True,
        })
        location = headers.get("location")
        if location:
            return location.rstrip("/").rsplit("/", 1)[-1]
        # Some Keycloak versions omit Location; fall back to a lookup.
        user = self.find_user(email)
        if not user:
            raise SuiteError(f"created {email} but could not resolve its id")
        return user["id"]

    def ensure_user(self, email):
        """Idempotent create-or-find. Returns (user_id, created)."""
        existing = self.find_user(email)
        if existing:
            return existing["id"], False
        return self.create_user(email), True

    def set_enabled(self, user_id, enabled):
        self._api("PUT", f"/users/{user_id}", data={"enabled": enabled})

    def set_password(self, user_id, password, *, temporary):
        self._api("PUT", f"/users/{user_id}/reset-password", data={
            "type": "password", "value": password, "temporary": temporary,
        })
