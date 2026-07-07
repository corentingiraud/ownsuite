# Status &amp; roadmap

> Self-host La Suite numérique, production-ready, on a single server, for a non-profit.
> The org arrives with a domain name; `suite apply` hands them the DNS records to set;
> everything works. The admin then creates users in a single step.

This is a feature and status board — what is **shipped**, what is **optional**, and what is
**planned**.

## Product vision (the global "definition of done")

1. A volunteer rents a server + a domain name.
2. They run `suite init` and answer ~5 questions (domain, admin email, which apps) —
   the answers land in `suite.yaml`, the one file they own.
3. `suite apply` prints **the exact list of DNS records** to set at the registrar.
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
- **Shared SSO + JIT user provisioning** — one Keycloak identity, just-in-time into every app;
  `suite user add/passwd/disable`. See [Users](../operate/users.md).
- **Declarative install** — `suite init` writes `suite.yaml`; `suite apply` reconciles
  everything to it: provisions, generates the DNS records, gates on propagation, issues
  Let's Encrypt certificates (staging → production), and brings the whole stack up. See
  [Guided install](../get-started/install.md).
- **Off-site backups + tested restore** — CNPG PITR plus an encrypted off-site copy of **every
  enabled app's media bucket and the Grist document volume**; CI replays a full
  **backup → destroy → restore** cycle. See [Backups & restore](../operate/backups.md).
- **Tuned for a single small server** — resource requests/limits and liveness/readiness probes on
  every workload, with a per-app **server-sizing guide** (RAM/CPU/disk). See [Sizing](../operate/sizing.md).
- **Per-app boot checks in CI** — each app boots on its own fresh cluster nightly,
  including the mailbox local-delivery loopback.
- **Backup-gated upgrades + health surfacing** — `suite upgrade` (snapshot → diff → apply →
  health check → rollback on failure) and `suite status`. See [Upgrade](../operate/upgrade.md)
  and [Status](../operate/status.md).
- **Real external mail deliverability** — proven end-to-end on a real domain + relay: mail from
  the Mailbox app lands in an external inbox **not in spam**, with SPF/DKIM/DMARC aligned.
  `suite apply` emits the records and `dns_check` verifies alignment. See
  [Mailbox application](../understand/messages.md).

## Apps (all off by default)

Every app is opt-in via one line under `apps:` in `suite.yaml`; they reuse the same SSO +
JIT seam and are boot-checked in CI. Enable any combination.

- **Docs** — collaborative documents, `suitenumerique/impress`
  (`docs: {}`), wired to SSO, Postgres and S3. See [Docs application](../understand/docs.md).
- **Drive** — file manager, `suitenumerique/drive` (`drive: {}`), on the same
  foundation; one identity reaches Docs **and** Drive. See [Drive application](../understand/drive.md).
- **Grist** — spreadsheets that behave like a database
  (`grist: {}`). See [Grist application](../understand/grist.md).
- **Projects** — kanban boards / task management
  (`projects: {}`). See [Projects application](../understand/projects.md).
- **Mailbox** — La Suite's own mail app, `suitenumerique/messages`
  (`messages: {...}`). Mail is the hardest part to make reliable, so it ships isolated
  and disabled by default. See [Mailbox application](../understand/messages.md).
- **Meet** — video conferencing, `suitenumerique/meet` on LiveKit
  (`meet: {}`). The only app needing non-HTTP ports: LiveKit media on
  `7882/udp` (mux) + `7881/tcp` (fallback), opened automatically by `suite apply`
  ([ADR-039](../understand/decisions.md#adr-039-meet-media-ports-single-udp-mux-tcp-fallback)).
  Recording is written to its own S3 bucket; the AI/transcription components are
  disabled. See [Meet application](../understand/meet.md).
- **Tchap** — Matrix/Element secure chat (text-only), the French State's
  [`tchapgouv`](https://github.com/tchapgouv) messenger on Element's `matrix-stack` chart
  (`tchap: {}`). Media lands in its own S3 bucket and is copied off-site. See
  [Tchap application](../understand/tchap.md).

## Not supported (and why)

These upstream La Suite apps are deliberately **not** packaged by OwnSuite. The bar is
single-server fit and real value over what the shared foundation already provides.

| App | What it is | Why not (yet) |
|---|---|---|
| **People** | User & team management | It's an OIDC **client**, not an identity provider — it sits *behind* Keycloak, so it can't replace it. Identity is already covered by Keycloak + `suite user`; People would be one more app, not a simplification. |
| **Calendars** | Shared calendars | Early upstream; not integrated yet. |
| **Conversations** | AI chatbot | Early upstream prototype; not integrated yet. |
| **Calc** | Collaborative spreadsheets | Upstream prototype; overlaps with the shipped **Grist**. |
| **Hub** | Meet + chat, unified | A portal over the other apps; overlaps with the shipped **Meet** + the suite landing. Not integrated yet. |

## Planned

The production-hardening goal — install, operate, upgrade and recover OwnSuite **without
maintainer help** — is met. Everything once planned here has shipped above, including the last
item CI could not stand in for: real external mail deliverability, now proven end-to-end.

**Out of scope / deferred:** OpenSearch full-text search for the mailbox (deferred to protect
single-VPS RAM — note the cost if re-enabled). For upstream apps we don't package, see
[Not supported](#not-supported-and-why) above.

---

## Main risks to watch

1. **Email deliverability** (mailbox) — the biggest risk; deliberately isolated as an optional module.
2. **Kubernetes learning curve** for a volunteer — hidden behind `suite.yaml` + the CLI.
3. **Upstream drift** — official charts move; pin versions, track releases via Renovate.
4. **Per-app OIDC quirks** — validate one by one.
5. **Storage sovereignty** — if external S3, pick an EU/CH provider and encrypt.

## References

- More advanced production reference (governmental): `MinBZK/mijn-bureau-infra`
- Upstream org: <https://github.com/suitenumerique>
