#!/usr/bin/env bash
# Fast, ISOLATED test of the ADR-032 PVC off-site backup/restore (the pvc-backup
# chart) WITHOUT the heavy suite — no Keycloak/Docs/Drive/CNPG. It boots a throwaway
# k3d cluster, stands up ONLY the off-site store (a single garage-backup, the same
# chart + pinned image prod uses, so nothing new is pulled), then runs the shared
# seed -> backup -> wipe -> restore -> assert round-trip from lib.sh. Reproduces both
# the PVC-protection wipe ordering and the busybox overrides path in ~2-3 min, so the
# backup logic can be iterated locally instead of waiting out the 30-min run-e2e.sh.
#   make test-pvc-backup        (or: helmfile/tests/run-pvc-backup-e2e.sh)
#   OWNSUITE_E2E_KEEP=1 make test-pvc-backup   # keep the cluster for poking around
set -euo pipefail

cd "$(dirname "$0")/../.."  # repo root
. helmfile/tests/lib.sh     # wait_job, dump_failure_diagnostics, pvc_backup_roundtrip

CLUSTER="${OWNSUITE_E2E_CLUSTER:-ownsuite-pvc-backup}"
NS=ownsuite
VERSIONS=helmfile/versions/versions.yaml
pin() { sed -nE 's/^[[:space:]]*'"$1"':[[:space:]]*"([^"]+)".*/\1/p' "$VERSIONS" | head -1; }
IMAGE_ARGS=()
[ -n "${OWNSUITE_K3S_IMAGE:-}" ] && IMAGE_ARGS=(--image "$OWNSUITE_K3S_IMAGE")

cleanup() {
  rc=$?
  [ "$rc" != "0" ] && { echo "(exit $rc)"; dump_failure_diagnostics; }
  if [ "${OWNSUITE_E2E_KEEP:-0}" != "1" ]; then
    echo "==> Deleting k3d cluster '$CLUSTER'"
    k3d cluster delete "$CLUSTER" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo "==> Creating k3d cluster '$CLUSTER' (${OWNSUITE_K3S_IMAGE:-k3d default})"
k3d cluster create "$CLUSTER" "${IMAGE_ARGS[@]}" --wait --timeout 180s
KUBECONFIG="$(k3d kubeconfig write "$CLUSTER")"
export KUBECONFIG
kubectl create namespace "$NS" >/dev/null

# Secrets normally produced by platform-configuration during a real install. Garage
# imports the S3 key from backup-s3-credentials; the pvc-backup chart reads the same
# secret for the rclone creds + crypt passphrase. Garage key format: id = GK + 24 hex,
# secret = 64 hex; the rpc secret is 32 bytes hex.
echo "==> Creating the backup secrets (S3 creds + crypt passphrase + garage rpc)"
kubectl -n "$NS" create secret generic backup-s3-credentials \
  --from-literal=ACCESS_KEY_ID="GK$(openssl rand -hex 12)" \
  --from-literal=ACCESS_SECRET_KEY="$(openssl rand -hex 32)" \
  --from-literal=RCLONE_CRYPT_PASSWORD="$(openssl rand -hex 16)" >/dev/null
kubectl -n "$NS" create secret generic garage-backup-credentials \
  --from-literal=rpcSecret="$(openssl rand -hex 32)" \
  --from-literal=adminToken="$(openssl rand -hex 16)" >/dev/null

echo "==> Standing up the off-site store (single garage-backup, the prod chart)"
helm install garage-backup helmfile/charts/garage \
  --namespace "$NS" \
  --set name=garage-backup \
  --set image.tag="$(pin garage)" \
  --set bootstrapImage.tag="$(pin kubectl)" \
  --set region=garage \
  --set storage.meta=1Gi --set storage.data=1Gi \
  --set 'buckets[0]=ownsuite-backups' \
  --set keyName=backup \
  --set credentialsSecret=garage-backup-credentials \
  --set s3Secret=backup-s3-credentials \
  --set s3SecretKeys.accessKeyId=ACCESS_KEY_ID \
  --set s3SecretKeys.secretAccessKey=ACCESS_SECRET_KEY \
  --wait --timeout 180s

# The whole point of this harness: the shared ADR-032 round-trip, same code as run-e2e.sh.
pvc_backup_roundtrip

echo "==> PASS: the PVC document survived backup -> wipe -> restore (ADR-032)"
