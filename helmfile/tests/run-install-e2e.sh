#!/usr/bin/env bash
# Installer-driven e2e (ADR-018): prove `suite install` drives a real k3d cluster
# to self-signed HTTPS — config -> helmfile sync -> Certificate Ready -> HTTPS per
# host -> the Keycloak OIDC client upsert (ADR-020) -> the Phase 1+2 SSO DoD. Fully
# hermetic: no SSH tunnel (ambient KUBECONFIG), no public DNS, no real ACME.
#
# Lighter than run-e2e.sh (no backup/restore cycle); the two intentionally do not
# share a library — this one only has to prove the installer orchestration.
set -euo pipefail
cd "$(dirname "$0")/../.."  # repo root

CLUSTER="${OWNSUITE_E2E_CLUSTER:-ownsuite-install-e2e}"
export OWNSUITE_DOMAIN="${OWNSUITE_DOMAIN:-ownsuite.localhost}"
export OWNSUITE_SECRET_SEED="${OWNSUITE_SECRET_SEED:-$(openssl rand -hex 24)}"
# Garage S3 + a seeded realm user with the direct-access grant, so the SSO DoD can
# mint a token without a browser (same knobs as run-e2e.sh). Backups stay off.
export OWNSUITE_OBJECT_STORAGE_MODE="${OWNSUITE_OBJECT_STORAGE_MODE:-garage}"
export OWNSUITE_KC_SEED_TEST_USER="${OWNSUITE_KC_SEED_TEST_USER:-true}"
export OWNSUITE_KC_DIRECT_GRANTS="${OWNSUITE_KC_DIRECT_GRANTS:-true}"
export OWNSUITE_BACKUP_ENABLED="${OWNSUITE_BACKUP_ENABLED:-false}"

cleanup() {
  rc=$?
  if [ "$rc" != "0" ] && [ -n "${KUBECONFIG:-}" ]; then
    echo "==> FAILURE diagnostics (exit $rc)"
    kubectl get pods -A -o wide || true
    kubectl -n ownsuite get certificate 2>/dev/null || true
    kubectl -n ownsuite logs job/keycloak-config-upsert --tail=60 2>/dev/null || true
    kubectl -n ownsuite get events --sort-by=.lastTimestamp 2>/dev/null | tail -40 || true
  fi
  [ "${OWNSUITE_E2E_KEEP:-0}" = "1" ] || k3d cluster delete "$CLUSTER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> Creating k3d cluster '$CLUSTER'"
k3d cluster create "$CLUSTER" \
  --port "80:80@loadbalancer" --port "443:443@loadbalancer" --wait --timeout 180s
KUBECONFIG="$(k3d kubeconfig write "$CLUSTER")"
export KUBECONFIG

# Make the ingress hostnames resolve to the k3d loadbalancer so the installer's own
# HTTPS verification step runs (production relies on real, propagated DNS instead).
echo "127.0.0.1 auth.${OWNSUITE_DOMAIN} docs.${OWNSUITE_DOMAIN}" | sudo tee -a /etc/hosts >/dev/null

echo "==> Running the installer (non-interactive, self-signed, no tunnel)"
python3 -m suite install \
  --non-interactive --no-tunnel --skip-bootstrap --skip-dns --skip-propagation \
  --tls-mode selfsigned --domain "$OWNSUITE_DOMAIN" --env-file "$(mktemp)"

echo "==> Asserting the Phase 1+2 definition of done (SSO document)"
OWNSUITE_E2E_STAGE=pre python3 -m pytest helmfile/tests/test_platform.py -v
