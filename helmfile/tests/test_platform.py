"""Phase 1 definition-of-done assertions for the OwnSuite shared infrastructure.

Run against a live cluster after `helmfile sync` (see run-e2e.sh). Each test
shells out to kubectl/curl using the ambient KUBECONFIG, so there is no extra
Python dependency beyond pytest.
"""

import json
import os
import subprocess
import time

NAMESPACE = "ownsuite"
REALM = "ownsuite"
DOMAIN = os.environ.get("OWNSUITE_DOMAIN", "ownsuite.localhost")


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
