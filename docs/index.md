# OwnSuite

> Self-host **[La Suite numérique](https://github.com/suitenumerique)**,
> *production-ready*, on a **single VPS**, for a **non-profit**.

The goal: a volunteer shows up with a domain name and some technical know-how, and
walks away with a full collaborative suite (documents, files, directory…) served over
**HTTPS**, with **single sign-on (SSO)** and **backups** that run on their own.

## The promise, in 6 steps

1. Rent a VPS and a domain name.
2. Run the **[guided installer](operations/install.md)**, answer ~5 questions (domain, admin email, apps).
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

!!! info "Status"
    Early-stage project. The design is documented here; code follows the
    [roadmap](roadmap.md). See also the [architecture decisions](architecture/decisions.md).

## Where to start

**Installing it?** Follow the two steps in order:

<div class="grid cards" markdown>

- :material-server: **[1. Prepare the VPS](operations/bootstrap.md)** — one command turns a bare Debian VPS into a ready K3s cluster.
- :material-rocket-launch: **[2. Install](operations/install.md)** — the guided installer takes you from there to every app on HTTPS, by following the screen.

</div>

**Curious how it works, or contributing?**

<div class="grid cards" markdown>

- :material-sitemap: **[Understand the stack](architecture/overview.md)** — the architecture, block by block.
- :material-backup-restore: **[Backups & restore](operations/backups.md)** — off-site, encrypted, with a tested restore.
- :material-scale-balance: **[Decisions (ADR)](architecture/decisions.md)** — the choices and their rationale.
- :material-map: **[Roadmap](roadmap.md)** — the phases to *production-ready*.

</div>

## Documentation built for AI

This documentation is **pure Markdown** and automatically publishes:

- **`/llms.txt`** — a structured index of the whole documentation;
- **`/llms-full.txt`** — the entire content concatenated into a single file.

Any AI tool can fetch these files to load the full project context. See
[For AI agents](contributing/for-ai-agents.md).
