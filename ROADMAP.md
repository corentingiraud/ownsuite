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

## Phase 5 — Broaden apps + user provisioning ⬜
- [ ] Add Drive (Helmfile profile; same CNPG + Valkey + S3 + Keycloak seam as Docs — no People dependency)
- [ ] Add Grist (collaborative spreadsheet, getgrist self-hosted — Node stack, not suitenumerique Django/React; OIDC wiring differs from the impress apps)
- [ ] Add Projects (suitenumerique/projects — kanban/task boards; Node/Sails.js + React, OIDC via Keycloak; docker-compose only, no Helm yet)
- [ ] People deferred / optional — identity stays in Keycloak (ADR-012/020); revisit only if app-level teams need it
- [ ] `suite` CLI: create/disable users, password reset (Keycloak, JIT to all apps)
- **DoD:** `suite user add firstname@assoc.org` grants Docs + Drive immediately.

## Phase 6 — (Optional) Mailbox ⬜
- [ ] Mail server (Stalwart) federated to the same Keycloak
- [ ] MX/SPF/DKIM/DMARC in the DNS flow; outbound relay option
- **DoD:** `suite user add` also creates the mailbox; outbound mail reaches the inbox.

## Phase 7 — Production hardening & packaging ⬜
- [ ] Resource limits, health checks, light monitoring
- [ ] Upgrade strategy (pinned versions, migrations, Helm rollback, Renovate)
- [ ] Non-profit-admin docs, troubleshooting, server sizing
- **DoD:** a third-party org installs and operates it without maintainer help.

---

## Out of scope (v1)
- **Meet (video)** — LiveKit/coturn, painful on a single server. Deferred.
- **Mailbox** — not part of La Suite numérique; optional add-on (Phase 6).
