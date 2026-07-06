#!/usr/bin/env bash
# Shared e2e helpers, sourced by run-e2e.sh (the full platform + backup/restore DoD)
# and run-app-e2e.sh (one optional app per fresh cluster). Keeps the fail-fast sync
# watchdog, the Job poller, the cert wait and the failure diagnostics in ONE place so
# the two harnesses share them instead of copy-pasting. Callers set `$NS` (the
# workloads namespace) and export KUBECONFIG before calling these.

dump_failure_diagnostics() {
  # On failure, dump cluster state — the only window to see what went wrong in CI
  # (pod status, recent events, CNPG/backup state, logs of non-Ready/recovery pods).
  [ -n "${KUBECONFIG:-}" ] || return 0
  echo "==> FAILURE diagnostics"
  kubectl get pods -A -o wide || true
  echo "--- recent events ($NS) ---"
  kubectl -n "$NS" get events --sort-by=.lastTimestamp 2>/dev/null | tail -50 || true
  echo "--- CNPG cluster + backups ---"
  kubectl -n "$NS" get cluster,backup,objectstore,scheduledbackup 2>/dev/null || true
  kubectl -n "$NS" get cluster ownsuite-pg -o jsonpath='{.status.phase}{"\n"}{.status.conditions}{"\n"}' 2>/dev/null || true
  echo "--- barman-cloud plugin (cnpg-system) ---"
  kubectl -n cnpg-system logs -l app=barman-cloud --tail=60 2>&1 | tail -60 || true
  # A pod stuck in ContainerCreating logs nothing; describe + events reveal the real
  # cause (e.g. a cert-manager secret volume still being issued -> FailedMount).
  kubectl -n cnpg-system describe pod -l app=barman-cloud 2>&1 | tail -40 || true
  kubectl -n cnpg-system get events --sort-by=.lastTimestamp 2>/dev/null | tail -30 || true
  echo "--- CNPG recovery/job pod logs ($NS) ---"
  for p in $(kubectl -n "$NS" get pods --no-headers 2>/dev/null \
    | awk '$1 ~ /-recovery|-full-recovery|object-restore/ {print $1}'); do
    echo "### $p ###"
    kubectl -n "$NS" logs "$p" --all-containers --tail=120 2>&1 | tail -120 || true
  done
  echo "--- logs of non-Ready pods ($NS) ---"
  for p in $(kubectl -n "$NS" get pods \
    -o jsonpath='{range .items[?(@.status.containerStatuses[0].ready==false)]}{.metadata.name}{"\n"}{end}' 2>/dev/null); do
    echo "### $p ###"
    kubectl -n "$NS" logs "$p" --all-containers --tail=80 2>&1 | tail -80 || true
  done
}

# `helmfile sync` blocks silently on `helm --wait` (up to 900s/release). Run it in
# the background with a watchdog that prints a per-pod-phase heartbeat and aborts
# IMMEDIATELY on an unrecoverable pod state (image pull errors, container start
# errors, or a pod stuck in CrashLoopBackOff) — turning a 15-minute silent timeout
# into a ~15-second, actionable failure. Reused for the initial sync and `restore`.
#
# A plain progress-deadline timeout (NOT one of the fail-fast states) is retried
# once: on a cold, CPU-starved single-node runner a Deployment that mounts a
# cert-manager-issued secret created in the same release (e.g. the barman-cloud
# plugin's TLS) can sit in ContainerCreating past helm's deadline while the secret
# is still being issued. `helmfile sync` is idempotent — the second pass finds the
# secret present and the pod comes up at once. Unrecoverable states fail fast and
# are never retried.
provision_with_watchdog() {
  local desc="$1"; shift
  local attempt rc
  for attempt in 1 2; do
    [ "$attempt" -eq 1 ] || echo "==> retrying provisioning (attempt $attempt) — previous sync timed out"
    rc=0
    _provision_attempt "$desc" "$@" || rc=$?
    case "$rc" in
      0) return 0 ;;
      2) exit 1 ;;   # unrecoverable, diagnosed above — do not retry
    esac
    # rc>=1: plain sync failure (e.g. progress deadline) — retry once, then give up.
  done
  echo "==> helmfile sync still failing after $attempt attempts (exit $rc)"
  exit 1
}

# One provisioning attempt. Returns 0 on success, 2 on an unrecoverable state that
# must NOT be retried, or the sync's own exit code (>=1) on a plain timeout/failure.
_provision_attempt() {
  # Run an arbitrary provisioning command ("$@") in the background while monitoring
  # pods, so a wedged bring-up fails fast instead of waiting out the helm timeout.
  local desc="$1"; shift
  echo "==> provisioning the stack ($desc)"
  local log; log="$(mktemp)"
  "$@" >"$log" 2>&1 &
  local pid=$!
  local empty=0
  while kill -0 "$pid" 2>/dev/null; do
    sleep 15
    local summary
    # --request-timeout bounds the call: if the API server is wedged (e.g. the node
    # is starved), kubectl returns empty fast instead of blocking for minutes, so the
    # empty-summary fail-fast below can actually trigger.
    summary="$(kubectl get pods -A --no-headers --request-timeout=10s 2>/dev/null \
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
      return 2
    fi
    if kubectl get pods -A --no-headers --request-timeout=10s 2>/dev/null | awk '
        $4 ~ /ImagePullBackOff|ErrImagePull|InvalidImageName|CreateContainerError|RunContainerError|CreateContainerConfigError/ {bad=1; print "  ! "$0}
        $4 == "CrashLoopBackOff" && ($5+0) >= 3 {bad=1; print "  ! "$0}
        # Several pods stuck in Error usually means a Job (e.g. CNPG recovery) is
        # failing and retrying — surface it instead of waiting for the helm timeout.
        $4 == "Error" {err++} END {if (err+0 >= 4) {print "  ! "err" pods in Error state"; bad=1}; exit bad ? 0 : 1}'; then
      echo "==> FAIL-FAST: unrecoverable pod state during sync (see above)"
      kill "$pid" 2>/dev/null || true
      cat "$log"
      return 2
    fi
  done
  local sync_rc=0
  wait "$pid" || sync_rc=$?
  cat "$log"
  [ "$sync_rc" -eq 0 ] && return 0
  echo "==> helmfile sync failed (exit $sync_rc)"
  return "$sync_rc"
}

wait_for_certs() {
  # cert-manager issues the certificates asynchronously after the ingresses are
  # created; give the named certs a moment before asserting (non-fatal — pytest
  # re-checks over HTTPS). Args: one or more Certificate names in $NS.
  echo "==> Waiting for the TLS certificates: $*"
  local c
  for c in "$@"; do
    kubectl -n "$NS" wait --for=condition=Ready "certificate/$c" --timeout=180s || true
  done
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

# --- ADR-032: PVC off-site backup/restore round-trip --------------------------
# Proves a document on a PVC survives backup -> wipe -> restore through the REAL
# pvc-backup chart (CronJob + restore Job) and the crypt off-site store, WITHOUT
# booting the heavy Grist pod: a fixture `grist-persist` PVC stands in for Grist's
# /persist, holding a sentinel under /persist/docs. Shared by run-e2e.sh (full
# suite) and run-pvc-backup-e2e.sh (isolated, fast). The caller sets $NS + KUBECONFIG
# and ensures the off-site store + backup-s3-credentials secret exist; OFFSITE_* env
# vars select the store (default: the in-cluster garage-backup).
GRIST_PVC="${GRIST_PVC:-grist-persist}"
GRIST_DOC="${GRIST_DOC:-docs/e2e-grist-doc.txt}"
GRIST_DOC_CONTENT="${GRIST_DOC_CONTENT:-ownsuite-e2e-grist-document-fixture}"

grist_pvc_make() {
  # (Re)create the fixture PVC the round-trip mounts.
  kubectl -n "$NS" apply -f - <<EOF >/dev/null
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ${GRIST_PVC}
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 1Gi
EOF
}

# A tiny pod that mounts the PVC, so we can write/read the sentinel without Grist.
grist_pvc_exec() {
  local name="$1" snippet="$2"
  # The snippet is concatenated raw into this JSON, so a stray " in it would yield
  # invalid JSON and a cryptic "Invalid JSON Patch" from kubectl, 8 min into the run.
  # Validate up front so a bad snippet fails instantly with a clear, named message.
  local overrides='{"spec":{"containers":[{"name":"sh","image":"busybox:1.37","command":["/bin/sh","-ceu"],"args":["'"$snippet"'"],"volumeMounts":[{"name":"d","mountPath":"/persist"}]}],"volumes":[{"name":"d","persistentVolumeClaim":{"claimName":"'"$GRIST_PVC"'"}}]}}'
  printf '%s' "$overrides" | python3 -c 'import json,sys; json.load(sys.stdin)' \
    || { echo "BUG: grist_pvc_exec snippet '$name' breaks the pod overrides JSON (no \" allowed): $snippet" >&2; exit 1; }
  kubectl -n "$NS" delete pod "$name" --ignore-not-found >/dev/null 2>&1 || true
  kubectl -n "$NS" run "$name" --restart=Never --image=busybox:1.37 \
    --overrides="$overrides" >/dev/null
  kubectl -n "$NS" wait --for=condition=Ready pod/"$name" --timeout=60s >/dev/null 2>&1 || true
  kubectl -n "$NS" wait --for=jsonpath='{.status.phase}'=Succeeded pod/"$name" --timeout=60s
  kubectl -n "$NS" logs "$name"
  kubectl -n "$NS" delete pod "$name" --ignore-not-found >/dev/null 2>&1 || true
}

# Render the pvc-backup chart for the fixture PVC and apply only its batch objects
# (CronJob for $1=backup, restore Job for $1=restore — gated by restore.enabled).
pvc_backup_apply() {
  local mode="$1"
  helm template pvc-backup-e2e helmfile/charts/pvc-backup \
    --namespace "$NS" \
    --set image.tag="$(sed -nE 's/^[[:space:]]*rclone:[[:space:]]*"([^"]+)".*/\1/p' helmfile/versions/versions.yaml | head -1)" \
    --set restore.enabled="$([ "$mode" = restore ] && echo true || echo false)" \
    --set offsite.endpoint="${OFFSITE_ENDPOINT:-http://garage-backup.${NS}.svc.cluster.local:3900}" \
    --set offsite.region="${OFFSITE_REGION:-garage}" \
    --set offsite.bucket="${OFFSITE_BUCKET:-ownsuite-backups}" \
    --set 'volumes[0].pvcName='"$GRIST_PVC" --set 'volumes[0].subPath=' \
    | kubectl -n "$NS" apply -f -
}

# The full round-trip: seed -> backup -> wipe -> restore -> assert byte-identical.
pvc_backup_roundtrip() {
  echo "==> ADR-032: creating a fixture ${GRIST_PVC} PVC + seeding a document sentinel"
  grist_pvc_make
  grist_pvc_exec grist-seed \
    "mkdir -p /persist/docs && printf '%s' '${GRIST_DOC_CONTENT}' > /persist/${GRIST_DOC} && ls -l /persist/docs"

  echo "==> ADR-032: backing the PVC up off-site (encrypted, via the pvc-backup chart)"
  pvc_backup_apply backup
  kubectl -n "$NS" delete job pvc-backup-e2e --ignore-not-found >/dev/null 2>&1 || true
  kubectl -n "$NS" create job --from=cronjob/pvc-backup-${GRIST_PVC} pvc-backup-e2e >/dev/null
  wait_job pvc-backup-e2e 180
  # The completed backup pod still references the PVC, so the pvc-protection finalizer
  # would hold it in Terminating forever on the wipe below. Drop the job (and its pod)
  # first; --cascade=foreground blocks until the pod is actually gone.
  kubectl -n "$NS" delete job pvc-backup-e2e --cascade=foreground --ignore-not-found

  echo "==> ADR-032: WIPING the PVC (simulating server loss), then restoring"
  kubectl -n "$NS" delete pvc "$GRIST_PVC" --ignore-not-found
  grist_pvc_make
  # Confirm the wipe took: the sentinel must be gone before the restore proves anything.
  grist_pvc_exec grist-check-empty "test ! -e /persist/${GRIST_DOC} && echo 'PVC is empty (sentinel gone)'"
  # The chart's restore Job is a helm post-install hook (annotations), which `kubectl
  # apply` keeps as a plain Job — so it runs immediately here.
  pvc_backup_apply restore
  wait_job pvc-restore-${GRIST_PVC} 180

  echo "==> ADR-032: asserting the Grist document SURVIVED the PVC backup/restore"
  # No double quotes in the snippet: it is concatenated into the kubectl --overrides
  # JSON, where a literal " would break the payload (-> "Invalid JSON Patch").
  grist_pvc_exec grist-verify \
    "grep -qxF '${GRIST_DOC_CONTENT}' /persist/${GRIST_DOC} && echo 'GRIST DOCUMENT SURVIVED' || { echo 'MISSING/CORRUPT'; exit 1; }"
}
