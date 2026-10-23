#!/usr/bin/env bash
# Fast, ISOLATED test of the object off-site backup/restore (ADR-006, ADR-017, ADR-047)
# WITHOUT the heavy suite: no Keycloak/Docs/Drive/CNPG, no Grist pod. It boots a
# throwaway k3d cluster and syncs ONLY platform-configuration (secrets), the primary
# rustfs (creates + versions the Grist bucket), the off-site rustfs-backup and the
# object-backup chart, all through the real helmfile releases. It then seeds a Grist
# document object, runs the backup CronJob, destroys the primary RustFS and its volume,
# re-syncs in restore mode and asserts the document came back byte-identical and the
# bucket is versioned again (Grist refuses an unversioned bucket at boot).
#   make test-object-backup        (or: helmfile/tests/run-object-backup-e2e.sh)
#   OWNSUITE_E2E_KEEP=1 make test-object-backup   # keep the cluster for poking around
set -euo pipefail

cd "$(dirname "$0")/../.."  # repo root
. helmfile/tests/lib.sh     # wait_job, wait_for_cluster_api, provision_with_watchdog, dump_failure_diagnostics

CLUSTER="${OWNSUITE_E2E_CLUSTER:-ownsuite-object-backup}"
HELMFILE="helmfile/helmfile.yaml.gotmpl"
NS=ownsuite
GRIST_BUCKET="${OWNSUITE_GRIST_S3_BUCKET:-grist-docs}"
DOC_KEY="docs/e2e.grist"
DOC_CONTENT="ownsuite-e2e-grist-document-fixture"
RCLONE_IMAGE="rclone/rclone:$(sed -nE 's/^[[:space:]]*rclone:[[:space:]]*"([^"]+)".*/\1/p' helmfile/versions/versions.yaml | head -1)"
IMAGE_ARGS=()
[ -n "${OWNSUITE_K3S_IMAGE:-}" ] && IMAGE_ARGS=(--image "$OWNSUITE_K3S_IMAGE")

# Same inputs the full suite uses, minus everything but Grist's bucket.
export OWNSUITE_DOMAIN="${OWNSUITE_DOMAIN:-ownsuite.localhost}"
export OWNSUITE_TLS_ISSUER="selfsigned"
export OWNSUITE_SECRET_SEED="${OWNSUITE_SECRET_SEED:-$(openssl rand -hex 24)}"
export OWNSUITE_OBJECT_STORAGE_MODE=in-cluster
export OWNSUITE_APP_GRIST=true
export OWNSUITE_BACKUP_ENABLED=true
export OWNSUITE_BACKUP_S3_TARGET=in-cluster
export OWNSUITE_GRIST_S3_BUCKET="$GRIST_BUCKET"

cleanup() {
  rc=$?
  [ "$rc" != "0" ] && { echo "(exit $rc)"; dump_failure_diagnostics; }
  if [ "${OWNSUITE_E2E_KEEP:-0}" != "1" ]; then
    echo "==> Deleting k3d cluster '$CLUSTER'"
    k3d cluster delete "$CLUSTER" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

# One-shot rclone Job against the PRIMARY RustFS. $1 = job name, $2 = shell snippet
# (has $BUCKET available).
rclone_primary_job() {
  local name="$1" snippet="$2"
  kubectl -n "$NS" delete job "$name" --ignore-not-found >/dev/null 2>&1 || true
  kubectl -n "$NS" apply -f - <<YAML >/dev/null
apiVersion: batch/v1
kind: Job
metadata:
  name: ${name}
spec:
  backoffLimit: 1
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: rclone
          image: ${RCLONE_IMAGE}
          command: ["/bin/sh", "-ceu"]
          args:
            - |
$(printf '%s\n' "$snippet" | sed 's/^/              /')
          env:
            - {name: RCLONE_CONFIG_PRIMARY_TYPE, value: s3}
            - {name: RCLONE_CONFIG_PRIMARY_PROVIDER, value: Other}
            - {name: RCLONE_CONFIG_PRIMARY_ENDPOINT, value: "http://rustfs-svc.${NS}.svc.cluster.local:9000"}
            - {name: RCLONE_CONFIG_PRIMARY_REGION, value: us-east-1}
            - {name: RCLONE_CONFIG_PRIMARY_FORCE_PATH_STYLE, value: "true"}
            - name: RCLONE_CONFIG_PRIMARY_ACCESS_KEY_ID
              valueFrom: {secretKeyRef: {name: s3-credentials, key: AWS_S3_ACCESS_KEY_ID}}
            - name: RCLONE_CONFIG_PRIMARY_SECRET_ACCESS_KEY
              valueFrom: {secretKeyRef: {name: s3-credentials, key: AWS_S3_SECRET_ACCESS_KEY}}
            - {name: BUCKET, value: "${GRIST_BUCKET}"}
YAML
  wait_job "$name" 120
}

echo "==> Creating k3d cluster '$CLUSTER' (${OWNSUITE_K3S_IMAGE:-k3d default})"
create_cluster_with_retry "$CLUSTER" "${IMAGE_ARGS[@]}"
wait_for_cluster_api
kubectl create namespace "$NS" >/dev/null

SELECT=(-l name=platform-configuration -l name=rustfs -l name=rustfs-backup -l name=object-backup)

provision_with_watchdog "object-backup stack: secrets + 2 RustFS + rclone copy" \
  helmfile -f "$HELMFILE" "${SELECT[@]}" sync

echo "==> Asserting the Grist bucket is versioned on the primary store"
# shellcheck disable=SC2016  # $BUCKET is expanded inside the Job, not here
rclone_primary_job e2e-check-versioning \
  'rclone backend versioning "primary:$BUCKET" | grep -q "Enabled"'

echo "==> Seeding a Grist document object (${GRIST_BUCKET}/${DOC_KEY})"
rclone_primary_job e2e-seed-doc \
  "printf '%s' '${DOC_CONTENT}' | rclone rcat \"primary:\$BUCKET/${DOC_KEY}\" -v"

echo "==> Copying off-site (object-backup CronJob, encrypted)"
kubectl -n "$NS" delete job object-backup-e2e --ignore-not-found >/dev/null 2>&1 || true
kubectl -n "$NS" create job --from=cronjob/object-backup object-backup-e2e >/dev/null
wait_job object-backup-e2e 180

echo "==> DESTROYING the primary RustFS and its volume (simulating server loss)"
helmfile -f "$HELMFILE" -l name=rustfs destroy
kubectl -n "$NS" delete pvc rustfs-data --ignore-not-found
kubectl -n "$NS" wait --for=delete pvc/rustfs-data --timeout=120s 2>/dev/null || true

echo "==> RESTORING (object-restore Job copies the off-site data back)"
OWNSUITE_RESTORE=true provision_with_watchdog "RESTORE: primary RustFS + object copy" \
  helmfile -f "$HELMFILE" "${SELECT[@]}" sync

echo "==> Asserting the Grist document SURVIVED and the bucket is versioned again"
rclone_primary_job e2e-verify-doc \
  "test \"\$(rclone cat \"primary:\$BUCKET/${DOC_KEY}\")\" = '${DOC_CONTENT}'
rclone backend versioning \"primary:\$BUCKET\" | grep -q Enabled
echo 'GRIST DOCUMENT SURVIVED'"

echo "==> PASS: the Grist document survived backup -> wipe -> restore (ADR-047)"
