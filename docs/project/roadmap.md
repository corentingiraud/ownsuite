# Status &amp; roadmap

> Self-host La Suite numérique, production-ready, on a single server, for a non-profit.
> The org arrives with a domain name; the installer hands them the DNS records to set;
> everything works. The admin then creates users in a single step.

This is a feature and status board — what is **shipped**, what is **optional**, and what is
**planned**. The rationale behind every choice lives in the
[Architecture Decision Records](../understand/decisions.md).

## Product vision (the global "definition of done")

1. A volunteer rents a server + a domain name.
2. They run an installer and answer ~5 questions (domain, admin email, which apps).
3. The installer prints **the exact list of DNS records** to set at the registrar.
4. Once DNS has propagated: every app responds over HTTPS, with **shared SSO**.
5. The admin creates `firstname@assoc.org` once → that person has access to Docs, Drive, etc.
6. **Backups** run automatically — encrypted, off-site — and **restore is tested**
   (not just the backup).

---

## Architecture (locked)

| Topic | Choice |
|---|---|
| Orchestration | **Single-node K3s + Helmfile** |
| Reverse proxy / TLS | **Traefik (bundled with K3s) + cert-manager** |
| SSO | **Keycloak**, 1 realm, 1 OIDC client per app |
| Database | **CloudNativePG** (PostgreSQL + WAL/PITR to S3) |
| Cache / broker | **Valkey** |
| Object storage | **Pluggable: Garage (self-hosted) or external EU S3** |
| Host provisioning | **Ansible** |
| Upgrade model | **Semver releases + backup-gated `suite` CLI + Renovate** |

---

## Shipped

Production essentials, implemented and **proven in CI**:

- **One-command bootstrap** — Ansible turns a bare Debian server into a hardened single-node
  K3s cluster (firewall, fail2ban, swap, sysctl, SSH hardening). See
  [server bootstrap](../get-started/bootstrap.md).
- **Shared foundation** — Traefik + cert-manager (HTTPS), CloudNativePG, Valkey, Keycloak SSO,
  pluggable Garage / external EU S3. See [shared infrastructure](../understand/platform.md).
- **Docs** *(core, on by default)* — collaborative documents wired to SSO, Postgres and S3.
  See [Docs application](../understand/docs.md).
- **Drive** *(core, on by default)* — file manager on the same foundation; one identity reaches
  Docs **and** Drive. See [Drive application](../understand/drive.md).
- **Shared SSO + JIT user provisioning** — one Keycloak identity, just-in-time into every app;
  `suite user add/passwd/disable`. See [Users](../operate/users.md).
- **Guided installer** — `suite install` generates the DNS records, gates on propagation, issues
  Let's Encrypt certificates (staging → production), and brings the whole stack up. See
  [Guided install](../get-started/install.md).
- **Off-site backups + tested restore** — CNPG PITR + an encrypted off-site object copy; CI
  replays a full **backup → destroy → restore** cycle. See [Backups & restore](../operate/backups.md).

## Optional apps (off by default)

Enable each with one `OWNSUITE_APP_*` flag; they reuse the same SSO + JIT seam.

- **Grist** *(optional)* — spreadsheets that behave like a database
  (`OWNSUITE_APP_GRIST`). See [Grist application](../understand/grist.md).
- **Projects** *(optional)* — kanban boards / task management
  (`OWNSUITE_APP_PROJECTS`). See [Projects application](../understand/projects.md).
- **Mailbox** *(advanced)* — La Suite's own mail app, `suitenumerique/messages`
  (`OWNSUITE_APP_MESSAGES`). Mail is the hardest part to make reliable, so it ships isolated
  and disabled by default. See [Mailbox application](../understand/messages.md).

## Planned

Production hardening so a third-party org can install, operate, upgrade and recover OwnSuite
**without maintainer help**:

- Tuned resource requests/limits + liveness/readiness probes on every workload, and a
  **server-sizing guide** (RAM/CPU/disk per enabled app).
- **Per-app nightly boot checks** — each app on its own fresh cluster, including the mailbox
  local-delivery loopback.
- **Backup coverage** — off-site copy of every media bucket, plus off-site backup of the Grist
  document volume.
- **`suite upgrade`** (backup-gated: snapshot → diff → apply → health check → rollback on
  failure) and **`suite status`** health surfacing.

**Out of scope / deferred:** Meet (video — LiveKit/coturn, painful on a single server);
OpenSearch full-text search for the mailbox (deferred to protect single-VPS RAM — note the cost
if re-enabled).

---

## Main risks to watch

1. **Email deliverability** (mailbox) — the biggest risk; deliberately isolated as an optional module.
2. **Kubernetes learning curve** for a volunteer — hidden behind the installer + CLI.
3. **Upstream drift** — official charts move; pin versions, track releases via Renovate.
4. **Per-app OIDC quirks** — validate one by one.
5. **Storage sovereignty** — if external S3, pick an EU/CH provider and encrypt.

## References

- More advanced production reference (governmental): `MinBZK/mijn-bureau-infra`
- Upstream org: <https://github.com/suitenumerique>
