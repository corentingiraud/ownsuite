#!/usr/bin/env bash
# Boot ONE app (grist | projects | messages | docs | drive | meet | tchap) on its OWN throwaway k3d
# cluster and assert its definition of done: it converges, its UI/API is reachable
# over HTTPS with SSO wired, plus an app-appropriate read-back (messages: local mail
# loopback; docs: SSO create + read-back; drive: JIT /users/me). One app per cluster
# so they never compete for RAM — this is the SINGLE source of each app's boot DoD,
# Docs/Drive included. The full suite (run-e2e.sh) is platform + installer +
# backup/restore only and no longer re-asserts any app.
#
# Runs in apps-e2e.yml (a matrix, one job per app) and locally via
# `make test-app APP=<grist|projects|messages|docs|drive|meet|tchap>`.
set -euo pipefail

cd "$(dirname "$0")/../.."  # repo root
. helmfile/tests/lib.sh     # provision_with_watchdog, wait_for_certs, dump_failure_diagnostics

APP="${1:-${OWNSUITE_E2E_APP:-}}"
case "$APP" in
  grist|projects|messages|docs|drive|meet|tchap) ;;
  *) echo "usage: $0 <grist|projects|messages|docs|drive|meet|tchap>" >&2; exit 2 ;;
esac

CLUSTER="${OWNSUITE_E2E_CLUSTER:-ownsuite-app-$APP}"
HELMFILE="helmfile/helmfile.yaml.gotmpl"
NS=ownsuite
IMAGE_ARGS=()
[ -n "${OWNSUITE_K3S_IMAGE:-}" ] && IMAGE_ARGS=(--image "$OWNSUITE_K3S_IMAGE")

export OWNSUITE_DOMAIN="${OWNSUITE_DOMAIN:-ownsuite.localhost}"
export OWNSUITE_TLS_ISSUER="selfsigned"
export OWNSUITE_SECRET_SEED="${OWNSUITE_SECRET_SEED:-$(openssl rand -hex 24)}"
# Self-hosted Garage so the run is hermetic (messages needs its media bucket; the
# bootstrap creates only the enabled apps' buckets).
export OWNSUITE_OBJECT_STORAGE_MODE="${OWNSUITE_OBJECT_STORAGE_MODE:-garage}"
# Only the app under test: Docs/Drive off so one app owns the runner's RAM.
export OWNSUITE_APP_DOCS=false OWNSUITE_APP_DRIVE=false
export OWNSUITE_APP_GRIST=false OWNSUITE_APP_PROJECTS=false OWNSUITE_APP_MESSAGES=false
export OWNSUITE_APP_MEET=false OWNSUITE_APP_TCHAP=false
# Direct-access grant on this app's OIDC client so the test can mint a bearer token
# for the API read-back (messages) without a browser — CI only, as in run-e2e.sh.
export OWNSUITE_KC_DIRECT_GRANTS=true
# Backups are out of scope for a per-app boot test (covered by run-e2e.sh).
export OWNSUITE_BACKUP_ENABLED=false
export OWNSUITE_E2E_APP="$APP"

# TLS certs to wait for before asserting (defaults to the app's own <app>-tls; Tchap
# has per-host certs — Element Web, Synapse and MAS each get their own).
CERTS=("$APP-tls")
case "$APP" in
  grist) export OWNSUITE_APP_GRIST=true ;;
  projects) export OWNSUITE_APP_PROJECTS=true ;;
  tchap)
    # Brings up the ess-helm matrix-stack (Synapse + MAS + Element Web + well-known,
    # all gated on apps.tchap.enabled). The DoD is a boot smoke: both CNPG databases
    # applied, Synapse answers /_matrix/client/versions, and the web client is reachable
    # over HTTPS. The full SSO login is NOT asserted here — MAS cannot skip TLS
    # verification on upstream OIDC discovery, so the MAS->Keycloak leg can't complete
    # against the self-signed CI issuer (it works in production with Let's Encrypt).
    export OWNSUITE_APP_TCHAP=true
    CERTS=(tchap-web-tls synapse-tls mas-tls)
    ;;
  meet)
    # Brings up meet + livekit + livekit-egress (all gated on apps.meet.enabled). The
    # DoD is a boot smoke: DB applied, backend + livekit pods Ready, UI bounces to SSO,
    # and the backend mints a LiveKit room token (proves backend<->LiveKit auth). Real
    # media/recording (hostNetwork UDP, headless-Chrome egress) is not exercised here.
    export OWNSUITE_APP_MEET=true
    # Layer the CI-only LiveKit override (values/livekit-ci.yaml.gotmpl): drop
    # hostNetwork + external-IP so LiveKit converges and tears down cleanly on k3d.
    export OWNSUITE_MEET_E2E=true
    # The token DoD mints a bearer for the seeded realm user `docs-tester` (meet's OIDC
    # client, direct-access grant), same seam docs uses. Seed it.
    export OWNSUITE_KC_SEED_TEST_USER=true
    ;;
  docs)
    export OWNSUITE_APP_DOCS=true
    # Docs' DoD (SSO create + read-back) mints a token for the seeded realm user
    # `docs-tester` via the direct-access grant — same path run-e2e.sh uses. Seed it.
    export OWNSUITE_KC_SEED_TEST_USER=true
    ;;
  drive)
    export OWNSUITE_APP_DRIVE=true
    # Drive's DoD (JIT /users/me) mints a token for a user created through the real
    # CLI, proving just-in-time provisioning. A PERMANENT password lets the test mint
    # a token via the direct-access grant (a temporary one forces a reset first).
    export OWNSUITE_E2E_USER="${OWNSUITE_E2E_USER:-drive-tester@$OWNSUITE_DOMAIN}"
    export OWNSUITE_E2E_USER_PW="${OWNSUITE_E2E_USER_PW:-$(openssl rand -hex 16)}"
    ;;
  messages)
    export OWNSUITE_APP_MESSAGES=true
    # A mailbox user created through the real CLI; its mailbox is auto-provisioned on
    # first login (MailDomain.oidc_autojoin). A PERMANENT password lets the test mint
    # a token via the direct-access grant. Email domain == mail domain (the base
    # domain) so autojoin matches.
    export OWNSUITE_E2E_USER="${OWNSUITE_E2E_USER:-msg-tester@$OWNSUITE_DOMAIN}"
    export OWNSUITE_E2E_USER_PW="${OWNSUITE_E2E_USER_PW:-$(openssl rand -hex 16)}"
    ;;
esac

cleanup() {
  rc=$?
  [ "$rc" != "0" ] && { echo "(exit $rc)"; dump_failure_diagnostics; }
  if [ "${OWNSUITE_E2E_KEEP:-0}" != "1" ]; then
    echo "==> Deleting k3d cluster '$CLUSTER'"
    # Guard the teardown: LiveKit's hostNetwork + host media ports can wedge
    # `k3d cluster delete` (the reason Meet was descoped), so cap it with `timeout` on
    # systems that have it (CI/Linux) — never let a wedged delete hang the job. macOS
    # has no `timeout`; fall back to a plain delete there.
    if command -v timeout >/dev/null 2>&1; then
      timeout 60 k3d cluster delete "$CLUSTER" >/dev/null 2>&1 || true
    else
      k3d cluster delete "$CLUSTER" >/dev/null 2>&1 || true
    fi
  fi
}
trap cleanup EXIT

echo "==> Creating k3d cluster '$CLUSTER' for app '$APP' (${OWNSUITE_K3S_IMAGE:-k3d default})"
k3d cluster create "$CLUSTER" \
  "${IMAGE_ARGS[@]}" \
  --port "80:80@loadbalancer" \
  --port "443:443@loadbalancer" \
  --wait --timeout 180s

KUBECONFIG="$(k3d kubeconfig write "$CLUSTER")"
export KUBECONFIG

# Plain `helmfile sync` (not `suite install`, which verifies Docs over HTTPS — Docs is
# off here). pytest resolves each host per-request with `curl --resolve`, so no
# /etc/hosts entry is needed.
provision_with_watchdog "app=$APP, issuer=$OWNSUITE_TLS_ISSUER" \
  helmfile -f "$HELMFILE" sync
wait_for_certs "${CERTS[@]}"

# Apps whose DoD authenticates as a CLI-created user (drive: JIT /users/me; messages:
# the mailbox autojoins on first login) get that user provisioned through the real CLI.
# The CLI reads suite.yaml (ADR-042) — hand it a minimal one in a temp dir.
if [ -n "${OWNSUITE_E2E_USER:-}" ]; then
  echo "==> Creating the test user via the suite CLI (JIT provisioning on first login)"
  export OWNSUITE_CONFIG="$(mktemp -d)/suite.yaml"
  printf 'domain: %s\ntls: selfsigned\napps:\n  %s: {}\n' \
    "$OWNSUITE_DOMAIN" "$APP" > "$OWNSUITE_CONFIG"
  python3 -m suite user add "$OWNSUITE_E2E_USER" \
    --password "$OWNSUITE_E2E_USER_PW" --permanent --no-tunnel
fi

echo "==> Asserting the '$APP' definition of done"
python3 -m pytest helmfile/tests/test_apps.py -v
