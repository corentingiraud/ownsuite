# OwnSuite — Roadmap

Quick status board. Full narrative, rationale and "definition of done" per phase live
in the docs: **[docs/project/roadmap.md](docs/project/roadmap.md)** and the
**[architecture decisions](docs/understand/decisions.md)**.

**Legend:** ✅ done · 🚧 in progress · ⬜ not started

**Current focus:** Phase 5 — broaden apps + user provisioning.

---

## Phase 0 — Scoping & foundation ✅
- [x] Lock the stack (K3s + Helmfile, CNPG, Valkey, Garage/external S3 — see ADRs)
- [x] Pick name (**OwnSuite**) and license (**AGPL-3.0**)
- [x] Initialize repo + documentation site (MkDocs Material + `llms.txt`)
- [x] server bootstrap (Ansible): K3s, firewall, fail2ban, swap, sysctl
- [x] Layered, evolving CI test harness (lint + Molecule/Testinfra + nightly full bootstrap — ADR-010)
- **DoD:** `make bootstrap` turns a bare Debian server into a ready single-node K3s cluster.

## Phase 1 — Reusable infrastructure foundation ✅
- [x] Traefik + cert-manager + Let's Encrypt / self-signed ClusterIssuers (ADR-013)
- [x] CloudNativePG operator + 1 cluster, 1 db/app (Database CRs)
- [x] Valkey (groundhog2k chart, auth from derived secret)
- [x] Object storage: pluggable seam — external EU S3 default, Garage deferred (ADR-003)
- [x] Keycloak (codecentric/keycloakx — ADR-011) + realm/client generation from `secretSeed` (ADR-012)
- [x] k3d e2e proving the DoD in CI (`helmfile-e2e.yml`)
- **DoD:** `helmfile sync` brings up all shared infra; Keycloak reachable over HTTPS.

## Phase 2 — Vertical slice: Docs end to end ✅
- [x] In-cluster object storage: single-node Garage + bucket bootstrap (ADR-015), external S3 still default
- [x] Docs (suitenumerique/impress) wired to CNPG + Valkey + S3 + Keycloak SSO (ADR-016)
- [x] Traefik ingress for Docs (websockets + authenticated media via middlewares); OIDC external/internal split
- [x] `docs` OIDC client + optional seeded test user generated from `secretSeed`
- [x] k3d e2e extended: Garage + Docs deployed, API-level DoD (token → create + read back a document)
- [ ] Full browser-driven SSO + collaboration check (deferred to a targeted job)
- **DoD:** a Keycloak user logs into Docs and creates a persistent document.

## Phase 3 — Backups & restore (production pillar) ✅
- [x] Postgres PITR to off-site S3 via CNPG Barman Cloud Plugin (recovery-window retention — ADR-017)
- [x] Object backup off-site with `rclone` (encrypted, both garage and external modes)
- [x] Keycloak covered by PITR of its database (realm + users) — refines ADR-006's realm export
- [x] Off-site by design (distinct destination; seed-derived or overridden creds)
- [x] Tested restore path: `make restore` + k3d e2e backup→destroy→restore cycle
- **DoD:** destroy an instance and fully restore it from backups (Docs document + Keycloak user survive, proven by CI).

## Phase 4 — "Domain → DNS → it works" experience ✅
- [x] Interactive, idempotent installer `suite install` (config + seed) wrapping bootstrap→sync (ADR-018)
- [x] Generate the exact DNS records (wildcard A + apex, AAAA when present, CAA) + propagation gate
- [x] Certificate issuance: additive `letsencrypt-staging` issuer, staging→production (ADR-019)
- [x] SSH tunnel automation + per-host HTTPS verification
- [x] Idempotent Keycloak OIDC client upsert on an already-imported realm (ADR-020)
- [x] k3d e2e: installer drives config→sync→certs Ready→HTTPS (self-signed); real ACME proven off-CI
- **DoD:** from a bare server + domain, the org follows the screen and everything serves HTTPS.

## Phase 5 — Broaden apps + user provisioning 🚧
- [x] Add Drive (Helmfile profile; same CNPG + Valkey + S3 + Keycloak seam as Docs — no People dependency) (ADR-022)
- [x] Add Grist (collaborative spreadsheet, getgrist self-hosted — local chart, public-issuer OIDC, PVC storage; off by default, outside the hard DoD) (ADR-024)
- [ ] Projects (suitenumerique/projects, kanban) — **deferred** with a documented build path: no upstream Helm chart, early-stage, would be a 2nd app not yet CI-booted; mirror the Grist local-chart pattern when prioritised (ADR-025)
- [ ] People deferred / optional — identity stays in Keycloak (ADR-012/020); revisit only if app-level teams need it
- [x] `suite` CLI: create/disable users, password reset (Keycloak, JIT to all apps) (ADR-023)
- **DoD:** `suite user add firstname@assoc.org` grants Docs + Drive immediately.

## Phase 6 — (Optional) Mailbox ⬜
- [ ] Mailbox: **suitenumerique/messages** — La Suite's own mail app (Postfix MTA-in + Django MDA + Postgres/Redis/OpenSearch + integrated webmail, no IMAP), federated to the same Keycloak via OIDC (ADR-021)
- [ ] Outbound via `MTA_OUT_MODE=relay` through a reputable EU SMTP relay (Infomaniak) — never direct from the VPS IP
- [ ] MX/SPF/DKIM/DMARC in the DNS flow; rDNS/PTR at the host; provisioning wired into the `suite` CLI
- **DoD:** `suite user add` also creates the mailbox; outbound mail reaches the inbox (not spam).

## Phase 7 — Production hardening & packaging ⬜
- [ ] Resource limits, health checks, light monitoring
- [ ] Upgrade strategy (pinned versions, migrations, Helm rollback, Renovate)
- [ ] Non-profit-admin docs, troubleshooting, server sizing
- **DoD:** a third-party org installs and operates it without maintainer help.

---

## Out of scope (v1)
- **Meet (video)** — LiveKit/coturn, painful on a single server. Deferred.
- **Mailbox** — now a La Suite app (suitenumerique/messages), but a heavy/advanced add-on; optional, deferred to Phase 6.
