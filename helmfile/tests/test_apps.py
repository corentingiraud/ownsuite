"""Per-app boot definition-of-done for the optional apps (Grist, Projects, Mailbox).

One app per fresh k3d cluster (see run-app-e2e.sh), selected by OWNSUITE_E2E_APP, so
the heavy optional apps never compete for RAM. The Docs+Drive core stays proven by
test_platform.py; this closes the optional-app gap: each app converges, its UI is
reachable through Traefik+TLS with SSO wired, and — for messages — a message
delivered to a local mailbox reads back via the API.

Shells out to kubectl/curl with the ambient KUBECONFIG; reuses the token/HTTP
helpers from test_platform (same directory, same conventions).
"""

import json
import os
import subprocess

import pytest

# test_platform sits next to this file; pytest puts the test dir on sys.path.
from test_platform import (
    AUTH_HOST,
    DOMAIN,
    NAMESPACE,
    curl,
    kubectl,
    password_token,
    retry,
)

APP = os.environ.get("OWNSUITE_E2E_APP", "")
# Mailbox user created by run-app-e2e.sh before this runs (CLI-provisioned).
CLI_USER = os.environ.get("OWNSUITE_E2E_USER", "")
CLI_USER_PW = os.environ.get("OWNSUITE_E2E_USER_PW", "")


def only(app):
    return pytest.mark.skipif(APP != app, reason=f"runs only for app={app} (got {APP!r})")


def app_host(app):
    return f"{app}.{DOMAIN}"


def _db_applied(name):
    applied = kubectl(
        "-n", NAMESPACE, "get", "database", name, "-o", "jsonpath={.status.applied}"
    ).stdout.strip()
    assert applied == "true", f"Database {name} not applied ({applied!r})"


def _pod_ready(name_label, component=None):
    sel = f"app.kubernetes.io/name={name_label}"
    if component:
        sel += f",app.kubernetes.io/component={component}"
    out = kubectl(
        "-n", NAMESPACE, "get", "pods", "-l", sel,
        "-o", 'jsonpath={.items[*].status.conditions[?(@.type=="Ready")].status}',
    ).stdout
    assert "True" in out, f"{sel} pod not Ready ({out!r})"


def _ui_reachable(host):
    """Follow redirects through Traefik+TLS; a final 200 proves the app booted and its
    UI is reachable end to end — whether it serves its SPA or bounces an
    unauthenticated visitor to the Keycloak login page. Resolves both the app host and
    the auth host to the k3d loadbalancer so a bounce to SSO still completes. Returns
    the landing URL so callers can assert the SSO bounce when the app does one."""
    def fetch():
        out = subprocess.run(
            ["curl", "-ksS", "-L", "-o", "/dev/null", "-w", "%{http_code} %{url_effective}",
             "--resolve", f"{host}:443:127.0.0.1",
             "--resolve", f"{AUTH_HOST}:443:127.0.0.1",
             f"https://{host}/"],
            capture_output=True, text=True, check=True,
        ).stdout.split(maxsplit=1)
        code, url = out[0], (out[1] if len(out) > 1 else "")
        assert code == "200", f"{host}: UI not reachable (status {code}, landed {url})"
        return url
    return retry(fetch, attempts=40, delay=3)


# --- Grist (optional) -------------------------------------------------------


@only("grist")
def test_grist_database_applied():
    _db_applied("grist")


@only("grist")
def test_grist_pod_ready():
    _pod_ready("grist")


@only("grist")
def test_grist_status_endpoint():
    """Grist's /status health endpoint answers 200 over HTTPS (direct boot proof)."""
    host = app_host("grist")

    def fetch():
        out = curl(host, f"https://{host}/status")
        assert "grist" in out.lower(), out[:200]

    retry(fetch, attempts=40, delay=3)


@only("grist")
def test_grist_ui_bounces_to_sso():
    """With GRIST_FORCE_LOGIN, an unauthenticated visit lands on the Keycloak login
    page — proving the boot AND that single sign-on is wired end to end."""
    url = _ui_reachable(app_host("grist"))
    assert AUTH_HOST in url, f"grist did not bounce to the SSO login page: {url}"


# --- Projects (optional) ----------------------------------------------------


@only("projects")
def test_projects_database_applied():
    _db_applied("projects")


@only("projects")
def test_projects_pod_ready():
    _pod_ready("projects")


@only("projects")
def test_projects_ui_reachable():
    """Projects answers 200 over HTTPS through Traefik (its SPA, with SSO enforced).
    Its OIDC redirect may happen client-side, so we assert reachability, not the
    bounce target."""
    _ui_reachable(app_host("projects"))


# --- Mailbox (optional, advanced) -------------------------------------------


@only("messages")
def test_messages_database_applied():
    _db_applied("messages")


@only("messages")
def test_messages_pods_ready():
    """The four serving components reach Ready; the worker (no port/probe) is Running."""
    for component in ("backend", "frontend", "mta-in", "mta-out"):
        _pod_ready("messages", component=component)
    phase = kubectl(
        "-n", NAMESPACE, "get", "pods",
        "-l", "app.kubernetes.io/name=messages,app.kubernetes.io/component=worker",
        "-o", "jsonpath={.items[*].status.phase}",
    ).stdout
    assert "Running" in phase, f"messages worker not Running ({phase!r})"


@only("messages")
def test_messages_webmail_reachable():
    """The webmail frontend answers its health endpoint over HTTPS through Traefik."""
    host = app_host("messages")

    def fetch():
        curl(host, f"https://{host}/__lbheartbeat__")

    retry(fetch, attempts=40, delay=3)


@only("messages")
@pytest.mark.skipif(
    not (CLI_USER and CLI_USER_PW),
    reason="needs a CLI-created mailbox user (OWNSUITE_E2E_USER/_PW)",
)
def test_messages_local_delivery_loopback():
    """The mailbox definition of done: a message delivered to a local mailbox reads
    back via the API — no external relay involved.

    1. A bearer-authenticated /users/me/ call JIT-creates the Django user and, because
       the MailDomain has oidc_autojoin=True, auto-provisions the mailbox (the same JIT
       path `suite user add` relies on).
    2. Inject a message over SMTP to mta-in:25 from inside the cluster — the real
       inbound path (mta-in signs an MDA JWT with the shared secret and POSTs the raw
       mail to the backend). Run it from the backend pod, which has python3's stdlib
       smtplib and reaches the mta-in Service.
    3. Read it back through the threads API → proves mta-in -> MDA -> mailbox delivery.
    """
    host = app_host("messages")
    api = f"https://{host}/api/v1.0"

    def me():
        token = password_token("messages", CLI_USER, CLI_USER_PW)
        out = curl(host, f"{api}/users/me/", "-H", f"Authorization: Bearer {token}")
        data = json.loads(out)
        assert (data.get("email") or "").lower() == CLI_USER.lower(), data
        return token

    token = retry(me)
    auth = f"Authorization: Bearer {token}"

    def mailbox_id():
        out = curl(host, f"{api}/mailboxes/", "-H", auth)
        payload = json.loads(out)
        items = payload.get("results", payload) if isinstance(payload, dict) else payload
        assert items, f"no mailbox auto-provisioned for {CLI_USER}: {payload}"
        return items[0]["id"]

    mbox = retry(mailbox_id)

    subject = f"ownsuite-loopback-{mbox[:8]}"
    inject = (
        "import smtplib, email.message\n"
        "m = email.message.EmailMessage()\n"
        "m['From'] = 'sender@external.example'\n"
        f"m['To'] = '{CLI_USER}'\n"
        f"m['Subject'] = '{subject}'\n"
        "m.set_content('ownsuite local delivery loopback')\n"
        "s = smtplib.SMTP('messages-mta-in', 25, timeout=30)\n"
        f"s.sendmail('sender@external.example', ['{CLI_USER}'], m.as_bytes())\n"
        "s.quit()\n"
        "print('injected')\n"
    )

    def inject_mail():
        res = kubectl(
            "-n", NAMESPACE, "exec", "deploy/messages-backend", "--",
            "python3", "-c", inject,
        )
        assert "injected" in res.stdout, res.stdout + res.stderr

    retry(inject_mail, attempts=10, delay=3)

    def delivered():
        out = curl(host, f"{api}/threads/?mailbox_id={mbox}", "-H", auth)
        payload = json.loads(out)
        items = payload.get("results", payload) if isinstance(payload, dict) else payload
        subjects = [t.get("subject") for t in items]
        assert subject in subjects, f"delivered message not found; got {subjects}"

    retry(delivered, attempts=40, delay=3)
