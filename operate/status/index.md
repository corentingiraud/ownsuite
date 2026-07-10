# Status & monitoring

`suite status` gives you a one-screen health check of a running OwnSuite. It reads the live state of the server and prints a plain summary — no extra software runs on the server, and no monitoring stack to install or maintain.

```
suite status          # the seed is not needed here
```

You get a readable block covering:

- **Node** — is the server itself ready.
- **Database** — the PostgreSQL cluster, how many instances are ready, and the time of its last successful backup.
- **Certificates** — every HTTPS certificate and whether it is valid and issued.
- **Off-site backup** — whether the off-site copy job is configured and running, and whether its most recent run succeeded.
- **Apps** — for each app enabled in `suite.yaml` (Docs, Drive, and any other you've turned on), how many of its pods are up and ready.

Each line is marked `OK` or `FAIL`, so a quick glance tells you whether everything is healthy or where to look. Only the apps you've turned on are listed.

Three companions when a line needs a closer look:

- [`suite apps`](https://corentingiraud.github.io/ownsuite/reference/cli/#suite-apps) — the catalog: every available app, whether it is enabled / installed / healthy, and its URL.
- [`suite logs <app>`](https://corentingiraud.github.io/ownsuite/reference/cli/#suite-logs) — that app's pod logs (`--tail N` for more lines), over the managed tunnel.
- [`suite info`](https://corentingiraud.github.io/ownsuite/reference/cli/#suite-info) — the URLs, the admin credentials (re-derived from the seed), and the DNS records for your domain.

## How it connects

Like the other admin commands, `suite status` talks to the server privately over the same SSH tunnel you use to manage it — nothing is exposed publicly. The server target comes from `suite.yaml` (or the machine state written by provisioning). If a tunnel is already open (or you have a working `KUBECONFIG`), add `--no-tunnel`.

It's read-only: it never changes anything, so it's safe to run as often as you like — before and after an [upgrade](https://corentingiraud.github.io/ownsuite/operate/upgrade/index.md), or any time you want to confirm the suite is well.
