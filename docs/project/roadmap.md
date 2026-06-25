# Roadmap (high level)

> Self-host La Suite numérique, production-ready, on a single VPS, for a non-profit.
> The org arrives with a domain name; we hand them the DNS records to set; everything
> works. The admin then creates users in a single step.

## Product vision (the global "definition of done")

1. A volunteer rents a VPS + a domain name.
2. They run an installer and answer ~5 questions (domain, admin email, which apps).
3. The installer prints **the exact list of DNS records** to set at the registrar.
4. Once DNS has propagated: every app responds over HTTPS, with **shared SSO**.
5. The admin creates `firstname@assoc.org` once → that person has access to Docs,
   Drive, etc.
6. **Backups** run automatically — encrypted, off-site — and **restore is tested**
   (not just the backup).

---

## Architecture decisions (locked)

The full rationale lives in the [Architecture Decision Records](../understand/decisions.md).

| Topic | Choice |
|---|---|
| Orchestration | **Single-node K3s + Helmfile** |
| Reverse proxy / TLS | **Traefik (bundled with K3s) + cert-manager** |
| SSO | **Keycloak**, 1 realm, 1 OIDC client per app |
| Database | **CloudNativePG** (PostgreSQL + WAL/PITR to S3) |
| Cache / broker | **Valkey** |
| Object storage | **Pluggable: Garage (self-hosted) | external EU S3** |
| Host provisioning | **Ansible** |
| Upgrade model | **Semver releases + backup-gated `suite` CLI + Renovate** |

**Out of scope for v1:** Meet (LiveKit/coturn — UDP, CPU, painful on a single VPS).
**Advanced add-on, not in the core:** the mailbox (see Phase 6 — this is NOT part of La Suite).

---

## What we reuse from `lasuite-platform` vs what we rebuild

**Reuse (mature logic, keep):**

- The Helmfile orchestration of all apps with enable/disable conditions.
- The `platform-configuration` that **generates the Keycloak realm + 1 OIDC client per
  app** with derived secrets.
- Deriving all secrets from a single `secretSeed`.
- The "one domain → `app.{domain}` per app" model, cert-manager + Let's Encrypt.
- The per-app `values/*.gotmpl` files (config starting point).

**Rebuild / add (the core of our value):**

- Infrastructure foundation **without Bitnami or MinIO** → CNPG, Valkey, Garage/external S3.
- **Traefik** ingress (K3s) instead of HAProxy.
- The whole **Backups & Restore** module (absent from the reference solution).
- The **domain → DNS** experience (generating the records to set).
- Simple **user provisioning** for the admin.
- **Production hardening** (monitoring, limits, upgrades, non-profit-facing docs).

---

## Phases

### Phase 0 — Scoping & technical foundation

- Lock the stack (above), pick the name/license (AGPL-3.0 suggested), init the repo.
- Reproducible VPS bootstrap with **Ansible**: K3s (pinned), ufw, fail2ban, swap, sysctl,
  SSH hardening, unattended security upgrades. See [VPS bootstrap](../get-started/bootstrap.md).
- A **layered, evolving CI test harness** (lint → Molecule/Testinfra on Debian 12/13 →
  nightly real-K3s bootstrap) — the seed of the install/upgrade/restore pipeline ([ADR-010](../understand/decisions.md#adr-010-testing-ci-strategy-a-layered-evolving-harness)).
- **Done:** `make bootstrap` turns a bare Debian VPS into a ready K3s cluster.

### Phase 1 — Reusable infrastructure foundation (no Bitnami/MinIO)

- Helmfile: Traefik (already there) + cert-manager + Let's Encrypt ClusterIssuer.
- CloudNativePG (1 cluster, 1 db/app), Valkey, Garage **or** external S3 wiring.
- Keycloak + realm/client generation (reused and adapted).
- **Done:** `helmfile sync` brings up all shared infra, Keycloak reachable over HTTPS.

### Phase 2 — Vertical slice: Docs end to end

> Go deep on **one** app before broadening.

- Build the real object store the foundation only stubbed: single-node **Garage**
  in-cluster with a seed-derived key + bucket bootstrap ([ADR-015](../understand/decisions.md#adr-015-in-cluster-object-storage-garage-single-node-deterministic-key)); external EU S3 stays the production default.
- Deploy **Docs** (`suitenumerique`/impress) wired to CNPG + Valkey + S3 + Keycloak SSO,
  in the shared `ownsuite` namespace, over **Traefik** with the OIDC external/internal
  endpoint split ([ADR-016](../understand/decisions.md#adr-016-docs-impress-integration-one-namespace-traefik-ingress-oidc-split)). See [Docs application](../understand/docs.md).
- Validate SSO login, file upload (S3), real-time collaboration; the k3d e2e proves the
  DoD at the API level (a Keycloak token creates and reads back a document).
- **Done:** a Keycloak user logs into Docs and creates a persistent document.

### Phase 3 — Backups & Restore (the "production-ready" pillar)

- Postgres: CNPG **Barman Cloud Plugin** — WAL archiving + base backups to **off-site** S3,
  PITR, recovery-window retention ([ADR-017](../understand/decisions.md#adr-017-backups-tested-restore-barman-cloud-plugin-rclone-off-site-by-design)).
- Objects: **`rclone`** S3→S3 copy off-site, client-side encrypted (both garage and external modes).
- Keycloak: covered by **PITR of its database** (realm + users) — refines ADR-006's "scheduled
  export"; a `kc.sh` export stays a later portability add-on.
- Off-site by design: a distinct destination (a different account in prod; a second in-cluster
  Garage in CI) with seed-derived-or-overridden credentials. See [Backups & restore](../operate/backups.md).
- **Tested restore procedure**: `make restore` rebuilds a clean instance; the k3d e2e runs a full
  **backup → destroy → restore** cycle.
- **Done:** we destroy an instance and fully restore it from backups — the Phase-2 document and
  the Keycloak user survive, proven by CI.

### Phase 4 — "Domain → DNS → it works" experience

- **Guided installer `suite install`** ([ADR-018](../understand/decisions.md#adr-018-phase-4-guided-installer-suite-install)):
  one idempotent command captures config + the seed (shown once, never written to the repo), runs
  the bootstrap, opens the SSH tunnel and drives `helmfile sync` — orchestrating the existing
  layers in pure standard library, adding nothing to the VPS.
- **Generate the exact DNS records** (wildcard A `*.{domain}` + apex, AAAA when the VPS has public
  IPv6, CAA authorising Let's Encrypt; MX/TXT deferred with mail), then a **propagation gate** that
  blocks ACME until public resolvers agree — so a typo never burns the production rate limits.
- **Certificates staging → production**: an additive `letsencrypt-staging` ClusterIssuer issues
  first, then the installer promotes to production and verifies HTTPS per host
  ([ADR-019](../understand/decisions.md#adr-019-phase-4-tls-staging-first-issuance-dns-01-deferred)).
  A wildcard *A record* is not a wildcard *certificate* — certs stay per-host; the DNS-01 issuer
  stays deferred (the seam is additive).
- **Keycloak OIDC clients reconciled** on an already-imported realm via an idempotent kcadm Job
  ([ADR-020](../understand/decisions.md#adr-020-keycloak-realm-convergence-idempotent-oidc-client-upsert)).
- The k3d e2e drives the stack through the installer to self-signed HTTPS; real Let's Encrypt is
  validated off-CI (staging then production). See [Guided install](../get-started/install.md).
- **Done:** from a bare VPS + domain, the org follows the screen and everything serves HTTPS.

### Phase 5 — Broaden apps + user provisioning

- Add Drive, then People (directory/teams), via Helmfile profiles.
- **Simple provisioning**: a CLI/small admin portal that creates a Keycloak user →
  immediate access to all apps (JIT). Password reset, deactivation.
- **Done:** the admin runs `suite user add firstname@assoc.org` and the person has Docs+Drive.

### Phase 6 — (Advanced / optional) Mailbox

> ⚠️ **La Suite numérique provides NO mail server.** This is an add-on, and the
> hardest part to make reliable on a VPS.

- A mail stack federated to the same Keycloak: **Stalwart** (modern, OIDC) recommended;
  Mailcow/Mailu as alternatives.
- Deliverability reality: port 25 often blocked by the host, **rDNS/PTR** set at the
  host (not in DNS), SPF/DKIM/DMARC, IP reputation.
- Offer **two modes**: self-hosted (sovereign, demanding) **or** an external EU relay/
  provider (pragmatic, better deliverability). Mailbox provisioning wired into the Phase 5 CLI.
- **Done:** `suite user add` also creates the mailbox; an outbound email lands in the inbox (not spam).

### Phase 7 — Production hardening & packaging

- Resource limits, health checks, light monitoring (Uptime Kuma / metrics).
- Upgrade strategy (pinned image tags, DB migrations, Helm rollback).
- "Non-profit admin" docs (non-K8s-expert), troubleshooting guide, VPS sizing.
- **Done:** a third-party org installs and operates it without maintainer intervention.

---

## Main risks to watch

1. **Email deliverability** (Phase 6) — the biggest risk; deliberately isolated as an optional module.
2. **Kubernetes learning curve** for a volunteer — hidden behind installer + CLI.
3. **Upstream drift** — official charts move; pin versions, track releases.
4. **Per-app OIDC quirks** — validate one by one (residual ProConnect assumptions).
5. **Storage sovereignty** — if external S3, pick an EU/CH provider and encrypt.

## References

- Reference repo (cloned as an inspiration base): `baptisterajaut/lasuite-platform`
- More advanced production reference (governmental): `MinBZK/mijn-bureau-infra`
- Upstream org: <https://github.com/suitenumerique>
