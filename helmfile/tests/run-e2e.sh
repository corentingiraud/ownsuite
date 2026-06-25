#!/usr/bin/env bash
# Full Phase 1 definition-of-done on a throwaway k3d cluster:
#   create single-node K3s (Traefik kept) -> helmfile sync (self-signed issuer)
#   -> assert the shared infra is up and Keycloak answers over HTTPS -> destroy.
#
# Heavy (pulls operators + Keycloak); runs in helmfile-e2e.yml (scheduled + on
# helmfile changes) and locally via `make test-platform`.
set -euo pipefail

cd "$(dirname "$0")/../.."  # repo root

CLUSTER="${OWNSUITE_E2E_CLUSTER:-ownsuite-e2e}"
HELMFILE="helmfile/helmfile.yaml.gotmpl"
# K3s image for k3d. Default to the version bundled with the pinned k3d binary
# (guaranteed compatible); override with OWNSUITE_K3S_IMAGE to test a specific
# K3s release, e.g. the one the Ansible bootstrap installs.
IMAGE_ARGS=()
if [ -n "${OWNSUITE_K3S_IMAGE:-}" ]; then
  IMAGE_ARGS=(--image "$OWNSUITE_K3S_IMAGE")
fi

export OWNSUITE_DOMAIN="${OWNSUITE_DOMAIN:-ownsuite.localhost}"
export OWNSUITE_TLS_ISSUER="selfsigned"
export OWNSUITE_SECRET_SEED="${OWNSUITE_SECRET_SEED:-$(openssl rand -hex 24)}"
# Phase 2: deploy the Docs vertical slice on a hermetic in-cluster Garage S3, and
# seed a realm user (+ enable the direct-access grant) so the DoD test can mint a
# token and create a document without a browser.
export OWNSUITE_OBJECT_STORAGE_MODE="${OWNSUITE_OBJECT_STORAGE_MODE:-garage}"
export OWNSUITE_KC_SEED_TEST_USER="${OWNSUITE_KC_SEED_TEST_USER:-true}"
export OWNSUITE_KC_DIRECT_GRANTS="${OWNSUITE_KC_DIRECT_GRANTS:-true}"

cleanup() {
  rc=$?
  # On failure, dump cluster state before tearing down — the only window to see
  # what went wrong in CI (pod status, recent events, logs of non-Ready pods).
  if [ "$rc" != "0" ] && [ -n "${KUBECONFIG:-}" ]; then
    echo "==> FAILURE diagnostics (exit $rc)"
    kubectl get pods -A -o wide || true
    echo "--- recent events (ownsuite) ---"
    kubectl -n ownsuite get events --sort-by=.lastTimestamp 2>/dev/null | tail -50 || true
    echo "--- logs of non-Ready pods (ownsuite) ---"
    for p in $(kubectl -n ownsuite get pods \
      -o jsonpath='{range .items[?(@.status.containerStatuses[0].ready==false)]}{.metadata.name}{"\n"}{end}' 2>/dev/null); do
      echo "### $p ###"
      kubectl -n ownsuite logs "$p" --all-containers --tail=60 2>&1 | tail -60 || true
    done
  fi
  if [ "${OWNSUITE_E2E_KEEP:-0}" != "1" ]; then
    echo "==> Deleting k3d cluster '$CLUSTER'"
    k3d cluster delete "$CLUSTER" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo "==> Creating k3d cluster '$CLUSTER' (${OWNSUITE_K3S_IMAGE:-k3d default})"
k3d cluster create "$CLUSTER" \
  "${IMAGE_ARGS[@]}" \
  --port "80:80@loadbalancer" \
  --port "443:443@loadbalancer" \
  --wait --timeout 180s

KUBECONFIG="$(k3d kubeconfig write "$CLUSTER")"
export KUBECONFIG

echo "==> helmfile sync (domain=$OWNSUITE_DOMAIN, issuer=$OWNSUITE_TLS_ISSUER)"
helmfile -f "$HELMFILE" sync

# cert-manager issues the certificates asynchronously after the ingresses are
# created; give them a moment before asserting (non-fatal — pytest re-checks).
echo "==> Waiting for the Keycloak + Docs TLS certificates"
kubectl -n ownsuite wait --for=condition=Ready certificate/keycloak-tls --timeout=180s || true
kubectl -n ownsuite wait --for=condition=Ready certificate/docs-tls --timeout=180s || true

echo "==> Asserting the definition of done"
python3 -m pytest helmfile/tests/test_platform.py -v
