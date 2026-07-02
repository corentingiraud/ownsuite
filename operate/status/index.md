# Status & monitoring

`suite status` gives you a one-screen health check of a running OwnSuite. It reads the live state of the server and prints a plain summary — no extra software runs on the server, and no monitoring stack to install or maintain.

```
set -a && source .env && set +a       # OWNSUITE_SERVER_SSH (the seed is not needed here)

suite status
```

You get a readable block covering:

- **Node** — is the server itself ready.
- **Database** — the PostgreSQL cluster, how many instances are ready, and the time of its last successful backup.
- **Certificates** — every HTTPS certificate and whether it is valid and issued.
- **Off-site backup** — whether the off-site copy job is configured and running, and whether its most recent run succeeded.
- **Apps** — for each app you've enabled (Docs, Drive, and any of Grist, Projects, Mailbox), how many of its pods are up and ready.

Each line is marked `OK` or `FAIL`, so a quick glance tells you whether everything is healthy or where to look. Only the apps you've turned on are listed.

## How it connects

Like the other admin commands, `suite status` talks to the server privately over the same SSH tunnel you use to manage it — nothing is exposed publicly. If a tunnel is already open (or you have a working `KUBECONFIG`), add `--no-tunnel`. Point it at a different server with `--ssh user@host` if it isn't in your `.env`.

It's read-only: it never changes anything, so it's safe to run as often as you like — before and after an [upgrade](https://corentingiraud.github.io/ownsuite/operate/upgrade/index.md), or any time you want to confirm the suite is well.
