"""Phase 1 definition-of-done assertions for the OwnSuite shared infrastructure.

Run against a live cluster after `helmfile sync` (see run-e2e.sh). Each test
shells out to kubectl/curl using the ambient KUBECONFIG, so there is no extra
Python dependency beyond pytest.
"""

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
DOCS_HOST = f"docs.{DOMAIN}"

SECRET_SEED = os.environ.get("OWNSUITE_SECRET_SEED")
GARAGE_MODE = os.environ.get("OWNSUITE_OBJECT_STORAGE_MODE", "external") == "garage"
SEED_TEST_USER = os.environ.get("OWNSUITE_KC_SEED_TEST_USER", "false").lower() == "true"
DOCS_BUCKET = os.environ.get("OWNSUITE_S3_BUCKET", "docs-media-storage")

# Test stage (set by run-e2e.sh): "pre" runs the Phase 1+2 DoD (and creates the
# survivor document); "post-restore" re-asserts infra health and proves the
# document + Keycloak user survived the backup -> destroy -> restore cycle (ADR-006).
E2E_STAGE = os.environ.get("OWNSUITE_E2E_STAGE", "pre")
PRE_ONLY = pytest.mark.skipif(
    E2E_STAGE != "pre", reason="runs only pre-destroy (creates the survivor document)"
)
POST_RESTORE_ONLY = pytest.mark.skipif(
    E2E_STAGE != "post-restore", reason="runs only after restore (survival check)"
)

# Deterministic title of the document created in the Phase 2 DoD; the Phase 3
# survival check looks for exactly this document after the restore.
DOC_TITLE = "OwnSuite e2e — persistent document"


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


# --- Phase 2: Docs vertical slice (ADR-015, ADR-016) ------------------------


@pytest.mark.skipif(not GARAGE_MODE, reason="object storage is not in garage mode")
def test_garage_running_and_bucket_ready():
    """Garage is up and the bootstrap Job created the Docs media bucket (ADR-015)."""
    pods = json.loads(kubectl("-n", NAMESPACE, "get", "pods",
                              "-l", "app.kubernetes.io/name=garage", "-o", "json").stdout)["items"]
    assert any(p["status"]["phase"] == "Running" for p in pods), "no Running garage pod"

    def bucket_exists():
        res = kubectl("-n", NAMESPACE, "exec", "garage-0", "-c", "garage", "--",
                      "/garage", "bucket", "info", DOCS_BUCKET, check=False)
        assert res.returncode == 0, f"bucket {DOCS_BUCKET} missing: {res.stdout + res.stderr}"

    retry(bucket_exists)


def test_docs_database_applied():
    applied = kubectl(
        "-n", NAMESPACE, "get", "database", "docs", "-o", "jsonpath={.status.applied}"
    ).stdout.strip()
    assert applied == "true", f"Database docs not applied ({applied!r})"


def test_docs_pods_ready():
    """All Docs components reach Ready (backend, celery, frontend, y-provider)."""
    for component in ("backend", "celery-worker", "frontend", "yProvider"):
        out = kubectl(
            "-n", NAMESPACE, "get", "pods",
            "-l", f"app.kubernetes.io/name=docs,app.kubernetes.io/component={component}",
            "-o", 'jsonpath={.items[*].status.conditions[?(@.type=="Ready")].status}',
        ).stdout
        assert "True" in out, f"Docs {component} pod not Ready ({out!r})"


def test_docs_reachable_over_https():
    """Docs answers over HTTPS through Traefik and exposes its OIDC config."""
    def fetch():
        out = curl(DOCS_HOST, f"https://{DOCS_HOST}/api/v1.0/config/")
        data = json.loads(out)
        # The frontend reads OIDC + collaboration settings from this endpoint.
        assert isinstance(data, dict) and data, "empty Docs config payload"
        return data

    retry(fetch, attempts=40, delay=3)


@PRE_ONLY
@pytest.mark.skipif(
    not (SECRET_SEED and SEED_TEST_USER),
    reason="needs OWNSUITE_SECRET_SEED and a seeded Keycloak test user",
)
def test_dod_sso_user_creates_persistent_document():
    """The Phase 2 definition of done: a Keycloak user logs in via SSO (OIDC) and
    creates a persistent document.

    Headless equivalent of the browser flow: obtain an access token from Keycloak
    with the seeded user (direct-access grant), then create a document through the
    Docs API as that user and read it back — proving SSO client wiring + DB
    persistence. Docs validates the bearer token against Keycloak's userinfo
    endpoint and just-in-time provisions the user (ADR-005, ADR-016). This document
    is also the survivor checked by the Phase 3 backup/restore test.
    """
    token = retry(docs_user_token)
    auth_header = f"Authorization: Bearer {token}"
    docs_api = f"https://{DOCS_HOST}/api/v1.0/documents/"

    def create():
        out = curl(
            DOCS_HOST, docs_api,
            "-X", "POST", "-H", auth_header,
            "-H", "Content-Type: application/json",
            "--data", json.dumps({"title": DOC_TITLE}),
        )
        doc = json.loads(out)
        assert doc.get("id"), f"no document id returned: {doc}"
        return doc["id"]

    doc_id = retry(create)

    def read_back():
        out = curl(DOCS_HOST, f"{docs_api}{doc_id}/", "-H", auth_header)
        doc = json.loads(out)
        assert doc["title"] == DOC_TITLE, doc
        return doc

    retry(read_back)


# --- Phase 3: backups & tested restore (ADR-006, ADR-017) -------------------


@POST_RESTORE_ONLY
@pytest.mark.skipif(
    not (SECRET_SEED and SEED_TEST_USER),
    reason="needs OWNSUITE_SECRET_SEED and a seeded Keycloak test user",
)
def test_restore_preserves_document_and_user():
    """The Phase 3 definition of done: after backup -> destroy -> restore, the
    Keycloak user still authenticates (realm + users recovered via CNPG PITR of the
    `keycloak` database) and the document created before the destroy is still there
    (the `docs` database recovered too). No document is created here — presence of
    the pre-destroy document is the proof of a real restore.

    The Keycloak user keeps its stable subject (the restored user row's id), so the
    Docs JIT-provisioned account maps back to the same owner and lists its document.
    """
    token = retry(docs_user_token)  # user survived: realm + credentials recovered
    auth_header = f"Authorization: Bearer {token}"
    docs_api = f"https://{DOCS_HOST}/api/v1.0/documents/"

    def find_survivor():
        out = curl(DOCS_HOST, f"{docs_api}?page_size=100", "-H", auth_header)
        payload = json.loads(out)
        items = payload.get("results", payload) if isinstance(payload, dict) else payload
        titles = [d.get("title") for d in items]
        assert DOC_TITLE in titles, f"restored document not found; got titles={titles}"

    retry(find_survivor)
