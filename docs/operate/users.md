# Users

Adding someone is **one command**. You create them once, and they can sign in to Docs, Drive
— and any other app you've enabled — the first time they log in. There's no per-app setup.

```bash
set -a && source .env && set +a       # OWNSUITE_SECRET_SEED + OWNSUITE_SERVER_SSH

suite user add alice@assoc.org        # create + show a one-time temporary password
suite user passwd alice@assoc.org     # reset the password
suite user disable alice@assoc.org    # deactivate (revokes access to all apps at once)
```

> **The result:** `suite user add firstname@assoc.org` and that person can reach every app
> you've enabled the first time they log in — with the recommended core (Docs **and** Drive)
> enabled, that's Docs and Drive immediately. Tested in CI.

## How it connects

The command talks to Keycloak (the login system) privately, over the same SSH tunnel you
use to manage the server — admin traffic never goes over the public internet. The admin
password is **derived from your seed**, so the only secret you ever need to guard is your
`OWNSUITE_SECRET_SEED`. If a tunnel is already open (or you have a working `KUBECONFIG`),
add `--no-tunnel`.

## Flags

- `--password` — set an explicit password instead of a generated one (`add`, `passwd`).
- `--permanent` — don't force a password change at next login (default is temporary).
- `--ssh user@host` — server SSH target if not in `.env`; `--no-tunnel` to skip the tunnel.

Generated passwords are shown **once** — hand them over securely. Disabling a user is the kill
switch: it deactivates the single identity, so every app rejects them at once.
