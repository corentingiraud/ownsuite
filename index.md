# OwnSuite

> Self-host **[La Suite numérique](https://github.com/suitenumerique)**, *production-ready*, on a **single server**, for a **non-profit**.

The goal: a volunteer shows up with a domain name and some technical know-how, and walks away with a full collaborative suite (documents, files, directory…) served over **HTTPS**, with **single sign-on (SSO)** and **backups** that run on their own.

## The promise, in 6 steps

1. Get a server — a cloud VM, a dedicated host, or a home server — and a domain name.
1. Run **`suite init`**, answer ~5 questions (domain, admin email, **which apps to enable**) — it writes **`suite.yaml`**, the one file that describes your suite.
1. Run **`suite apply`** — it prints **the exact list of DNS records** to add at the registrar, waits for them, and brings everything up over HTTPS with **shared SSO**.
1. Want another app later? Add one line under `apps:` in `suite.yaml`, `suite apply` again.
1. The admin creates `firstname@assoc.org` **once** → instant access to every enabled app.
1. **Backups** are encrypted, off-site, and **restore is tested**.

## Why this project exists

Each La Suite app ships a `compose.yml` flagged *"experimental, dev only"* — the official production path is Kubernetes/Helm. But the guides deploy each app **in isolation**, with no shared infrastructure and no common SSO.

**This project's value is integration:** a single stack that shares the database, cache, storage and — above all — **one SSO** across every app, plus everything real production needs: **backups, tested restore, controlled upgrades**.

What's ready today

The platform is built and tested in CI: server setup, shared single sign-on, off-site backups with a restore that's actually tested, and the declarative `suite apply` flow. **Every app is off by default — you choose which to deploy.** Docs, Drive, Grist, Projects, a Mailbox, Meet, Tchap and Calendars are all available. See [Choosing which apps to deploy](https://corentingiraud.github.io/ownsuite/reference/configuration/#choosing-which-apps-to-deploy) and the [feature list](https://corentingiraud.github.io/ownsuite/project/roadmap/index.md).

## The apps

One Keycloak identity reaches every enabled app (single sign-on, just-in-time). **Every app is off by default** — an app is enabled by its line under `apps:` in `suite.yaml`.

| App                                                                                      | What it is                               | suite.yaml entry |
| ---------------------------------------------------------------------------------------- | ---------------------------------------- | ---------------- |
| **[Docs](https://corentingiraud.github.io/ownsuite/understand/docs/index.md)**           | Collaborative documents                  | `docs: {}`       |
| **[Drive](https://corentingiraud.github.io/ownsuite/understand/drive/index.md)**         | File manager                             | `drive: {}`      |
| **[Grist](https://corentingiraud.github.io/ownsuite/understand/grist/index.md)**         | Spreadsheets that behave like a database | `grist: {}`      |
| **[Projects](https://corentingiraud.github.io/ownsuite/understand/projects/index.md)**   | Kanban boards / task management          | `projects: {}`   |
| **[Mailbox](https://corentingiraud.github.io/ownsuite/understand/messages/index.md)**    | Mail provider + webmail                  | `messages: {}`   |
| **[Meet](https://corentingiraud.github.io/ownsuite/understand/meet/index.md)**           | Video conferencing (LiveKit)             | `meet: {}`       |
| **[Tchap](https://corentingiraud.github.io/ownsuite/understand/tchap/index.md)**         | Matrix/Element secure chat, text-only    | `tchap: {}`      |
| **[Calendars](https://corentingiraud.github.io/ownsuite/understand/calendars/index.md)** | Shared calendars with org free/busy      | `calendars: {}`  |

Some upstream La Suite apps (e.g. People) are deliberately not packaged — see [Not supported](https://corentingiraud.github.io/ownsuite/project/roadmap/#not-supported-and-why).

## Where to start

**Installing it?**

- **[Install](https://corentingiraud.github.io/ownsuite/get-started/install/index.md)** — `suite init` writes `suite.yaml`, `suite apply` takes you to the apps you chose, on HTTPS. Start here.
- **[Pick a server size](https://corentingiraud.github.io/ownsuite/operate/sizing/index.md)** — how much RAM, CPU and disk to rent, per app. Decide this before you provision.
- **[Under the hood: the server](https://corentingiraud.github.io/ownsuite/get-started/provision/index.md)** — what apply provisions with Terraform on Scaleway, and how to bring your own server instead.
- **[Under the hood: the bootstrap](https://corentingiraud.github.io/ownsuite/get-started/bootstrap/index.md)** — how apply turns a bare Debian server into a ready K3s cluster.

**Running it day to day?**

- **[Add your people](https://corentingiraud.github.io/ownsuite/operate/users/index.md)** — one command per person, instant access to every app.
- **[Backups & restore](https://corentingiraud.github.io/ownsuite/operate/backups/index.md)** — off-site, encrypted, with a restore you can trust.

**Curious how it works?**

- **[How it works](https://corentingiraud.github.io/ownsuite/understand/overview/index.md)** — the moving parts, in plain terms.
- **[What's included](https://corentingiraud.github.io/ownsuite/project/roadmap/index.md)** — the apps and features, and what's coming.

## Documentation built for AI

This documentation is **pure Markdown** and automatically publishes:

- **`/llms.txt`** — a structured index of the whole documentation;
- **`/llms-full.txt`** — the entire content concatenated into a single file.

Any AI tool can fetch these files to load the full project context. See [For AI agents](https://corentingiraud.github.io/ownsuite/project/for-ai-agents/index.md).
