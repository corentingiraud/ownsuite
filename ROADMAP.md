# OwnSuite — Roadmap

Quick status board. Full narrative, rationale and "definition of done" per phase live
in the docs: **[docs/roadmap.md](docs/roadmap.md)** and the
**[architecture decisions](docs/architecture/decisions.md)**.

**Legend:** ✅ done · 🚧 in progress · ⬜ not started

**Current focus:** Phase 2 — vertical slice: Docs end to end.

---

## Phase 0 — Scoping & foundation ✅
- [x] Lock the stack (K3s + Helmfile, CNPG, Valkey, Garage/external S3 — see ADRs)
- [x] Pick name (**OwnSuite**) and license (**AGPL-3.0**)
- [x] Initialize repo + documentation site (MkDocs Material + `llms.txt`)
- [x] VPS bootstrap (Ansible): K3s, firewall, fail2ban, swap, sysctl
- [x] Layered, evolving CI test harness (lint + Molecule/Testinfra + nightly full bootstrap — ADR-010)
- **DoD:** `make bootstrap` turns a bare Debian VPS into a ready single-node K3s cluster.

## Phase 1 — Reusable infrastructure foundation ✅
- [x] Traefik + cert-manager + Let's Encrypt / self-signed ClusterIssuers (ADR-013)
- [x] CloudNativePG operator + 1 cluster, 1 db/app (Database CRs)
- [x] Valkey (groundhog2k chart, auth from derived secret)
- [x] Object storage: pluggable seam — external EU S3 default, Garage deferred (ADR-003)
- [x] Keycloak (codecentric/keycloakx — ADR-011) + realm/client generation from `secretSeed` (ADR-012)
- [x] k3d e2e proving the DoD in CI (`helmfile-e2e.yml`)
- **DoD:** `helmfile sync` brings up all shared infra; Keycloak reachable over HTTPS.

## Phase 2 — Vertical slice: Docs end to end ⬜
- [ ] Docs wired to CNPG + Valkey + S3 + Keycloak SSO
- [ ] Validate SSO login, file upload, real-time collaboration
- **DoD:** a Keycloak user logs into Docs and creates a persistent document.

## Phase 3 — Backups & restore (production pillar) ⬜
- [ ] Postgres PITR to S3 (GFS retention)
- [ ] Object backup off-site (replication or restic/rclone)
- [ ] Scheduled Keycloak realm export
- [ ] Tested restore path
- **DoD:** destroy an instance and fully restore it from backups.

## Phase 4 — "Domain → DNS → it works" experience ⬜
- [ ] Interactive installer (domain, admin email, app selection)
- [ ] Generate the exact DNS records to set (wildcard A/AAAA, CAA)
- [ ] Propagation check + certificate issuance
- **DoD:** from a bare VPS + domain, the org follows the screen and everything serves HTTPS.

## Phase 5 — Broaden apps + user provisioning ⬜
- [ ] Add Drive, then People (Helmfile profiles)
- [ ] `suite` CLI: create/disable users, password reset (Keycloak, JIT to all apps)
- **DoD:** `suite user add firstname@assoc.org` grants Docs + Drive immediately.

## Phase 6 — (Optional) Mailbox ⬜
- [ ] Mail server (Stalwart) federated to the same Keycloak
- [ ] MX/SPF/DKIM/DMARC in the DNS flow; outbound relay option
- **DoD:** `suite user add` also creates the mailbox; outbound mail reaches the inbox.

## Phase 7 — Production hardening & packaging ⬜
- [ ] Resource limits, health checks, light monitoring
- [ ] Upgrade strategy (pinned versions, migrations, Helm rollback, Renovate)
- [ ] Non-profit-admin docs, troubleshooting, VPS sizing
- **DoD:** a third-party org installs and operates it without maintainer help.

---

## Out of scope (v1)
- **Meet (video)** — LiveKit/coturn, painful on a single VPS. Deferred.
- **Mailbox** — not part of La Suite numérique; optional add-on (Phase 6).
