# Users

Adding someone is **one command**. You create them once, and they can sign in to Docs, Drive
— and any other app you've enabled — the first time they log in. There's no per-app setup.

```bash
suite user add alice@assoc.org        # create + show a one-time temporary password
suite user passwd alice@assoc.org     # reset the password
suite user disable alice@assoc.org    # deactivate (revokes access to all apps at once)
```

> **The result:** `suite user add firstname@assoc.org` and that person can reach every app
> you've enabled the first time they log in — if you enabled Docs **and** Drive, that's
> both of them immediately. Tested in CI.

## How it connects

The command talks to Keycloak (the login system) privately, over the same SSH tunnel you
use to manage the server — admin traffic never goes over the public internet. The server
target comes from `suite.yaml` (or the machine state written by provisioning). The admin
password is **derived from your seed**, so the only secret you ever need to guard is your
`OWNSUITE_SECRET_SEED` — use the exported value, or let the command prompt you for it. If
a tunnel is already open (or you have a working `KUBECONFIG`), add `--no-tunnel`.

## Flags

- `--password` — set an explicit password instead of a generated one (`add`, `passwd`).
- `--permanent` — don't force a password change at next login (default is temporary).
- `--first-name` / `--last-name` — set the user's name on `add` (else derived from the username).
- `--local-port` — local port for the managed tunnel (`add`, `passwd`, `disable`; default `8081`).
- `--no-tunnel` — skip the managed tunnel (one is already open, or `KUBECONFIG` works).

Generated passwords are shown **once** — hand them over securely. Disabling a user is the kill
switch: it deactivates the single identity, so every app rejects them at once.
