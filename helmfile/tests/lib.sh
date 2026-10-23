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
  # A Ready pod can still be the failing piece (e.g. Docs' yhub refusing websocket
  # upgrades with a 503): dump the recent logs of the app-under-test's Deployments
  # (run-app-e2e.sh exports OWNSUITE_E2E_APP; the platform e2e has none).
  if [ -n "${OWNSUITE_E2E_APP:-}" ]; then
    echo "--- logs of the ${OWNSUITE_E2E_APP} Deployments ($NS) ---"
    for d in $(kubectl -n "$NS" get deploy -o name 2>/dev/null \
      | grep "^deployment.apps/${OWNSUITE_E2E_APP}-" || true); do
      echo "### $d ###"
      kubectl -n "$NS" logs "$d" --all-containers --tail=80 2>&1 | tail -160 || true
    done
  fi
}

# retry <attempts> <cmd...>: run a command up to N times with a growing pause
# (10s, 20s, ...). For network-bound steps that flake on shared runners (helm repo
# index fetches, chart pulls). Returns the last exit code on final failure.
retry() {
  local max="$1"; shift
  local n rc=0
  for n in $(seq 1 "$max"); do
    rc=0
    "$@" && return 0 || rc=$?
    [ "$n" -lt "$max" ] || break
    echo "==> '$1' failed (exit $rc), retry $n/$((max - 1)) in $((n * 10))s"
    sleep $((n * 10))
  done
  return "$rc"
}

# create_cluster_with_retry <name> [k3d args...]: create a k3d cluster, export its
# KUBECONFIG and block on the API. On a k3d failure or an API that is not ready within
# ~2 min (apiserver EOF / unreachable on a starved runner), delete the cluster and
# start over, up to 3 attempts. Remembers name+args so provision_with_watchdog can
# recreate the cluster the same way.
_CLUSTER_NAME="" ; _CLUSTER_ARGS=()
create_cluster_with_retry() {
  _CLUSTER_NAME="$1"; shift
  _CLUSTER_ARGS=("$@")
  local attempt
  for attempt in 1 2 3; do
    [ "$attempt" -eq 1 ] || echo "==> recreating k3d cluster '$_CLUSTER_NAME' (attempt $attempt)"
    k3d cluster delete "$_CLUSTER_NAME" >/dev/null 2>&1 || true
    if k3d cluster create "$_CLUSTER_NAME" "${_CLUSTER_ARGS[@]}" --wait --timeout 180s; then
      KUBECONFIG="$(k3d kubeconfig write "$_CLUSTER_NAME")"
      export KUBECONFIG
      wait_for_cluster_api 60 && route_domain_to_ingress && return 0
    fi
  done
  echo "==> k3d cluster '$_CLUSTER_NAME' could not be brought up after 3 attempts"
  return 1
}

# In production every app host resolves to the server, so a pod calling
# https://<app>.<domain> hairpins into Traefik (Docs' yhub authorizes each websocket
# upgrade that way, against the backend). The e2e domain (`ownsuite.localhost`) has no
# real DNS: inside the cluster it resolves to nothing or to the pod's own loopback. Give
# the throwaway cluster the same hairpin: k3s imports the user-owned `coredns-custom`
# ConfigMap into its default server block, and the rewrite points `*.<domain>` at the
# bundled Traefik Service.
route_domain_to_ingress() {
  [ -n "${OWNSUITE_DOMAIN:-}" ] || return 0
  local pattern="${OWNSUITE_DOMAIN//./\\.}"
  echo "==> Resolving *.${OWNSUITE_DOMAIN} to Traefik inside the cluster"
  kubectl apply -f - <<EOF || return 1
apiVersion: v1
kind: ConfigMap
metadata:
  name: coredns-custom
  namespace: kube-system
data:
  ownsuite-hairpin.override: |
    rewrite name regex ^(.+\\.)?${pattern}\\.$ traefik.kube-system.svc.cluster.local answer auto
EOF
  # CoreDNS reads the import at startup: restart it when k3s has already deployed it.
  # Waiting on the rollout turns a rejected rule (CoreDNS crash-looping) into a loud
  # failure instead of a silent missing route.
  if kubectl -n kube-system get deploy coredns >/dev/null 2>&1; then
    kubectl -n kube-system rollout restart deploy/coredns >/dev/null || return 1
    kubectl -n kube-system rollout status deploy/coredns --timeout=180s || return 1
  fi
}

# k3d's `--wait` returns once the k3s server process is up, but the Kubernetes API
# can still answer 503 ("the server is currently unable to handle the request") for
# tens of seconds on a slow shared runner. `suite apply` hits the API on its very
# first call (a reachability preflight) and gives up the instant it 503s, so block on
# the API's own /readyz endpoint before provisioning against a freshly created cluster.
wait_for_cluster_api() {
  echo "==> Waiting for the cluster API to be ready"
  local i
  for i in $(seq 1 "${1:-60}"); do
    kubectl get --raw='/readyz' >/dev/null 2>&1 && return 0
    sleep 2
  done
  echo "==> cluster API never became ready"
  kubectl cluster-info 2>&1 | head -5 || true
  return 1
}

# `helmfile sync` blocks silently on `helm --wait` (up to 900s/release). Run it in
# the background with a watchdog that prints a per-pod-phase heartbeat and aborts
# IMMEDIATELY on an unrecoverable pod state (image pull errors, container start
# errors, or a pod stuck in CrashLoopBackOff) — turning a 15-minute silent timeout
# into a ~15-second, actionable failure. Reused for the initial sync and `restore`.
#
# A plain progress-deadline timeout (NOT one of the fail-fast states) is retried
# (up to 3 attempts): on a cold, CPU-starved single-node runner a Deployment that mounts a
# cert-manager-issued secret created in the same release (e.g. the barman-cloud
# plugin's TLS) can sit in ContainerCreating past helm's deadline while the secret
# is still being issued. `helmfile sync` is idempotent — the second pass finds the
# secret present and the pod comes up at once. Unrecoverable states fail fast and
# are never retried.
provision_with_watchdog() {
  local desc="$1"; shift
  local attempt rc
  # Pull helm repo indexes up front with backoff: a transient
  # `groundhog2k.github.io ... cannot be reached` otherwise aborts the whole sync.
  if [ -n "${HELMFILE:-}" ]; then
    retry 5 helmfile -f "$HELMFILE" repos || echo "==> helm repos still unreachable, syncing anyway"
  fi
  for attempt in 1 2 3; do
    [ "$attempt" -eq 1 ] || echo "==> retrying provisioning (attempt $attempt) — previous sync failed"
    rc=0
    _provision_attempt "$desc" "$@" || rc=$?
    case "$rc" in
      0) return 0 ;;
      2) exit 1 ;;   # unrecoverable, diagnosed above — do not retry
      3)
        # API unreachable: the killed sync may have left releases pending-install, so
        # only a brand-new cluster is a safe retry. Opt-in (OWNSUITE_E2E_RECREATE=1),
        # only for a first bring-up where the cluster holds nothing worth keeping.
        if [ "${OWNSUITE_E2E_RECREATE:-0}" = "1" ] && [ -n "$_CLUSTER_NAME" ]; then
          create_cluster_with_retry "$_CLUSTER_NAME" "${_CLUSTER_ARGS[@]}" || exit 1
        else
          exit 1
        fi ;;
    esac
    # rc>=1: plain sync failure (e.g. progress deadline) — retry, then give up.
  done
  echo "==> helmfile sync still failing after $attempt attempts (exit $rc)"
  exit 1
}

# One provisioning attempt. Returns 0 on success, 2 on an unrecoverable state that
# must NOT be retried, 3 on an unreachable API (cluster recreated when opted in), or the sync's own exit code (>=1) on a plain timeout/failure.
_provision_attempt() {
  # Run an arbitrary provisioning command ("$@") in the background while monitoring
  # pods, so a wedged bring-up fails fast instead of waiting out the helm timeout.
  local desc="$1"; shift
  echo "==> provisioning the stack ($desc)"
  local log; log="$(mktemp)"
  "$@" >"$log" 2>&1 &
  local pid=$!
  local empty=0 pull_bad=0
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
      return 3
    fi
    # Registry pulls flake on shared runners and kubelet retries them with backoff, so
    # an image-pull error only counts once it persisted ~2 min (8 checks); the other
    # states are never transient.
    if kubectl get pods -A --no-headers --request-timeout=10s 2>/dev/null \
        | grep -qE 'ImagePullBackOff|ErrImagePull'; then pull_bad=$((pull_bad + 1)); else pull_bad=0; fi
    if kubectl get pods -A --no-headers --request-timeout=10s 2>/dev/null | awk -v pull="$pull_bad" '
        $4 ~ /ImagePullBackOff|ErrImagePull/ && pull >= 8 {bad=1; print "  ! "$0}
        $4 ~ /InvalidImageName|CreateContainerError|RunContainerError|CreateContainerConfigError/ {bad=1; print "  ! "$0}
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
