"""`suite user add|disable|passwd <email>` (Phase 5).

JIT provisioning (ADR-005): creating the Keycloak user **once** grants access to
every enabled app on its first login — there is no per-app provisioning call. The
admin password is derived from the seed (ADR-012), never read from the cluster;
Keycloak's admin API is reached over the in-cluster HTTP service through the
existing SSH tunnel (ADR-014) + a short-lived kubectl port-forward.
"""

from __future__ import annotations

import contextlib
import os
import secrets
import shutil
import subprocess
import time

from . import config, tunnel
from .errors import SuiteError
from .keycloak import KeycloakAdmin

NS = "ownsuite"
REALM = "ownsuite"
KC_SERVICE = "keycloak-keycloakx-http"
KC_PORT = 80
ADMIN_USER = "admin"


def run(args):
    cfg = config.load_env(args.env_file)
    ssh = getattr(args, "ssh", None) or cfg.get("OWNSUITE_SERVER_SSH", "")
    seed = os.environ.get("OWNSUITE_SECRET_SEED")
    if not seed:
        raise SuiteError(
            "OWNSUITE_SECRET_SEED must be exported — it is never stored (ADR-012)."
        )
    _preflight(args, ssh)
    admin_password = config.derive_secret(seed, "keycloak-admin")

    tunnel_ctx = (
        contextlib.nullcontext()
        if args.no_tunnel or not ssh
        else tunnel.tunnel(ssh)
    )
    with tunnel_ctx, _port_forward(KC_SERVICE, args.local_port, KC_PORT) as port:
        kc = KeycloakAdmin(f"http://127.0.0.1:{port}", REALM, ADMIN_USER, admin_password)
        _dispatch(args, kc)


def _dispatch(args, kc):
    email = args.email
    if args.action == "add":
        user_id, created = kc.ensure_user(
            email,
            first_name=getattr(args, "first_name", None),
            last_name=getattr(args, "last_name", None),
        )
        password, generated = _resolve_password(args)
        kc.set_password(user_id, password, temporary=not args.permanent)
        print(f"  {'created' if created else 'updated'} Keycloak user {email}")
        print("  JIT: this user reaches every enabled app on first login (ADR-005).")
        if generated:
            _password_banner(email, password, temporary=not args.permanent)
    elif args.action == "passwd":
        user = _require_user(kc, email)
        password, generated = _resolve_password(args)
        kc.set_password(user["id"], password, temporary=not args.permanent)
        print(f"  reset password for {email}")
        if generated:
            _password_banner(email, password, temporary=not args.permanent)
    elif args.action == "disable":
        user = _require_user(kc, email)
        kc.set_enabled(user["id"], False)
        print(f"  disabled Keycloak user {email} (access revoked across all apps)")
    else:  # pragma: no cover - argparse enforces the choices
        raise SuiteError(f"unknown user action: {args.action}")


def _require_user(kc, email):
    user = kc.find_user(email)
    if not user:
        raise SuiteError(f"no Keycloak user with email {email}")
    return user


def _resolve_password(args):
    """Return (password, generated?). An explicit --password is used as-is; otherwise
    a strong one is generated and shown once."""
    if args.password:
        return args.password, False
    return secrets.token_urlsafe(12), True


@contextlib.contextmanager
def _port_forward(service, local_port, remote_port, *, namespace=NS):
    """kubectl port-forward to the in-cluster service over the tunnel. Reuses an
    already-open local port (so a running `make tunnel`/port-forward isn't stacked)."""
    if tunnel.port_open(local_port):
        print(f"  reusing existing port-forward on :{local_port}")
        yield local_port
        return
    print(f"  port-forwarding svc/{service} -> :{local_port}")
    proc = subprocess.Popen(
        ["kubectl", "-n", namespace, "port-forward", f"svc/{service}",
         f"{local_port}:{remote_port}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(30):
            if tunnel.port_open(local_port):
                break
            time.sleep(1)
        else:
            raise SuiteError(f"kubectl port-forward to {service} never opened :{local_port}")
        yield local_port
    finally:
        proc.terminate()


def _preflight(args, ssh):
    tools = ["kubectl"]
    if not args.no_tunnel and ssh:
        tools.append("ssh")
    missing = [t for t in tools if not shutil.which(t)]
    if missing:
        raise SuiteError(f"missing required tools on PATH: {', '.join(missing)}")


def _password_banner(email, password, *, temporary):
    note = (
        "temporary — the user must set their own at first login"
        if temporary else "permanent"
    )
    print(
        "\n" + "=" * 70 + "\n"
        f"INITIAL PASSWORD for {email} ({note}). Shown once; hand it over securely.\n\n"
        f"  {password}\n"
        + "=" * 70
    )
