#!/usr/bin/env bash
# Full platform + apply + backup/restore definition-of-done on a throwaway k3d
# cluster:
#   create single-node K3s (Traefik kept) -> `suite apply` brings the stack up from
#   a generated suite.yaml (self-signed issuer, backups ON to a second in-cluster
#   RustFS as the off-site store) -> assert the shared infra DoD + provision a user
#   via the `suite user` CLI -> seed a media object -> back up (PostgreSQL base
#   backup + off-site object copy) -> DESTROY the primary state -> `make restore`
#   -> assert all THREE storage classes SURVIVED (ADR-006): the Keycloak user
#   (Postgres PITR), the media object (rclone object-copy, ADR-030) and a PVC
#   document (pvc_backup_roundtrip, ADR-032) -> destroy.
#
# This asserts NO application: each app's boot DoD lives in apps-e2e.yml / test_apps.py.
# Docs is the one app kept enabled here, SOLELY to provide a primary object bucket for
# the object-copy survival check (RustFS only creates buckets for enabled apps) — a
# restore fixture, not an app DoD.
#
# Provisioning goes through `suite apply` (ADR-042), so this ONE cluster proves the
# declarative orchestration AND the platform/restore DoD — there is no second
# from-scratch build.
#
# Heavy (pulls operators + Keycloak + runs a recovery); runs in helmfile-e2e.yml
# (scheduled + on helmfile changes) and locally via `make test-platform`.
set -euo pipefail

cd "$(dirname "$0")/../.."  # repo root
# Shared helpers: provision_with_watchdog, wait_for_certs, wait_job,
# dump_failure_diagnostics (also used by run-app-e2e.sh).
. helmfile/tests/lib.sh

CLUSTER="${OWNSUITE_E2E_CLUSTER:-ownsuite-e2e}"
HELMFILE="helmfile/helmfile.yaml.gotmpl"
NS=ownsuite
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
# Hermetic in-cluster RustFS S3 for the object store. The direct-access grant lets the
# restore survival check mint a Keycloak admin token without a browser.
export OWNSUITE_OBJECT_STORAGE_MODE="${OWNSUITE_OBJECT_STORAGE_MODE:-in-cluster}"
export OWNSUITE_KC_DIRECT_GRANTS="${OWNSUITE_KC_DIRECT_GRANTS:-true}"
# Apps are OFF by default (ADR-035). This suite asserts no app — but it keeps DOCS
# enabled SOLELY so RustFS creates the primary `docs-media-storage` bucket the
# object-copy backup/restore DoD seeds and reads back (a restore fixture, not an app
# DoD; that lives in test_apps.py). The installer then issues + verifies the docs cert
# alongside Keycloak. Drive et al. stay off so this stays lean.
export OWNSUITE_APP_DOCS=true
# Provision a user through the `suite user` CLI (admin REST -> realm, runtime). It is
# in no declarative realm import, so its survival after restore is the genuine proof
# the keycloak database recovered via PITR. A PERMANENT password is set for parity with
# real CLI usage (the survival check looks the user up via the admin API, not a login).
export OWNSUITE_E2E_USER="${OWNSUITE_E2E_USER:-restore-survivor@ownsuite.localhost}"
export OWNSUITE_E2E_USER_PW="${OWNSUITE_E2E_USER_PW:-$(openssl rand -hex 16)}"
# Phase 3: backups ON to a SECOND in-cluster RustFS (`rustfs-backup`) standing in for
# the off-site store. WAL archiving is continuous; the e2e takes an on-demand base
# backup and triggers the object-copy CronJob manually, so the default schedule
# (kept so the CronJob/ScheduledBackup exist) never actually fires during the run.
export OWNSUITE_BACKUP_ENABLED="${OWNSUITE_BACKUP_ENABLED:-true}"
export OWNSUITE_BACKUP_S3_TARGET="${OWNSUITE_BACKUP_S3_TARGET:-in-cluster}"
DOCS_BUCKET="${OWNSUITE_S3_BUCKET:-docs-media-storage}"

# The declarative input for `suite apply` (ADR-042), in a temp dir so a developer's
# real suite.yaml/.suite-state.json are never touched. The exported OWNSUITE_* above
# still win for scalar values (ambient env > suite.yaml); the APP SET comes from
# this file only. The raw-helmfile destroy/restore steps below read the env directly.
export OWNSUITE_CONFIG="$(mktemp -d)/suite.yaml"
cat > "$OWNSUITE_CONFIG" <<EOF
domain: ${OWNSUITE_DOMAIN}
tls: selfsigned
object_storage: {mode: in-cluster}
backup: {enabled: true, target: in-cluster}
apps:
  docs: {}
EOF
# rclone image (pinned), reused by the seed/verify helper Jobs below.
RCLONE_IMAGE="rclone/rclone:$(sed -nE 's/^[[:space:]]*rclone:[[:space:]]*"([^"]+)".*/\1/p' helmfile/versions/versions.yaml | head -1)"
MEDIA_FIXTURE="e2e/media-fixture.txt"

cleanup() {
  rc=$?
  [ "$rc" != "0" ] && { echo "(exit $rc)"; dump_failure_diagnostics; }
  if [ "${OWNSUITE_E2E_KEEP:-0}" != "1" ]; then
    echo "==> Deleting k3d cluster '$CLUSTER'"
    k3d cluster delete "$CLUSTER" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

# Run an rclone one-shot Job against the PRIMARY media store (RustFS). The actual
# off-site copy/restore is exercised by the chart's CronJob / restore Job; this
# helper only seeds and reads back objects from the primary bucket. $1 = job name,
# $2 = shell snippet (has $BUCKET available).
rclone_primary_job() {
  local name="$1" snippet="$2"
  kubectl -n "$NS" delete job "$name" --ignore-not-found >/dev/null 2>&1 || true
  kubectl -n "$NS" apply -f - <<EOF >/dev/null
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
            - {name: BUCKET, value: "${DOCS_BUCKET}"}
EOF
  wait_job "$name" 120
}

echo "==> Creating k3d cluster '$CLUSTER' (${OWNSUITE_K3S_IMAGE:-k3d default})"
k3d cluster create "$CLUSTER" \
  "${IMAGE_ARGS[@]}" \
  --port "80:80@loadbalancer" \
  --port "443:443@loadbalancer" \
  --wait --timeout 180s

KUBECONFIG="$(k3d kubeconfig write "$CLUSTER")"
export KUBECONFIG
wait_for_cluster_api

# apply verifies HTTPS for auth.{domain} + each ENABLED app (ADR-035) with
# Python's TLS stack (urllib honours /etc/hosts); point auth + the one enabled app
# (docs, kept only as the object-bucket vehicle) at the k3d loadbalancer so that step
# runs hermetically. The pytest below resolves per-request with `curl --resolve`.
echo "127.0.0.1 auth.${OWNSUITE_DOMAIN} docs.${OWNSUITE_DOMAIN}" | sudo tee -a /etc/hosts >/dev/null

# --- Bring the stack up VIA `suite apply` and assert the platform DoD ----------
# `suite apply` (ADR-042) is the provisioning path, so this single e2e proves the
# declarative orchestration AND the platform/restore DoD on one cluster. apply reads
# the suite.yaml above (no provider/ssh -> ambient k3d cluster, selfsigned -> no
# DNS), inherits the exported CI knobs (direct grants) through the env, applies once
# with the pinned issuer, waits for the keycloak/docs certs, verifies HTTPS. --yes:
# no TTY here — apply must never block on a confirmation. Idempotent, so the
# watchdog's one retry re-applies safely (the snapshot skips itself mid-bring-up).
provision_with_watchdog "domain=$OWNSUITE_DOMAIN, issuer=$OWNSUITE_TLS_ISSUER, backups=on" \
  python3 -m suite apply --yes --no-tunnel
wait_for_certs keycloak-tls docs-tls

echo "==> Provisioning the restore-survivor user through the suite CLI"
# Exercises the real CLI path (ADR-023): admin REST to the in-cluster Keycloak over a
# kubectl port-forward (no SSH tunnel needed against k3d — ambient KUBECONFIG). This
# runtime-created user is the Postgres-PITR survivor checked after the restore.
python3 -m suite user add "$OWNSUITE_E2E_USER" \
  --password "$OWNSUITE_E2E_USER_PW" --permanent --no-tunnel

echo "==> Asserting the platform + object-store definition of done"
OWNSUITE_E2E_STAGE=pre python3 -m pytest helmfile/tests/test_platform.py -v

# --- Phase 3: backup -> destroy -> restore --------------------------------------
echo "==> Phase 3: seeding a media object into the primary bucket"
rclone_primary_job e2e-seed-media \
  "printf 'ownsuite-e2e-media-fixture\n' | rclone rcat \"primary:\$BUCKET/$MEDIA_FIXTURE\" -v"

echo "==> Taking an on-demand PostgreSQL base backup (Barman Cloud Plugin)"
kubectl -n "$NS" delete backup e2e-backup --ignore-not-found >/dev/null 2>&1 || true
kubectl -n "$NS" apply -f - <<'EOF' >/dev/null
apiVersion: postgresql.cnpg.io/v1
kind: Backup
metadata:
  name: e2e-backup
spec:
  cluster:
    name: ownsuite-pg
  method: plugin
  pluginConfiguration:
    name: barman-cloud.cloudnative-pg.io
EOF
# The first base backup on a fresh cluster must first establish WAL archiving, then
# upload to the off-site store, so allow generous time (~9 min).
echo "    waiting for backup to complete..."
for i in $(seq 1 110); do
  phase="$(kubectl -n "$NS" get backup e2e-backup -o jsonpath='{.status.phase}' 2>/dev/null || echo '')"
  echo "    [backup $i] phase=${phase:-<pending>}"
  case "$phase" in
    completed) break ;;
    failed) echo "==> backup failed"; kubectl -n "$NS" describe backup e2e-backup | tail -40; exit 1 ;;
  esac
  [ "$i" -eq 110 ] && { echo "==> backup did not complete in time"; kubectl -n "$NS" describe backup e2e-backup | tail -40; exit 1; }
  sleep 5
done

echo "==> Copying media off-site (rclone CronJob, encrypted)"
kubectl -n "$NS" delete job object-backup-e2e --ignore-not-found >/dev/null 2>&1 || true
kubectl -n "$NS" create job --from=cronjob/object-backup object-backup-e2e >/dev/null
wait_job object-backup-e2e 180

# --- ADR-032: prove a Grist document SURVIVES a PVC-backup -> restore ------------
# Exercises the reusable pvc-backup chart end to end WITHOUT booting the heavy Grist
# pod (kept out of this constrained runner). The round-trip lives in lib.sh so the
# isolated, fast harness (run-pvc-backup-e2e.sh) runs the exact same code path.
pvc_backup_roundtrip

echo "==> DESTROYING the primary state (DB + primary object store + docs)"
# Keep platform-configuration (secrets), rustfs-backup (the off-site backups!), the
# barman plugin and the operators — they stand in for what survives the server.
helmfile -f "$HELMFILE" \
  -l name=docs -l name=docs-ingress \
  -l name=keycloak -l name=valkey -l name=postgres -l name=rustfs \
  destroy
echo "    deleting leftover PVCs (StatefulSet/CNPG volumes are not removed by uninstall)"
kubectl -n "$NS" delete pvc -l "cnpg.io/cluster=ownsuite-pg" --ignore-not-found
kubectl -n "$NS" delete pvc rustfs-data --ignore-not-found
# Make sure the CNPG Cluster object is fully gone before recovery recreates it.
kubectl -n "$NS" wait --for=delete cluster/ownsuite-pg --timeout=120s 2>/dev/null || true
echo "    primary state destroyed; off-site rustfs-backup retained:"
kubectl -n "$NS" get statefulset,cluster 2>/dev/null || true

echo "==> RESTORING from off-site backups (make restore)"
# Docs stays enabled through the restore so RustFS recreates the primary bucket and the
# object-copy can land the media fixture back in it. Restore is a direct `helmfile sync`
# (recovery bootstrap, the low-level path `suite restore` wraps) — only the initial
# provisioning goes through `suite apply` (above).
OWNSUITE_RESTORE=true provision_with_watchdog "RESTORE: CNPG recovery + object copy" \
  helmfile -f "$HELMFILE" sync
wait_for_certs keycloak-tls docs-tls

echo "==> Verifying the media object came back into the primary bucket"
rclone_primary_job e2e-verify-media \
  "rclone lsf \"primary:\$BUCKET/e2e/\" | tee /dev/stderr | grep -qx \"media-fixture.txt\""

echo "==> Asserting the Phase 3 definition of done (Keycloak user SURVIVED via PITR)"
OWNSUITE_E2E_STAGE=post-restore python3 -m pytest helmfile/tests/test_platform.py -v
