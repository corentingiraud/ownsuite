# OwnSuite

> Self-host **[La Suite numérique](https://github.com/suitenumerique)**,
> *production-ready*, on a **single server**, for a **non-profit**.

The goal: a volunteer shows up with a domain name and some technical know-how, and
walks away with a full collaborative suite (documents, files, directory…) served over
**HTTPS**, with **single sign-on (SSO)** and **backups** that run on their own.

## The promise, in 6 steps

1. Get a server — a cloud VM, a dedicated host, or a home server — and a domain name.
2. Run the **[guided installer](get-started/install.md)**, answer ~5 questions (domain, admin email, apps).
3. The installer prints **the exact list of DNS records** to add at the registrar.
4. DNS propagates → every app responds over HTTPS, with **shared SSO**.
5. The admin creates `firstname@assoc.org` **once** → instant access to Docs, Drive, etc.
6. **Backups** are encrypted, off-site, and **restore is tested**.

## Why this project exists

Each La Suite app ships a `compose.yml` flagged *"experimental, dev only"* — the
official production path is Kubernetes/Helm. But the guides deploy each app **in
isolation**, with no shared infrastructure and no common SSO.

**This project's value is integration:** a single stack that shares the database,
cache, storage and — above all — **one SSO** across every app, plus everything real
production needs: **backups, tested restore, controlled upgrades**.

!!! info "What's ready today"
    The core is built and tested in CI: server setup, shared single sign-on, the **Docs**
    and **Drive** apps, off-site backups with a restore that's actually tested, and the
    guided installer. **Grist**, **Projects** and a **Mailbox** are available as optional
    extras. See the [feature list](project/roadmap.md).

## Where to start

**Installing it?** Follow the two steps in order:

<div class="grid cards" markdown>

- :material-server: **[1. Prepare the server](get-started/bootstrap.md)** — one command turns a bare Debian server into a ready K3s cluster.
- :material-rocket-launch: **[2. Install](get-started/install.md)** — the guided installer takes you from there to every app on HTTPS, by following the screen.

</div>

**Running it day to day?**

<div class="grid cards" markdown>

- :material-account-multiple: **[Add your people](operate/users.md)** — one command per person, instant access to every app.
- :material-backup-restore: **[Backups & restore](operate/backups.md)** — off-site, encrypted, with a restore you can trust.
- :material-server-network: **[Pick a server size](operate/sizing.md)** — how much RAM, CPU and disk to rent.

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
