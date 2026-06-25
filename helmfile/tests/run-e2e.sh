#!/usr/bin/env bash
# Full Phase 1-3 definition-of-done on a throwaway k3d cluster:
#   create single-node K3s (Traefik kept) -> helmfile sync (self-signed issuer,
#   backups ON to a second in-cluster Garage acting as the off-site store) ->
#   assert the shared infra + Docs SSO DoD -> seed a media object -> back up
#   (PostgreSQL base backup + off-site object copy) -> DESTROY the primary state ->
#   `make restore` -> assert the Docs document, the Keycloak user, and the media
#   object all SURVIVED the cycle (ADR-006) -> destroy.
#
# Heavy (pulls operators + Keycloak + runs a recovery); runs in helmfile-e2e.yml
# (scheduled + on helmfile changes) and locally via `make test-platform`.
set -euo pipefail

cd "$(dirname "$0")/../.."  # repo root

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
# Phase 2: deploy the Docs vertical slice on a hermetic in-cluster Garage S3, and
# seed a realm user (+ enable the direct-access grant) so the DoD test can mint a
# token and create a document without a browser.
export OWNSUITE_OBJECT_STORAGE_MODE="${OWNSUITE_OBJECT_STORAGE_MODE:-garage}"
export OWNSUITE_KC_SEED_TEST_USER="${OWNSUITE_KC_SEED_TEST_USER:-true}"
export OWNSUITE_KC_DIRECT_GRANTS="${OWNSUITE_KC_DIRECT_GRANTS:-true}"
# Phase 3: backups ON to a SECOND in-cluster Garage (`garage-backup`) standing in for
# the off-site store. WAL archiving is continuous; the e2e takes an on-demand base
# backup and triggers the object-copy CronJob manually, so the default schedule
# (kept so the CronJob/ScheduledBackup exist) never actually fires during the run.
export OWNSUITE_BACKUP_ENABLED="${OWNSUITE_BACKUP_ENABLED:-true}"
export OWNSUITE_BACKUP_S3_TARGET="${OWNSUITE_BACKUP_S3_TARGET:-in-cluster}"
DOCS_BUCKET="${OWNSUITE_S3_BUCKET:-docs-media-storage}"
# rclone image (pinned), reused by the seed/verify helper Jobs below.
RCLONE_IMAGE="rclone/rclone:$(sed -nE 's/^[[:space:]]*rclone:[[:space:]]*"([^"]+)".*/\1/p' helmfile/versions/versions.yaml | head -1)"
MEDIA_FIXTURE="e2e/media-fixture.txt"

cleanup() {
  rc=$?
  # On failure, dump cluster state before tearing down — the only window to see
  # what went wrong in CI (pod status, recent events, logs of non-Ready pods).
  if [ "$rc" != "0" ] && [ -n "${KUBECONFIG:-}" ]; then
    echo "==> FAILURE diagnostics (exit $rc)"
    kubectl get pods -A -o wide || true
    echo "--- recent events (ownsuite) ---"
    kubectl -n "$NS" get events --sort-by=.lastTimestamp 2>/dev/null | tail -50 || true
    echo "--- CNPG cluster + backups ---"
    kubectl -n "$NS" get cluster,backup,objectstore,scheduledbackup 2>/dev/null || true
    kubectl -n "$NS" get cluster ownsuite-pg -o jsonpath='{.status.phase}{"\n"}{.status.conditions}{"\n"}' 2>/dev/null || true
    echo "--- barman-cloud plugin logs (cnpg-system) ---"
    kubectl -n cnpg-system logs -l app=barman-cloud --tail=60 2>&1 | tail -60 || true
    echo "--- CNPG recovery/job pod logs (ownsuite) ---"
    for p in $(kubectl -n "$NS" get pods --no-headers 2>/dev/null \
      | awk '$1 ~ /-recovery|-full-recovery|object-restore/ {print $1}'); do
      echo "### $p ###"
      kubectl -n "$NS" logs "$p" --all-containers --tail=120 2>&1 | tail -120 || true
    done
    echo "--- logs of non-Ready pods (ownsuite) ---"
    for p in $(kubectl -n "$NS" get pods \
      -o jsonpath='{range .items[?(@.status.containerStatuses[0].ready==false)]}{.metadata.name}{"\n"}{end}' 2>/dev/null); do
      echo "### $p ###"
      kubectl -n "$NS" logs "$p" --all-containers --tail=80 2>&1 | tail -80 || true
    done
  fi
  if [ "${OWNSUITE_E2E_KEEP:-0}" != "1" ]; then
    echo "==> Deleting k3d cluster '$CLUSTER'"
    k3d cluster delete "$CLUSTER" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

# `helmfile sync` blocks silently on `helm --wait` (up to 900s/release). Run it in
# the background with a watchdog that prints a per-pod-phase heartbeat and aborts
# IMMEDIATELY on an unrecoverable pod state (image pull errors, container start
# errors, or a pod stuck in CrashLoopBackOff) — turning a 15-minute silent timeout
# into a ~15-second, actionable failure. Reused for the initial sync and `restore`.
sync_with_watchdog() {
  local desc="$1"
  echo "==> helmfile sync ($desc)"
  local log; log="$(mktemp)"
  helmfile -f "$HELMFILE" sync >"$log" 2>&1 &
  local pid=$!
  local empty=0
  while kill -0 "$pid" 2>/dev/null; do
    sleep 15
    local summary
    summary="$(kubectl get pods -A --no-headers 2>/dev/null \
      | awk '{c[$4]++} END{for(k in c) printf "%s=%d ", k, c[k]}')"
    echo "[watch $(date -u +%H:%M:%S)] pods: $summary"
    # kube-system pods appear within ~1 min of a healthy k3d cluster. A prolonged
    # empty listing means the cluster API is unreachable (k3d/runner flakiness) —
    # fail fast instead of waiting out the helm timeout.
    if [ -z "$summary" ]; then empty=$((empty + 1)); else empty=0; fi
    if [ "$empty" -ge 10 ]; then
      echo "==> FAIL-FAST: no pods visible for ${empty} checks — cluster API unreachable"
      kubectl get nodes -o wide 2>&1 | head -5 || true
      kubectl cluster-info 2>&1 | head -5 || true
      kill "$pid" 2>/dev/null || true
      cat "$log"
      exit 1
    fi
    if kubectl get pods -A --no-headers 2>/dev/null | awk '
        $4 ~ /ImagePullBackOff|ErrImagePull|InvalidImageName|CreateContainerError|RunContainerError|CreateContainerConfigError/ {bad=1; print "  ! "$0}
        $4 == "CrashLoopBackOff" && ($5+0) >= 3 {bad=1; print "  ! "$0}
        # Several pods stuck in Error usually means a Job (e.g. CNPG recovery) is
        # failing and retrying — surface it instead of waiting for the helm timeout.
        $4 == "Error" {err++} END {if (err+0 >= 4) {print "  ! "err" pods in Error state"; bad=1}; exit bad ? 0 : 1}'; then
      echo "==> FAIL-FAST: unrecoverable pod state during sync (see above)"
      kill "$pid" 2>/dev/null || true
      cat "$log"
      exit 1
    fi
  done
  local sync_rc=0
  wait "$pid" || sync_rc=$?
  cat "$log"
  [ "$sync_rc" -eq 0 ] || { echo "==> helmfile sync failed (exit $sync_rc)"; exit "$sync_rc"; }
}

wait_for_certs() {
  # cert-manager issues the certificates asynchronously after the ingresses are
  # created; give them a moment before asserting (non-fatal — pytest re-checks).
  echo "==> Waiting for the Keycloak + Docs TLS certificates"
  kubectl -n "$NS" wait --for=condition=Ready certificate/keycloak-tls --timeout=180s || true
  kubectl -n "$NS" wait --for=condition=Ready certificate/docs-tls --timeout=180s || true
}

wait_job() {
  # Poll a Job to success/failure (kubectl wait can't watch two conditions at once).
  local name="$1" timeout="${2:-180}" i=0
  while :; do
    local s f
    s="$(kubectl -n "$NS" get job "$name" -o jsonpath='{.status.succeeded}' 2>/dev/null || echo 0)"
    f="$(kubectl -n "$NS" get job "$name" -o jsonpath='{.status.failed}' 2>/dev/null || echo 0)"
    if [ "${s:-0}" -ge 1 ] 2>/dev/null; then echo "    job/$name succeeded"; return 0; fi
    if [ "${f:-0}" -ge 1 ] 2>/dev/null; then
      echo "    job/$name FAILED"; kubectl -n "$NS" logs "job/$name" --tail=80 || true; return 1
    fi
    i=$((i + 1))
    if [ "$i" -gt "$((timeout / 3))" ]; then
      echo "    job/$name TIMEOUT"; kubectl -n "$NS" logs "job/$name" --tail=80 || true; return 1
    fi
    sleep 3
  done
}

# Run an rclone one-shot Job against the PRIMARY media store (Garage). The actual
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
            - {name: RCLONE_CONFIG_PRIMARY_ENDPOINT, value: "http://garage.${NS}.svc.cluster.local:3900"}
            - {name: RCLONE_CONFIG_PRIMARY_REGION, value: garage}
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

# --- Phase 1+2: bring the stack up and assert the SSO definition of done --------
sync_with_watchdog "domain=$OWNSUITE_DOMAIN, issuer=$OWNSUITE_TLS_ISSUER, backups=on"
wait_for_certs

echo "==> Asserting the Phase 1+2 definition of done (creates the survivor document)"
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

echo "==> DESTROYING the primary state (DB + primary object store + apps)"
# Keep platform-configuration (secrets), garage-backup (the off-site backups!), the
# barman plugin and the operators — they stand in for what survives the VPS.
helmfile -f "$HELMFILE" \
  -l name=docs -l name=docs-ingress -l name=keycloak -l name=valkey \
  -l name=postgres -l name=garage \
  destroy
echo "    deleting leftover PVCs (StatefulSet/CNPG volumes are not removed by uninstall)"
kubectl -n "$NS" delete pvc -l "cnpg.io/cluster=ownsuite-pg" --ignore-not-found
kubectl -n "$NS" delete pvc meta-garage-0 data-garage-0 --ignore-not-found
# Make sure the CNPG Cluster object is fully gone before recovery recreates it.
kubectl -n "$NS" wait --for=delete cluster/ownsuite-pg --timeout=120s 2>/dev/null || true
echo "    primary state destroyed; off-site garage-backup retained:"
kubectl -n "$NS" get statefulset,cluster 2>/dev/null || true

echo "==> RESTORING from off-site backups (make restore)"
OWNSUITE_RESTORE=true sync_with_watchdog "RESTORE: CNPG recovery + object copy"
wait_for_certs

echo "==> Verifying the media object came back into the primary bucket"
rclone_primary_job e2e-verify-media \
  "rclone lsf \"primary:\$BUCKET/e2e/\" | tee /dev/stderr | grep -qx \"media-fixture.txt\""

echo "==> Asserting the Phase 3 definition of done (document + user SURVIVED)"
OWNSUITE_E2E_STAGE=post-restore python3 -m pytest helmfile/tests/test_platform.py -v
