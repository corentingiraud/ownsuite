"""Platform + installer + backup/restore definition-of-done for OwnSuite.

Run against a live cluster after `suite install` / restore (see run-e2e.sh). Asserts
the shared infrastructure (Phase 1), the object store, and that the backup -> destroy
-> restore cycle preserves all three storage classes (ADR-006). The per-app boot DoD
lives in test_apps.py — this module no longer asserts any application; it keeps a few
shared token/HTTP helpers that test_apps imports.

Each test shells out to kubectl/curl using the ambient KUBECONFIG, so there is no
extra Python dependency beyond pytest.
"""

import base64
import hashlib
import json
import os
import subprocess
import time

import pytest

NAMESPACE = "ownsuite"
REALM = "ownsuite"
DOMAIN = os.environ.get("OWNSUITE_DOMAIN", "ownsuite.localhost")
AUTH_HOST = f"auth.{DOMAIN}"

# A user created through the `suite user` CLI (run by run-e2e.sh before the pre-stage).
# Created at runtime via the Keycloak admin REST API — it is in no declarative realm
# import — so its survival after restore is the genuine proof of Postgres PITR.
CLI_USER = os.environ.get("OWNSUITE_E2E_USER", "")
CLI_USER_PW = os.environ.get("OWNSUITE_E2E_USER_PW", "")

SECRET_SEED = os.environ.get("OWNSUITE_SECRET_SEED")
GARAGE_MODE = os.environ.get("OWNSUITE_OBJECT_STORAGE_MODE", "external") == "garage"
SEED_TEST_USER = os.environ.get("OWNSUITE_KC_SEED_TEST_USER", "false").lower() == "true"
DOCS_BUCKET = os.environ.get("OWNSUITE_S3_BUCKET", "docs-media-storage")

# Test stage (set by run-e2e.sh): "pre" runs the platform + object-store DoD;
# "post-restore" re-asserts infra health and proves the Keycloak user survived the
# backup -> destroy -> restore cycle (ADR-006). The media object (object-copy) and the
# PVC document survival are asserted by run-e2e.sh's own shell steps.
E2E_STAGE = os.environ.get("OWNSUITE_E2E_STAGE", "pre")
POST_RESTORE_ONLY = pytest.mark.skipif(
    E2E_STAGE != "post-restore", reason="runs only after restore (survival check)"
)


def docs_user_token():
    """Mint an access token for the seeded Keycloak user (direct-access grant)."""
    client_secret = derive_secret("docs-oidc")
    password = derive_secret("kc-test-user")
    token_url = f"https://{AUTH_HOST}/realms/{REALM}/protocol/openid-connect/token"
    out = curl(
        AUTH_HOST, token_url,
        "--data-urlencode", "grant_type=password",
        "--data-urlencode", "client_id=docs",
        "--data-urlencode", f"client_secret={client_secret}",
        "--data-urlencode", "username=docs-tester",
        "--data-urlencode", f"password={password}",
        "--data-urlencode", "scope=openid email",
    )
    return json.loads(out)["access_token"]


def derive_secret(secret_id, length=32):
    """Mirror the chart helper: sha256sum("<seed>:<id>") truncated (ADR-012)."""
    digest = hashlib.sha256(f"{SECRET_SEED}:{secret_id}".encode()).hexdigest()
    return digest[:length]


def password_token(client_id, username, password):
    """Mint an access token via the direct-access (password) grant for any app's
    OIDC client (its secret is derived from the `<clientId>-oidc` id, ADR-012)."""
    client_secret = derive_secret(f"{client_id}-oidc")
    token_url = f"https://{AUTH_HOST}/realms/{REALM}/protocol/openid-connect/token"
    out = curl(
        AUTH_HOST, token_url,
        "--data-urlencode", "grant_type=password",
        "--data-urlencode", f"client_id={client_id}",
        "--data-urlencode", f"client_secret={client_secret}",
        "--data-urlencode", f"username={username}",
        "--data-urlencode", f"password={password}",
        "--data-urlencode", "scope=openid email",
    )
    return json.loads(out)["access_token"]


def _secret_value(secret, key):
    """Read one key from a namespace Secret (base64-decoded)."""
    out = kubectl(
        "-n", NAMESPACE, "get", "secret", secret, "-o", f"jsonpath={{.data.{key}}}"
    ).stdout.strip()
    return base64.b64decode(out).decode()


def keycloak_admin_token():
    """Mint a master-realm admin token (admin-cli) — the same path `suite user` uses.

    Credentials come from the live keycloak-admin Secret, so this works regardless of
    which apps are enabled: no app OIDC client is involved.
    """
    user = _secret_value("keycloak-admin", "username")
    password = _secret_value("keycloak-admin", "password")
    token_url = f"https://{AUTH_HOST}/realms/master/protocol/openid-connect/token"
    out = curl(
        AUTH_HOST, token_url,
        "--data-urlencode", "grant_type=password",
        "--data-urlencode", "client_id=admin-cli",
        "--data-urlencode", f"username={user}",
        "--data-urlencode", f"password={password}",
    )
    return json.loads(out)["access_token"]


def curl(host, url, *args):
    """curl through Traefik, resolving <host> to the local loadbalancer (k3d)."""
    return subprocess.run(
        ["curl", "-fksS", "--resolve", f"{host}:443:127.0.0.1", *args, url],
        capture_output=True, text=True, check=True,
    ).stdout


def kubectl(*args, check=True):
    return subprocess.run(
        ["kubectl", *args], capture_output=True, text=True, check=check
    )


def retry(fn, attempts=40, delay=3):
    """Retry fn() until it stops raising (async reconciliation can lag sync)."""
    last = None
    for _ in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - re-raised after the loop
            last = exc
            time.sleep(delay)
    raise last


def test_namespaces_exist():
    out = kubectl("get", "ns", "-o", "jsonpath={.items[*].metadata.name}").stdout.split()
    for ns in ("cert-manager", "cnpg-system", NAMESPACE):
        assert ns in out, f"namespace {ns} missing"


def test_cert_manager_ready():
    deps = json.loads(kubectl("-n", "cert-manager", "get", "deploy", "-o", "json").stdout)["items"]
    assert deps, "no cert-manager deployments found"
    for d in deps:
        name = d["metadata"]["name"]
        assert d["status"].get("availableReplicas", 0) >= 1, f"{name} not available"


def test_selfsigned_issuer_ready():
    # The self-signed ClusterIssuer is what CI/dev uses; the Let's Encrypt issuer
    # is created only in production (it registers a real ACME account), so it is
    # intentionally absent here.
    out = kubectl(
        "get", "clusterissuer", "selfsigned",
        "-o", 'jsonpath={.status.conditions[?(@.type=="Ready")].status}',
    ).stdout.strip()
    assert out == "True", f"selfsigned ClusterIssuer not Ready ({out!r})"


def test_cnpg_cluster_healthy():
    phase = kubectl(
        "-n", NAMESPACE, "get", "cluster", "ownsuite-pg", "-o", "jsonpath={.status.phase}"
    ).stdout
    assert "healthy" in phase.lower(), f"CNPG cluster phase: {phase!r}"


def test_keycloak_database_applied():
    applied = kubectl(
        "-n", NAMESPACE, "get", "database", "keycloak", "-o", "jsonpath={.status.applied}"
    ).stdout.strip()
    assert applied == "true", f"Database keycloak not applied ({applied!r})"


def test_valkey_running_with_auth():
    pods = json.loads(kubectl("-n", NAMESPACE, "get", "pods", "-o", "json").stdout)["items"]
    valkey = [p for p in pods if p["metadata"]["name"].startswith("valkey")]
    assert valkey, "no valkey pod found"
    assert any(p["status"]["phase"] == "Running" for p in valkey), "valkey not Running"
    # Prove requirepass is active: an unauthenticated PING must be refused.
    pod = valkey[0]["metadata"]["name"]
    res = kubectl("-n", NAMESPACE, "exec", pod, "--",
                  "valkey-cli", "ping", check=False)
    assert "NOAUTH" in (res.stdout + res.stderr), \
        f"valkey accepted an unauthenticated command: {res.stdout + res.stderr!r}"


def test_keycloak_pod_ready():
    out = kubectl(
        "-n", NAMESPACE, "get", "pods", "-l", "app.kubernetes.io/name=keycloakx",
        "-o", 'jsonpath={.items[*].status.conditions[?(@.type=="Ready")].status}',
    ).stdout
    assert "True" in out, f"Keycloak pod not Ready ({out!r})"


def test_keycloak_tls_certificate_issued():
    """cert-manager issued the Keycloak certificate (end-to-end TLS plumbing)."""
    def check():
        kubectl("-n", NAMESPACE, "get", "secret", "keycloak-tls")
    retry(check, attempts=40, delay=3)


def test_keycloak_reachable_over_https():
    """The Phase 1 DoD: Keycloak answers over HTTPS through Traefik."""
    url = f"https://auth.{DOMAIN}/realms/{REALM}/.well-known/openid-configuration"

    def fetch():
        out = subprocess.run(
            ["curl", "-fksS", "--resolve", f"auth.{DOMAIN}:443:127.0.0.1", url],
            capture_output=True, text=True, check=True,
        ).stdout
        data = json.loads(out)
        assert data["issuer"].endswith(f"/realms/{REALM}"), data.get("issuer")
        return data

    retry(fetch, attempts=40, delay=3)


# --- Object store (ADR-015) -------------------------------------------------
# run-e2e.sh keeps Docs enabled SOLELY to provide a primary object bucket for the
# object-copy backup/restore DoD (ADR-030) — not to assert the Docs app, whose boot
# DoD lives in test_apps.py. This proves the store + that bucket are up: the fixture
# the backup -> restore cycle seeds, copies off-site, and reads back lands here.


@pytest.mark.skipif(not GARAGE_MODE, reason="object storage is not in garage mode")
def test_garage_running_and_bucket_ready():
    """Garage is up and the bootstrap Job created the primary media bucket (ADR-015)."""
    pods = json.loads(kubectl("-n", NAMESPACE, "get", "pods",
                              "-l", "app.kubernetes.io/name=garage", "-o", "json").stdout)["items"]
    assert any(p["status"]["phase"] == "Running" for p in pods), "no Running garage pod"

    def bucket_exists():
        res = kubectl("-n", NAMESPACE, "exec", "garage-0", "-c", "garage", "--",
                      "/garage", "bucket", "info", DOCS_BUCKET, check=False)
        assert res.returncode == 0, f"bucket {DOCS_BUCKET} missing: {res.stdout + res.stderr}"

    retry(bucket_exists)


# --- Phase 3: backups & tested restore (ADR-006, ADR-017) -------------------


@POST_RESTORE_ONLY
@pytest.mark.skipif(
    not CLI_USER,
    reason="needs a CLI-created Keycloak user (OWNSUITE_E2E_USER)",
)
def test_restore_preserves_keycloak_user():
    """The backup/restore definition of done (Postgres storage class): after
    backup -> destroy -> restore, the user created at runtime via `suite user add`
    is still in the realm — proving the `keycloak` database recovered via CNPG PITR.

    App-agnostic by design: the user is looked up through the Keycloak admin REST API
    (the same path `suite user` uses), so this does not depend on any app's OIDC
    client. It is also a genuine PITR proof: the CLI user is created at runtime and is
    in no declarative realm import, so its presence cannot come from a re-sync.

    The other two storage classes are proven by run-e2e.sh's own shell steps: the
    media object (rclone object-copy, ADR-030) is read back from the primary bucket,
    and the PVC document (pvc_backup_roundtrip, ADR-032) survives a wipe -> restore.
    """
    def found():
        token = keycloak_admin_token()  # realm + admin creds recovered
        out = curl(
            AUTH_HOST, f"https://{AUTH_HOST}/admin/realms/{REALM}/users",
            "-H", f"Authorization: Bearer {token}",
            "-G", "--data-urlencode", f"email={CLI_USER}", "--data-urlencode", "exact=true",
        )
        emails = [(u.get("email") or "").lower() for u in json.loads(out)]
        assert CLI_USER.lower() in emails, f"restored user not found; got {emails}"

    retry(found)
