# Users

Provisioning is **one identity in Keycloak**, just-in-time into every app (ADR-005): create a
user once and they reach Docs, Drive — and any future app — on their first login. No per-app
step ([ADR-023](../understand/decisions.md#adr-023-user-provisioning-suite-user-admin-rest-over-the-tunnel-jit)).

```bash
set -a && source .env && set +a       # OWNSUITE_SECRET_SEED + OWNSUITE_SERVER_SSH

suite user add alice@assoc.org        # create + show a one-time temporary password
suite user passwd alice@assoc.org     # reset the password
suite user disable alice@assoc.org    # deactivate (revokes access to all apps at once)
```

> **Definition of done (Phase 5):** `suite user add firstname@assoc.org` and that person has
> Docs **and** Drive immediately — proven at the token level in CI.

## How it reaches Keycloak

The CLI talks the Keycloak **admin REST API** to the in-cluster service over the existing SSH
tunnel ([ADR-014](../understand/decisions.md#adr-014-operator-control-plane-local-workstation-ssh-tunnel))
plus a short-lived `kubectl port-forward` — admin traffic never crosses the public
`auth.{domain}` endpoint. The admin password is **derived from your seed** (id `keycloak-admin`,
[ADR-012](../understand/decisions.md#adr-012-secrets-derived-from-a-single-secretseed-via-helm-templating)),
so the only secret you need is the `OWNSUITE_SECRET_SEED` you already guard. With a tunnel
already open (or an ambient `KUBECONFIG`) add `--no-tunnel`.

## Flags

- `--password` — set an explicit password instead of a generated one (`add`, `passwd`).
- `--permanent` — don't force a password change at next login (default is temporary).
- `--ssh user@host` — server SSH target if not in `.env`; `--no-tunnel` to skip the tunnel.

Generated passwords are shown **once** — hand them over securely. Disabling a user is the kill
switch: it deactivates the single identity, so every app rejects them at once.
