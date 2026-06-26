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
  echo "--- barman-cloud plugin logs (cnpg-system) ---"
  kubectl -n cnpg-system logs -l app=barman-cloud --tail=60 2>&1 | tail -60 || true
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
provision_with_watchdog() {
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
      exit 1
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
