# OwnSuite

> Self-host **[La Suite numérique](https://github.com/suitenumerique)**,
> *production-ready*, on a **single server**, for a **non-profit**.

The goal: a volunteer shows up with a domain name and some technical know-how, and
walks away with a full collaborative suite (documents, files, directory…) served over
**HTTPS**, with **single sign-on (SSO)** and **backups** that run on their own.

## The promise, in 6 steps

1. Get a server — a cloud VM, a dedicated host, or a home server — and a domain name.
2. Run **`suite init`**, answer ~5 questions (domain, admin email, **which apps to enable**) — it writes **`suite.yaml`**, the one file that describes your suite.
3. Run **`suite apply`** — it prints **the exact list of DNS records** to add at the registrar, waits for them, and brings everything up over HTTPS with **shared SSO**.
4. Want another app later? Add one line under `apps:` in `suite.yaml`, `suite apply` again.
5. The admin creates `firstname@assoc.org` **once** → instant access to every enabled app.
6. **Backups** are encrypted, off-site, and **restore is tested**.

## Why this project exists

Each La Suite app ships a `compose.yml` flagged *"experimental, dev only"* — the
official production path is Kubernetes/Helm. But the guides deploy each app **in
isolation**, with no shared infrastructure and no common SSO.

**This project's value is integration:** a single stack that shares the database,
cache, storage and — above all — **one SSO** across every app, plus everything real
production needs: **backups, tested restore, controlled upgrades**.

!!! info "What's ready today"
    The platform is built and tested in CI: server setup, shared single sign-on, off-site
    backups with a restore that's actually tested, and the declarative `suite apply` flow.
    **Every app is off by default — you choose which to deploy.** Docs, Drive, Grist,
    Projects, a Mailbox, Meet and Tchap are all available. See
    [Choosing which apps to deploy](reference/configuration.md#choosing-which-apps-to-deploy)
    and the [feature list](project/roadmap.md).

## The apps

One Keycloak identity reaches every enabled app (single sign-on, just-in-time). **Every app is
off by default** — an app is enabled by its line under `apps:` in `suite.yaml`.

| App | What it is | suite.yaml entry |
|---|---|---|
| **[Docs](understand/docs.md)** | Collaborative documents | `docs: {}` |
| **[Drive](understand/drive.md)** | File manager | `drive: {}` |
| **[Grist](understand/grist.md)** | Spreadsheets that behave like a database | `grist: {}` |
| **[Projects](understand/projects.md)** | Kanban boards / task management | `projects: {}` |
| **[Mailbox](understand/messages.md)** | Mail provider + webmail | `messages: {}` |
| **[Meet](understand/meet.md)** | Video conferencing (LiveKit) | `meet: {}` |
| **[Tchap](understand/tchap.md)** | Matrix/Element secure chat, text-only | `tchap: {}` |

Some upstream La Suite apps (People, Calendars…) are deliberately not packaged — see
[Not supported](project/roadmap.md#not-supported-and-why).

## Where to start

**Installing it?**

<div class="grid cards" markdown>

- :material-rocket-launch: **[Install](get-started/install.md)** — `suite init` writes `suite.yaml`, `suite apply` takes you to the apps you chose, on HTTPS. Start here.
- :material-server-network: **[Pick a server size](operate/sizing.md)** — how much RAM, CPU and disk to rent, per app. Decide this before you provision.
- :material-cloud-outline: **[Under the hood: the server](get-started/provision.md)** — what apply provisions with Terraform on Scaleway, and how to bring your own server instead.
- :material-server: **[Under the hood: the bootstrap](get-started/bootstrap.md)** — how apply turns a bare Debian server into a ready K3s cluster.

</div>

**Running it day to day?**

<div class="grid cards" markdown>

- :material-account-multiple: **[Add your people](operate/users.md)** — one command per person, instant access to every app.
- :material-backup-restore: **[Backups & restore](operate/backups.md)** — off-site, encrypted, with a restore you can trust.

</div>

**Curious how it works?**

<div class="grid cards" markdown>

- :material-sitemap: **[How it works](understand/overview.md)** — the moving parts, in plain terms.
- :material-map: **[What's included](project/roadmap.md)** — the apps and features, and what's coming.

</div>

## Documentation built for AI

This documentation is **pure Markdown** and automatically publishes:

- **`/llms.txt`** — a structured index of the whole documentation;
- **`/llms-full.txt`** — the entire content concatenated into a single file.

Any AI tool can fetch these files to load the full project context. See
[For AI agents](project/for-ai-agents.md).
