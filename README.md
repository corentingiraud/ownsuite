# OwnSuite

> Self-host **[La Suite numérique](https://github.com/suitenumerique)** — **production-ready**, on a **single server**, for a **non-profit**.

[![CI](https://github.com/corentingiraud/ownsuite/actions/workflows/ci.yml/badge.svg)](https://github.com/corentingiraud/ownsuite/actions/workflows/ci.yml)
[![Platform e2e](https://github.com/corentingiraud/ownsuite/actions/workflows/helmfile-e2e.yml/badge.svg)](https://github.com/corentingiraud/ownsuite/actions/workflows/helmfile-e2e.yml)
[![Docs](https://github.com/corentingiraud/ownsuite/actions/workflows/docs.yml/badge.svg)](https://corentingiraud.github.io/ownsuite/)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)

OwnSuite turns **one Linux server + a domain** into a full collaborative suite served over
**HTTPS**, with **single sign-on** and **off-site backups you can actually restore** — the
production essentials the upstream apps' *"dev only"* `compose.yml` files leave out. One file
(`suite.yaml`) describes your suite; **one command (`suite apply`) makes it real**: it
provisions the server if asked, generates your DNS records, waits for propagation, issues real
Let's Encrypt certificates, brings the stack up, and prints your URLs.

Runs on any single server — a cloud VM, a dedicated host, or a home server.

## 📖 Documentation

**→ [corentingiraud.github.io/ownsuite](https://corentingiraud.github.io/ownsuite/)** — the full site.

| Get started | Operate | Reference | How it works | Project |
|---|---|---|---|---|
| [Provision](https://corentingiraud.github.io/ownsuite/get-started/provision/) · [Prepare the server](https://corentingiraud.github.io/ownsuite/get-started/bootstrap/) · [Install](https://corentingiraud.github.io/ownsuite/get-started/install/) | [Add users](https://corentingiraud.github.io/ownsuite/operate/users/) · [Server sizing](https://corentingiraud.github.io/ownsuite/operate/sizing/) · [Backups & restore](https://corentingiraud.github.io/ownsuite/operate/backups/) | [`suite` CLI](https://corentingiraud.github.io/ownsuite/reference/cli/) · [Configuration](https://corentingiraud.github.io/ownsuite/reference/configuration/) | [Overview](https://corentingiraud.github.io/ownsuite/understand/overview/) | [What's included](https://corentingiraud.github.io/ownsuite/project/roadmap/) |

## Install

```bash
git clone https://github.com/corentingiraud/ownsuite.git && cd ownsuite
python3 -m suite deps       # one-time: install the tooling + Ansible collections
pipx install --editable .   # optional: the short `suite` command, on PATH in any shell
                            # (run `pipx ensurepath` once if it isn't picked up yet)
suite init                  # questionnaire -> writes suite.yaml
suite apply                 # provision -> bootstrap -> DNS -> HTTPS -> your URLs
```

Adding an app later is the whole point:

```bash
$EDITOR suite.yaml          # add `tchap: {}` under apps:
suite apply                 # done -> https://tchap.your-domain.org
```

Prerequisites and the full step-by-step flow are in the
**[install guide](https://corentingiraud.github.io/ownsuite/get-started/install/)**.

## The `suite` CLI

`python3 -m suite <command>` is the single entry point for both installing and operating the
stack (argparse, no extra tooling), and always works from the checkout. For the shorter
`suite <command>` on your `PATH` in any shell, `pipx install --editable .`. The commands:

| Command | What it does |
|---|---|
| `init` | Questionnaire → writes `suite.yaml`, the one file that describes your suite. |
| `plan` | Preview what `apply` would change (infra, apps, DNS) — read-only. |
| `apply` | Reconcile everything to `suite.yaml`: provision, bootstrap, DNS, deploy/prune apps, verify, print URLs. |
| `apps` | App catalog: available / enabled / installed / healthy / URL. |
| `info` | URLs, admin credentials, DNS records. |
| `logs <app>` | Tail an app's pods over the managed tunnel. |
| `user add\|passwd\|disable` | Manage Keycloak users — one identity reaches every enabled app (JIT). |
| `status` | Health summary — node, database, certs, backup, apps. |
| `upgrade` | Backup-gated upgrade: snapshot → diff → apply → health-check → rollback on failure. |
| `backup` | Take a backup now and wait for it to complete. |
| `restore` | Restore a clean cluster from the off-site backups. |
| `destroy` | Uninstall the whole suite from the cluster (data kept). |
| `deps` | One-time: install Python tooling + Ansible collections. |

Full reference: **[`suite` CLI](https://corentingiraud.github.io/ownsuite/reference/cli/)**.

## Apps

One identity in Keycloak reaches every enabled app (single sign-on, just-in-time). **Every app
is off by default** — enabling one is a line in `suite.yaml` under `apps:` followed by
`suite apply`; removing the line (+ apply) uninstalls it, keeping its data.

| App | What it is | suite.yaml entry |
|---|---|---|
| **Docs** | Collaborative documents (suitenumerique/impress) | `docs: {}` |
| **Drive** | File manager (suitenumerique/drive) | `drive: {}` |
| **Grist** | Spreadsheets that behave like a database (getgrist) | `grist: {}` |
| **Projects** | Kanban boards / task management (suitenumerique/projects) | `projects: {}` |
| **Mailbox** | Mail provider + webmail (suitenumerique/messages) | `messages: {}` |
| **Meet** | Video conferencing on LiveKit (suitenumerique/meet) | `meet: {}` |
| **Tchap** | Matrix/Element secure chat, text-only (ess-helm + tchapgouv) | `tchap: {}` |

Some upstream La Suite apps (People, Calendars…) are deliberately not packaged — see
[Not supported](https://corentingiraud.github.io/ownsuite/project/roadmap/#not-supported-and-why).
See the [status board](https://corentingiraud.github.io/ownsuite/project/roadmap/) for the
full feature list and what's planned.

## What's built

Production essentials, implemented and **proven in CI**:

- ✅ **Declarative suite** — `suite.yaml` describes it, `suite apply` reconciles everything to it.
- ✅ **Shared foundation** — Traefik + cert-manager (HTTPS), CloudNativePG, Valkey, Keycloak SSO.
- ✅ **Opt-in apps** — each app you enable is wired to SSO, Postgres, and S3 storage; removing it uninstalls but keeps the data.
- ✅ **One-command user provisioning** — `suite user add` grants every enabled app at once (JIT).
- ✅ **Guardrails always on** — DNS propagation gate, Let's Encrypt staging → production ladder, pre-change snapshot, health check + rollback.
- ✅ **Backups + tested restore** — off-site, encrypted; CI replays *backup → destroy → restore* nightly.

## Stack

K3s · Helmfile · Traefik · cert-manager · CloudNativePG · Valkey · Keycloak · fail2ban · LiveKit (Meet) · Scaleway · external EU S3 / Garage · rclone

## Contributing

See **[AGENTS.md](AGENTS.md)** for conventions — in short: English everywhere, versions pinned
to the latest, and no plaintext secrets. Preview the docs locally:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-docs.txt
mkdocs serve     # http://127.0.0.1:8000
```

## License

[AGPL-3.0](LICENSE) — use it commercially and offer paid hosting, but a modified version
exposed over a network must publish its source under AGPL-3.0.
