#!/usr/bin/env bash
# Fast, ISOLATED test of the ADR-032 PVC off-site backup/restore (the pvc-backup
# chart) WITHOUT the heavy suite — no Keycloak/Docs/Drive/CNPG. It boots a throwaway
# k3d cluster, stands up ONLY the off-site store (a single rustfs-backup, the same
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

# Secrets normally produced by platform-configuration during a real install (ADR-046).
# RustFS takes its root credential from backup-s3-credentials (RUSTFS_ACCESS_KEY/
# RUSTFS_SECRET_KEY); the pvc-backup chart's rclone reads the SAME key under
# ACCESS_KEY_ID/ACCESS_SECRET_KEY, so both must be the same value to authenticate as
# the RustFS root. No RPC/admin secret — RustFS is single-node, no inter-node protocol.
echo "==> Creating the backup secret (S3 root creds + crypt passphrase)"
S3_ID="rustfs$(openssl rand -hex 8)"
S3_SECRET="$(openssl rand -hex 20)"
kubectl -n "$NS" create secret generic backup-s3-credentials \
  --from-literal=ACCESS_KEY_ID="$S3_ID" \
  --from-literal=ACCESS_SECRET_KEY="$S3_SECRET" \
  --from-literal=RUSTFS_ACCESS_KEY="$S3_ID" \
  --from-literal=RUSTFS_SECRET_KEY="$S3_SECRET" \
  --from-literal=RCLONE_CRYPT_PASSWORD="$(openssl rand -hex 16)" >/dev/null

echo "==> Standing up the off-site store (single rustfs-backup, the upstream chart)"
helm install rustfs-backup rustfs \
  --repo https://charts.rustfs.com \
  --version "$(pin rustfs)" \
  --namespace "$NS" \
  --set mode.standalone.enabled=true \
  --set mode.distributed.enabled=false \
  --set secret.existingSecret=backup-s3-credentials \
  --set storageclass.dataStorageSize=1Gi \
  --set-string config.rustfs.region=us-east-1 \
  --set-string config.rustfs.console_enable=false \
  --set config.rustfs.obs_log_directory= \
  --set ingress.enabled=false \
  --wait --timeout 180s

# The upstream chart creates no buckets; make the one the round-trip copies into.
echo "==> Creating the ownsuite-backups bucket (rclone mkdir)"
kubectl -n "$NS" run rustfs-mkbucket -i --rm --restart=Never \
  --image="rclone/rclone:$(pin rclone)" \
  --env=RCLONE_CONFIG_S3_TYPE=s3 \
  --env=RCLONE_CONFIG_S3_PROVIDER=Other \
  --env=RCLONE_CONFIG_S3_ENDPOINT="http://rustfs-backup-svc.${NS}.svc.cluster.local:9000" \
  --env=RCLONE_CONFIG_S3_REGION=us-east-1 \
  --env=RCLONE_CONFIG_S3_FORCE_PATH_STYLE=true \
  --env=RCLONE_CONFIG_S3_ACCESS_KEY_ID="$S3_ID" \
  --env=RCLONE_CONFIG_S3_SECRET_ACCESS_KEY="$S3_SECRET" \
  --command -- rclone mkdir s3:ownsuite-backups

# The whole point of this harness: the shared ADR-032 round-trip, same code as run-e2e.sh.
pvc_backup_roundtrip

echo "==> PASS: the PVC document survived backup -> wipe -> restore (ADR-032)"
