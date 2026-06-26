#!/usr/bin/env bash
# Boot ONE optional app (grist | projects | messages) on its OWN throwaway k3d
# cluster and assert it converges + its UI/SSO works — and, for messages, that a
# message delivered between two local mailboxes reads back via the API (the local
# mail-delivery loopback). One app per cluster so they never compete for RAM: that
# is exactly why the optional apps are kept OUT of the combined run-e2e.sh. The
# Docs+Drive core stays proven by run-e2e.sh; this fills the optional-app gap.
#
# Runs in nightly-apps-e2e.yml (a matrix, one job per app) and locally via
# `make test-app APP=<grist|projects|messages>`.
set -euo pipefail

cd "$(dirname "$0")/../.."  # repo root
. helmfile/tests/lib.sh     # provision_with_watchdog, wait_for_certs, dump_failure_diagnostics

APP="${1:-${OWNSUITE_E2E_APP:-}}"
case "$APP" in
  grist|projects|messages) ;;
  *) echo "usage: $0 <grist|projects|messages>" >&2; exit 2 ;;
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
# Direct-access grant on this app's OIDC client so the test can mint a bearer token
# for the API read-back (messages) without a browser — CI only, as in run-e2e.sh.
export OWNSUITE_KC_DIRECT_GRANTS=true
# Backups are out of scope for a per-app boot test (covered by run-e2e.sh).
export OWNSUITE_BACKUP_ENABLED=false
export OWNSUITE_E2E_APP="$APP"

case "$APP" in
  grist) export OWNSUITE_APP_GRIST=true ;;
  projects) export OWNSUITE_APP_PROJECTS=true ;;
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
    k3d cluster delete "$CLUSTER" >/dev/null 2>&1 || true
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
wait_for_certs "$APP-tls"

if [ "$APP" = "messages" ]; then
  echo "==> Creating a mailbox user via the suite CLI (JIT autojoin on first login)"
  python3 -m suite user add "$OWNSUITE_E2E_USER" \
    --password "$OWNSUITE_E2E_USER_PW" --permanent --no-tunnel
fi

echo "==> Asserting the '$APP' definition of done"
python3 -m pytest helmfile/tests/test_apps.py -v
