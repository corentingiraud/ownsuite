# OwnSuite

> Self-host **[La Suite numérique](https://github.com/suitenumerique)** — **production-ready**, on a **single server**, for a **non-profit**.

[![CI](https://github.com/corentingiraud/ownsuite/actions/workflows/ci.yml/badge.svg)](https://github.com/corentingiraud/ownsuite/actions/workflows/ci.yml)
[![Platform e2e](https://github.com/corentingiraud/ownsuite/actions/workflows/helmfile-e2e.yml/badge.svg)](https://github.com/corentingiraud/ownsuite/actions/workflows/helmfile-e2e.yml)
[![Docs](https://github.com/corentingiraud/ownsuite/actions/workflows/docs.yml/badge.svg)](https://corentingiraud.github.io/ownsuite/)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)

OwnSuite turns **one Linux server + a domain** into a full collaborative suite served over
**HTTPS**, with **single sign-on** and **off-site backups you can actually restore** — the
production essentials the upstream apps' *"dev only"* `compose.yml` files leave out. A single
guided installer does the work: it generates your DNS records, waits for propagation, issues
real Let's Encrypt certificates, and brings the whole stack up.

Runs on any single server — a cloud VM, a dedicated host, or a home server.

## 📖 Documentation

**→ [corentingiraud.github.io/ownsuite](https://corentingiraud.github.io/ownsuite/)** — the full site.

| Get started | Operate | How it works | Project |
|---|---|---|---|
| [Prepare the server](https://corentingiraud.github.io/ownsuite/get-started/bootstrap/) · [Install](https://corentingiraud.github.io/ownsuite/get-started/install/) | [Add users](https://corentingiraud.github.io/ownsuite/operate/users/) · [Server sizing](https://corentingiraud.github.io/ownsuite/operate/sizing/) · [Backups & restore](https://corentingiraud.github.io/ownsuite/operate/backups/) | [Overview](https://corentingiraud.github.io/ownsuite/understand/overview/) | [What's included](https://corentingiraud.github.io/ownsuite/project/roadmap/) |

## Install

```bash
git clone https://github.com/corentingiraud/ownsuite.git && cd ownsuite
make deps        # one-time: tooling + Ansible collections
make install     # guided: bare server + domain -> all-in-HTTPS
```

Then follow the screen. Prerequisites and the full step-by-step flow are in the
**[install guide](https://corentingiraud.github.io/ownsuite/get-started/install/)**.

## Apps

One identity in Keycloak reaches every enabled app (single sign-on, just-in-time). **Every app
is off by default**; each is opt-in via its flag or the guided installer's prompts. **Docs +
Drive** are the recommended first pair (the installer presents them as such).

| App | What it is | Default | Flag | Status |
|---|---|---|---|---|
| **Docs** | Collaborative documents (suitenumerique/impress) | off | `OWNSUITE_APP_DOCS` | core |
| **Drive** | File manager (suitenumerique/drive) | off | `OWNSUITE_APP_DRIVE` | core |
| **Grist** | Spreadsheets that behave like a database (getgrist) | off | `OWNSUITE_APP_GRIST` | optional |
| **Projects** | Kanban boards / task management (suitenumerique/projects) | off | `OWNSUITE_APP_PROJECTS` | optional |
| **Mailbox** | Mail provider + webmail (suitenumerique/messages) | off | `OWNSUITE_APP_MESSAGES` | advanced |

See the [status board](https://corentingiraud.github.io/ownsuite/project/roadmap/) for the
full feature list and what's planned.

## What's built

Production essentials, implemented and **proven in CI**:

- ✅ **One-command bootstrap** — Ansible turns a bare Debian box into a hardened single-node K3s.
- ✅ **Shared foundation** — Traefik + cert-manager (HTTPS), CloudNativePG, Valkey, Keycloak SSO.
- ✅ **Recommended core apps** — Docs and Drive (opt-in) wired to SSO, Postgres, and S3 storage.
- ✅ **One-command user provisioning** — `suite user add` grants every enabled app at once (JIT).
- ✅ **Guided installer** — DNS records, propagation gate, Let's Encrypt staging → production.
- ✅ **Backups + tested restore** — off-site, encrypted; CI replays *backup → destroy → restore* nightly.

## Stack

K3s · Helmfile · Traefik · cert-manager · CloudNativePG · Valkey · Keycloak · Garage / external EU S3 · rclone

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
