# Architecture Decision Records (ADR)

A log of the structural choices, in a lightweight *Context → Decision → Consequences*
format. Each decision is numbered so it can be referenced and revised.

---

## ADR-001 — K3s + Helmfile (not Compose or raw Helm)

**Context.** La Suite's official production path is Helm; the apps' `compose.yml`
files are flagged *dev only*. We target a single VPS.

**Decision.** A **single-node K3s** cluster orchestrated with **Helmfile**. Helmfile
is `helm upgrade --install` done with discipline: it brings dependency ordering
(`config → postgres → keycloak → apps`), a preview (`helmfile diff`) and environments.

**Consequences.** We reuse the official charts (less drift). Traefik and ServiceLB
come bundled with K3s. Trade-off: a Kubernetes learning curve, hidden behind an
installer and a `suite` CLI.

---

## ADR-002 — Ansible for the host (not Nix)

**Context.** We must provision the VPS (firewall, fail2ban, swap, sysctl, patches,
K3s install) reproducibly. Target audience: non-profit volunteers, not Kubernetes/Nix
experts.

**Decision.** **Ansible** for host configuration and the K3s install.

**Why not Nix.** NixOS's headline advantage — atomic generation rollback — only
restores the **OS config**, not the cluster state (K3s sqlite/etcd, volumes, app
data). For a **stateful** stack, that rollback hands you an empty shell you must
restore from backups anyway: you'd pay Nix's entry cost without reaping its real
benefit. Add a much smaller contributor pool and scarce VPS images. A community NixOS
variant remains possible later, off the main path.

**Consequences.** Low barrier for admins and contributors; re-runnable playbooks for
OS/K3s version bumps. Drift is possible on manual edits (mitigated by idempotence and CI).

---

## ADR-003 — Pluggable object storage: Garage or external EU S3

**Context.** MinIO (community) is **archived** (February 2026): console removed,
binaries/images discontinued. Drive can store hundreds of GB.

**Decision.** **Pluggable** object storage via config: **Garage** (self-hosted,
French, lightweight) **or** a **managed EU/CH S3** (Infomaniak, Scaleway, OVH).
Recommended production default: external S3.

**Consequences.** No storage ops with external S3, smaller VPS disk, simpler backups;
Garage for full sovereignty. Even with external S3, an **off-site application-level
backup** of the objects is still required (accidental deletion, lock-in).

---

## ADR-004 — CloudNativePG + Valkey (leaving Bitnami)

**Context.** Broadcom locked down the free Bitnami catalog (August 28, 2025), moving
images to the unmaintained `bitnamilegacy`. The reference solution depended on it
(`bitnami/postgresql`, `bitnami/redis`).

**Decision.** **CloudNativePG** (operator) for PostgreSQL — with **native** WAL/PITR
backups to S3. **Valkey** (open Redis fork) for cache/broker.

**Consequences.** A maintained, libre foundation; Postgres backup becomes an operator
feature rather than a homegrown script. CNPG adds an operator to run (acceptable).

---

## ADR-005 — Shared Keycloak, JIT provisioning

**Context.** A "suite" implies a single identity across apps. ProConnect is not open
to non-profits.

**Decision.** Self-hosted **Keycloak**, **1 realm**, **1 OIDC client per app**
(secrets derived from a single `secretSeed`). Creating a user **once** → access to all
apps via **JIT** provisioning.

**Consequences.** Real SSO plus a simple admin journey. Each app's OIDC quirks must be
validated one by one (possible residual ProConnect assumptions).

---

## ADR-006 — Backups and tested restore

**Context.** Existing solutions ship **no** backups. This is the heart of
"production-ready".

**Decision.** Back up the **three sources of state**: PostgreSQL (CNPG PITR to S3),
objects (bucket replication or `restic`/`rclone` off-site), Keycloak realm (scheduled
export). All encrypted, with GFS retention. **Restore is tested** (`make restore` /
`suite restore`), not just the backup.

**Consequences.** Credible disaster recovery. Cost: a CI pipeline that replays
install → upgrade → restore to keep the promise true over time.

---

## ADR-007 — Upgrade model: semver releases + backup-gated CLI

**Context.** The project aggregates ~6 upstream charts plus infrastructure, all moving
fast. Long-term administration and upgrades are a design criterion.

**Decision.** The non-profit tracks **the project's releases (semver)**, not upstream
directly: each tag pins a **tested matrix** `{chart versions, image tags, K3s
version}`. Upgrades run through a **`suite` CLI** that is *backup-gated*: snapshot →
`helmfile diff`/`apply` → migrations → health check → auto-rollback on failure.
**Renovate/Dependabot** opens bump PRs, tested in CI before a release.

**Consequences.** Sustainable maintenance; upgrades = a git operation plus one
command. GitOps (Flux/ArgoCD) is possible later; deemed overkill for a single VPS in v1.

**Concrete tooling (Phase 0).** **Renovate** (`renovate.json`), not Dependabot — one
tool that tracks *every* pin we ship: Python tooling (`requirements-*.txt`), **Ansible
Galaxy collections** (`ansible/requirements.yml`, `molecule/requirements.yml`), GitHub
Actions, and the **K3s release** in `ansible/group_vars/all.yml` (via a custom manager
against the `k3s-io/k3s` releases). Dependabot would only cover a subset and would race
Renovate with duplicate PRs, so it is intentionally omitted. Each bump is a PR gated by
the [ADR-010](#adr-010-testing-ci-strategy-a-layered-evolving-harness) test harness, so
"stay current" never means "stay untested".

---

## ADR-008 — Mailbox out of scope for v1 (feasible as an add-on)

**Context.** La Suite numérique provides **no** mail server. The request "create
`firstname@assoc.org` with their mailbox" requires a separate stack.

**Decision.** **Out of v1.** Architecturally feasible later: a mail server
(**Stalwart** recommended, native OIDC) federated to the **same Keycloak**, with
MX/SPF/DKIM/DMARC records added to the DNS flow and provisioning wired into the
`suite` CLI.

**Why deferred.** Outbound email is the hard part (port 25 often blocked, rDNS/PTR at
the host, IP reputation). Recommended workaround when the time comes: self-host the
mailboxes but **relay outbound through a reputable EU SMTP**. Since backups and DNS are
already shared, the add-on blocks none of the earlier phases.

---

## ADR-009 — Documentation: MkDocs Material + llms.txt

**Context.** Docs must be published on GitHub Pages and **usable by AI** for future
development.

**Decision.** **MkDocs + Material**. The decisive "AI-friendly" criterion is a
**pure-Markdown source** (an agent reads `docs/**/*.md` with no noise), which rules out
Docusaurus (MDX/JSX). The `mkdocs-llmstxt` plugin publishes `/llms.txt` and
`/llms-full.txt`.

**Consequences.** A site that's readable for humans, an ideal raw source for agents,
and a fetchable full-text dump. Per-version docs via `mike`, aligned with releases
(to enable later).

---

## ADR-010 — Testing & CI strategy: a layered, evolving harness

**Context.** ADR-002 makes Ansible the host provisioner and ADR-006 promises a CI
pipeline that replays **install → upgrade → restore** so the backup/restore promise
stays true over time. We need automated tests from Phase 0 that are cheap enough to run
on every change, yet able to grow into that full pipeline without being rebuilt.

**Decision.** A **three-layer** test harness, established in Phase 0 and extended one
phase at a time. The *harness* (Molecule + Testinfra + a Debian 12/13 matrix) is the
stable contract; each phase only adds scenarios and assertions.

1. **Static** — `yamllint`, `ansible-lint` (production profile),
   `ansible-playbook --syntax-check`. Runs on every PR in seconds (`make lint`).
2. **Per-role container** — Molecule (Docker driver, systemd-enabled Debian images)
   converges the host-prep roles, asserts **idempotence** (a second run changes
   nothing), then **Testinfra** asserts the resulting state (swap, sysctl, ufw rules,
   fail2ban, SSH hardening). Runs on every PR across Debian 12 and 13 (`make test`).
3. **Full definition-of-done** — Molecule's `full` scenario runs the *entire* bootstrap
   incl. a real, pinned K3s install in a privileged systemd container, then asserts the
   node reaches `Ready` and the core components (CoreDNS, Traefik, local-path) are up.
   Heavy, so it runs **nightly and when the K3s role changes** (`make test-full`).

**Why layered.** Most changes are caught in seconds by layers 1–2; the expensive
real-cluster check (layer 3) is reserved for what actually affects the cluster. The DoD
is still machine-verified, just not on every PR.

**How it evolves.** Phase 1 adds a scenario asserting `helmfile sync` brings the shared
infra up; Phase 3 adds the install → upgrade → **restore** replay ADR-006 mandates. The
Phase 1 Helmfile layer runs on **k3d** (purpose-built for in-cluster Helm e2e) with the
same pytest-style assertions, kept in a dedicated, cost-aware workflow
(`helmfile-e2e.yml`) — the layered philosophy holds; only the substrate fits the tool.

**Consequences.** Robust feedback proportional to risk, and a test foundation that the
later phases inherit instead of reinventing. Cost: Molecule/Testinfra are Python dev
dependencies, and the nightly full run consumes CI minutes (bounded to the two Debian
targets).

---

## ADR-011 — Keycloak via the `codecentric/keycloakx` chart (not the Operator)

**Context.** ADR-005 mandates a self-hosted Keycloak (1 realm, 1 OIDC client per app).
Bitnami is banned (ADR-004). Three credible install methods remain: the
`codecentric/keycloakx` Helm chart, the official **Keycloak Operator** (Quarkus, with
`Keycloak`/`KeycloakRealmImport` CRs), or a hand-rolled local chart. The deciding
criterion is long-term **upgradeability** on a single VPS (ADR-007).

**Decision.** Use **`codecentric/keycloakx`** — the chart `lasuite-platform` already
relies on, with realm import via `--import-realm` from a ConfigMap that
`platform-configuration` generates.

**Why not the Operator.** What makes a Keycloak upgrade risky — the Liquibase DB schema
migration on first boot — is identical for every method; safety comes from the
backup-gated upgrade flow (ADR-006/007), not the installer. Given that, the chart is the
*better* fit for our constraints: the Keycloak version is just an image tag we control,
**decoupled** from the chart and tracked by Renovate, so a security patch is a one-line
bump (`helmfile apply` = `helm upgrade`, `helm rollback` for the objects). The Operator
instead couples the operator and Keycloak versions, ships an OLM auto-update footgun that
fights our "everything pinned, explicit diffs" rule, runs an always-on controller for a
single instance, and offers a Job-based realm import with no advantage over `--import-realm`
for our seed-derived realm.

**Consequences.** Minimal moving parts, upgrades that slot straight into Renovate + CI +
the future `suite` CLI. Residual risk: dependence on a third-party chart — mitigated
because the Keycloak image is independently pinned and the thin chart can be vendored
locally if its maintenance ever lapses.

---

## ADR-012 — Secrets derived from a single `secretSeed` via Helm templating

**Context.** Every credential (Postgres roles, Keycloak admin/DB, Valkey, S3, per-app
OIDC client secrets) must exist without committing any plaintext (hard rule), on a target
that is a **single VPS** run by non-experts. Options range from a secrets manager
(Vault/External Secrets) or SOPS to in-template derivation.

**Decision.** Derive **everything from one `secretSeed`** with a Helm template helper —
`deriveSecret = sha256sum("<seed>:<id>")` truncated, with an optional `secretOverrides`
map. The seed is supplied at sync time via `requiredEnv "OWNSUITE_SECRET_SEED"` and is
**never** written to the repo or stored in the cluster. Derivation lives in exactly one
place (the `platform-configuration` chart, which emits Kubernetes Secrets); consumers
reference those by `secretKeyRef`/`existingSecret` rather than re-deriving.

**Why not SOPS / External Secrets.** Both add an operational component (a KMS, an
operator, key rotation) that a volunteer must run and recover during a restore — overkill
for one node. Deterministic derivation means Keycloak and an app compute the *same* secret
for the same id with zero sync, and disaster recovery needs only the seed.

**Consequences.** No secret material in git, a single high-value secret to protect
(`$OWNSUITE_SECRET_SEED`), and reproducible credentials across rebuilds. Trade-off:
rotating one derived secret means changing the seed (rotates all) or adding an explicit
override; SOPS/External Secrets remain a possible later evolution if requirements grow.

---

## ADR-013 — TLS issuance: cert-manager HTTP-01 per-subdomain (wildcard DNS-01 deferred)

**Context.** Phase 1's definition of done is **Keycloak reachable over HTTPS**. Traefik is
bundled with K3s; cert-manager handles certificates. ACME offers HTTP-01 (per host, needs
port 80 + public DNS) or DNS-01 (wildcards, needs a DNS-provider API credential).

**Decision.** Use cert-manager with a **`letsencrypt-http01`** ClusterIssuer per subdomain
through the Traefik ingress for production, and a **`selfsigned`** ClusterIssuer for CI/dev
(no public DNS). The Keycloak ingress selects the issuer via `tls.issuer`.

**Why not DNS-01 wildcard now.** A `*.{domain}` certificate needs a chosen DNS provider and
an API credential — exactly the "domain → DNS" experience **Phase 4** owns. HTTP-01 needs
nothing but the port 80 the firewall already opens, so it is the right minimum for Phase 1.

**Consequences.** HTTPS works on a bare VPS with no DNS-provider integration, and CI proves
end-to-end TLS termination with the self-signed issuer (Let's Encrypt cannot be exercised
without public DNS). DNS-01 wildcard becomes an additive ClusterIssuer in Phase 4 — no
rework of the issuer-selection seam.

---

## ADR-014 — Operator control plane: local workstation + SSH tunnel

**Context.** The Ansible bootstrap (ADR-002) runs remotely (workstation → VPS over
SSH). The Phase 1 Helmfile layer needs the Kubernetes API (port 6443), but the
firewall opens only 22/80/443 and the fetched kubeconfig points at
`https://127.0.0.1:6443`. We must decide where `helmfile`/`kubectl`/the future `suite`
CLI run, and how they reach the API.

**Decision.** The **operator's workstation is the single control plane**. The repo is
cloned locally once; nothing is installed on the VPS beyond what the bootstrap lays
down. `helmfile`/`kubectl`/the `suite` CLI reach the cluster through an **SSH tunnel**
to `127.0.0.1:6443` (`make tunnel`). The K8s API is **never exposed** — 6443 stays out
of the firewall. The bootstrap-fetched kubeconfig is used **unchanged**: its
`127.0.0.1:6443` server is correct through the tunnel, and the K3s API certificate
lists `127.0.0.1` in its SANs, so TLS verification holds (no rewriting, no `--insecure`).

**Why not run on the VPS.** It would mean cloning the repo and installing tooling on
the box, splitting the workflow across two machines. **Why not expose 6443.** It
enlarges the attack surface for no benefit on a single VPS; a tunnel is free and keeps
the API private.

**Consequences.** One place to operate from, a minimal VPS, and a private API. The
tunnel must be open during `sync` (a manual `make tunnel` for now). The Phase 4
installer / Phase 5 `suite` CLI will open the tunnel automatically, making this
invisible — they implement this model rather than change it.

---

## ADR-015 — In-cluster object storage: Garage (single-node), deterministic key

**Context.** [ADR-003](#adr-003-pluggable-object-storage-garage-or-external-eu-s3) made
object storage pluggable — Garage (self-hosted) or external EU S3 — and Phase 1 only
*derived* the S3 credentials; nothing was deployed. Phase 2's Docs app needs a real
bucket, and the hermetic k3d e2e ([ADR-010](#adr-010-testing-ci-strategy-a-layered-evolving-harness))
needs an S3 backend that exists with no external account. MinIO is banned (ADR-004).

**Decision.** Deploy **Garage** in-cluster as a single-node `StatefulSet`, via a local
chart (`helmfile/charts/garage`), gated on `objectStorage.mode == garage`. Garage runs
with `replication_factor = 1`; its RPC secret and admin token are seed-derived and
injected as `GARAGE_RPC_SECRET` / `GARAGE_ADMIN_TOKEN` env vars, so `garage.toml` stays
secret-free and committed-safe. A post-install Helm-hook **bootstrap Job** (least-privilege
`kubectl exec` into the pod) idempotently assigns the cluster layout, **imports the
seed-derived S3 access key/secret** (the same `s3-credentials` the app consumes — no
read-back, no manual sync), creates the bucket, and grants access. `helm --wait` blocks
the release — and Docs, which `needs` it — until the store is usable.

**Why import the key rather than generate it.** Derivation stays one-way (ADR-012): the
single seed reproduces both the app's credentials and Garage's. Garage's `key import`
accepts arbitrary conforming strings (id ≥8 alnum/`-_.`, secret ≥16 graphic ASCII), so the
existing derived creds are imported as-is. **Production default stays external S3** (ADR-003):
in `external` mode nothing is deployed and Docs points at the configured endpoint.

**Consequences.** A real, sovereign object store on one node and a fully hermetic e2e, at a
tiny footprint (Rust; ~128Mi request). Off-site object backup is still required (ADR-006,
Phase 3). The bootstrap Job depends on a pinned community `kubectl` image — acceptable, and
the only non-distroless piece (Garage's own image ships no shell).

---

## ADR-016 — Docs (impress) integration: one namespace, Traefik ingress, OIDC split

**Context.** Phase 2 wires the first app — **Docs** (`suitenumerique` / impress) — to the
whole foundation. Three integration choices were left open by Phase 1: where apps live
(namespace), how the upstream chart's **nginx**-oriented ingress maps onto our **Traefik**
(K3s-bundled), and how a backend inside the cluster talks OIDC to a Keycloak that issues
browser-facing URLs.

**Decision.**
- **One workloads namespace.** Docs runs in the same `ownsuite` namespace as the Phase 1
  infra, reusing the secrets already there. No per-app namespaces or cross-namespace secret
  reflector in v1 — unnecessary moving parts for a single VPS. (Per-app namespaces remain a
  clean later evolution.)
- **Traefik ingress.** The official chart ships nginx annotations; we override them for
  Traefik. Websockets need no annotation (Traefik proxies them natively), and a single
  y-provider replica removes the need for room-sticky routing. Authenticated **media
  serving** is reproduced with two Traefik middlewares (a `forwardAuth` to the backend
  media-auth endpoint + a path rewrite to the bucket), defined in `platform-configuration`.
  cert-manager issues one `docs-tls` certificate on the main ingress; the sibling ingresses
  reuse it for the same host.
- **OIDC external/internal endpoint split.** The browser-facing endpoints
  (authorization, logout) point at `https://auth.{domain}`; the backend-to-Keycloak
  endpoints (JWKS, token, userinfo) point at the in-cluster service
  `keycloak-keycloakx-http`. `OIDC_VERIFY_SSL` is off under the self-signed issuer. The
  `docs` OIDC client (confidential, secret derived from the same seed id the app reads) is
  appended to `keycloak.clients`, so the realm and the app agree with no manual sync.

**Realm import on an existing install.** `--import-realm` only imports on Keycloak's
**first** boot, so adding the `docs` client to an *already-imported* realm has no effect on
upgrade. Acceptable for a fresh install / CI (the path Phase 2 proves). For an existing
install the client must be added out-of-band (Keycloak admin API / `kcadm`, or a one-shot
upsert Job); this is documented and slated for the Phase 4 installer / Phase 5 `suite` CLI,
which own the upgrade flow.

**Consequences.** Docs is reachable over HTTPS with real SSO and persistent storage, proven
by CI. The DoD is verified at the API level (a Keycloak-issued token creates and reads back
a document — see [ADR-010](#adr-010-testing-ci-strategy-a-layered-evolving-harness)); a full
browser-driven SSO/collaboration check is deferred to a targeted job. The one-namespace and
realm-import-on-first-boot choices are explicit simplifications to revisit as the suite
broadens (Phase 5).

---

## ADR-017 — Backups & tested restore: Barman Cloud Plugin, rclone, off-site by design

**Context.** [ADR-006](#adr-006-backups-and-tested-restore) commits to backing up the **three
sources of state** and to a **tested** restore. Phase 3 implements it on the running stack:
CNPG (operator **1.29.1**, chart 0.28.3), Keycloak + Docs databases, an object store that is
in-cluster Garage *or* external S3, and cert-manager already deployed. The decisions left open
were the PostgreSQL backup mechanism, the object-copy tool, the off-site destination + its
credentials, the depth of Keycloak backup, and how to prove the cycle hermetically in CI.

**Decision.**

- **PostgreSQL → CNPG Barman Cloud Plugin** ([v0.13.0](https://github.com/cloudnative-pg/plugin-barman-cloud),
  the CNPG-I plugin), not the in-tree `.spec.backup.barmanObjectStore` (deprecated since CNPG
  1.26). The plugin is installed from its **pinned, vendored** release manifest
  (`charts/barman-cloud-plugin`) into `cnpg-system`, reusing cert-manager for its TLS. A
  `barmancloud.cnpg.io/v1` **`ObjectStore`** describes the off-site S3; the `Cluster` references
  it via `spec.plugins` (`isWALArchiver`) for continuous WAL archiving + base backups; a
  `ScheduledBackup` (`method: plugin`) anchors the recovery window. Recovery is a fresh
  `Cluster` with `bootstrap.recovery` + an `externalClusters` plugin entry pointing at the same
  store — restoring the **whole instance**, hence both the `keycloak` and `docs` databases. The
  restored cluster *reads* the original `serverName` but *archives* under a distinct one
  (`<cluster>-restored`): CNPG runs `barman-cloud-check-wal-archive` first and refuses a
  destination that already holds an archive, so reusing the source `serverName` would block it.
- **Objects (media) → `rclone`** (pinned image), an S3→S3 `sync` CronJob from the primary
  bucket to the off-site store, **client-side encrypted** through an rclone `crypt` remote. A
  one-shot Job syncs back during restore. Chosen over `restic` because the source is already an
  S3 bucket (no filesystem to snapshot). Required in **both** garage and external modes (ADR-006).
- **Keycloak → PITR only.** Keycloak keeps realm + users in its `keycloak` database, which CNPG
  recovery restores verbatim (the user's subject/id is stable, so JIT-provisioned app accounts
  map back). This **refines** ADR-006's "scheduled realm export": a separate `kc.sh` export adds
  a recurring Job and RAM pressure on a single VPS for portability we don't need in v1. Deferred,
  not forbidden — it stays an easy add-on for migration/portability later.
- **Off-site by construction.** The backup destination is a **distinct** S3 (`OWNSUITE_BACKUP_S3_*`)
  that must survive loss of the VPS — **never** the in-cluster Garage being backed up. In
  **production** it is a managed S3 in a *different account/provider* than the primary; in **CI**
  it is a **second in-cluster Garage** (`garage-backup`, own PVC/service/bucket) that is *kept*
  when the primary is destroyed — hermetic, and respecting the no-MinIO rule. The off-site
  credentials and the rclone crypt passphrase are **seed-derived by default** (so CI and
  self-controlled targets need no manual sync) and **overridable** (`secretOverrides` ids
  `backup-s3-access` / `backup-s3-secret` / `rclone-crypt`, or an untracked Secret) for a real
  external account ([ADR-012](#adr-012-secrets-derived-from-a-single-secretseed-via-helm-templating)).

**Why not the in-tree barmanObjectStore.** It is deprecated (CNPG 1.26+) and slated for removal;
building Phase 3 on it would mean migrating immediately. The plugin is the supported path on our
version, its only extra dependency (cert-manager) is already present, and the image is pinned
inside the vendored manifest (Renovate-tracked, re-vendored on bump).

**Encryption & retention — honest limits.** PostgreSQL backups rely on **TLS in transit** plus
the destination's **at-rest** protection (optional S3 SSE `AES256` via
`OWNSUITE_BACKUP_PG_ENCRYPTION`, left off for S3-compatible stores like Garage that don't support
it); **objects** get **client-side** encryption via the rclone `crypt` remote. Retention is a
Barman **recovery window** (e.g. `30d`) for PITR, not true grandfather-father-son — GFS-style
retention is expressed on the object copy / bucket lifecycle. Full GFS for PostgreSQL is a later
enhancement.

**Tested in CI (the deliverable).** The k3d e2e ([ADR-010](#adr-010-testing-ci-strategy-a-layered-evolving-harness))
runs one hermetic **backup → destroy → restore** cycle: sync with backups on, assert the Phase-2
DoD (creating the survivor document), seed a media object, take an on-demand base backup + an
off-site object copy, **destroy** the primary state (DB + primary store + apps; keep
`platform-configuration` + `garage-backup` + the operators), `make restore`, then assert the
document and the Keycloak user **survived** and the media object is back. Kept on the existing
cost-aware triggers (nightly + on `helmfile/**`), with the same fail-fast watchdog. This is the
machine-checked Phase-3 definition of done and the seed of the install→upgrade→restore replay
ADR-006/ADR-010 promise; `make restore` prefigures the backup-gated `suite restore`
([ADR-007](#adr-007-upgrade-model-semver-releases-backup-gated-cli)).

**Consequences.** Credible, *proven* disaster recovery from off-site backups with one seed and
one command. Cost: a heavier nightly e2e, a small barman sidecar next to PostgreSQL, an rclone
CronJob, and (in CI) a second Garage — all kept on modest `requests`/`limits` so Keycloak and
Docs are not starved on a single VPS. Operator guide: [Backups & restore](../operate/backups.md).

---

## ADR-018 — Phase 4 guided installer (`suite install`)

**Context.** Phases 0–3 leave a working stack driven by a **manual sequence** (`make bootstrap`
→ edit/source `.env` → `make tunnel` → `make sync` → curl-check HTTPS — see
[platform.md](platform.md)). The Phase 4 promise is "bare VPS + a domain →
all-in-HTTPS by following the screen". We must decide the installer's form and language, how it
reaches the cluster, and how it handles the single secret.

**Decision.** A small **Python package `suite/`** (standard library only — `argparse`,
`secrets`, `urllib`, `subprocess`), invoked as `python -m suite install` and wrapped by
`make install`. It **orchestrates the existing layers** rather than reimplementing them: capture
config → (optional) `make bootstrap` → detect the VPS public IP over SSH → print the exact DNS
records → wait for propagation → open the SSH tunnel (ADR-014) → `helmfile sync` → issue
certificates (ADR-019) → verify HTTPS per host. Every step is idempotent, so the replay story is
simply **re-running `suite install`** (no resume bookkeeping). The **seed is generated with
`secrets.token_hex(24)`, shown once, and never written to the repo**; on re-run the operator
re-exports `OWNSUITE_SECRET_SEED` (non-secret `OWNSUITE_*` are saved to the git-ignored `.env`).
A `--non-interactive` / `--no-tunnel` / `--tls-mode` surface lets CI drive the same code path
against k3d.

**Why Python, standard-library only.** pytest is already the harness (ADR-010), so the
DNS-record generation and propagation logic are unit-tested with fakes, and Python prefigures the
Phase 5 `suite` CLI (ADR-007). **No third-party runtime dependency is added**: propagation shells
out to `dig` (ubiquitous), HTTPS verification uses the standard library's own TLS trust check, and
everything else is `subprocess` to `ssh`/`helmfile`/`kubectl` — tools the operator already has.
The installer runs on the operator's workstation, adding nothing to the single VPS.

**Consequences.** One command takes an operator from a bare VPS to HTTPS, the SSH tunnel becomes
invisible, and the manual flow stays documented as the fallback. The installer is a thin
orchestrator with no privileged cluster component. It only *prefigures* the `suite` CLI: a single
`install` verb, with upgrades/restore (`suite upgrade` / `suite restore`) left to Phase 5.

---

## ADR-019 — Phase 4 TLS: staging-first issuance, DNS-01 deferred

**Context.** ADR-013 shipped the issuer seam (`tls.issuer` selects a ClusterIssuer **by name**;
the ingress annotation follows it) with `selfsigned` and `letsencrypt-http01`, and explicitly
handed the wildcard DNS-01 issuer to Phase 4 "as an additive ClusterIssuer — no rework of the
seam". The installer must issue *real* certificates without burning Let's Encrypt's tight
**production** rate limits on a misconfiguration.

**Decision.** Add an **additive `letsencrypt-staging` ClusterIssuer** (HTTP-01 via Traefik, the
Let's Encrypt staging directory, a *distinct* account-key Secret so the staging and production
ACME accounts never collide) and wire the previously-dead `acmeServer`/`acmeStagingServer` chart
values through. The installer issues against **staging first**, verifies the path end to end, then
**promotes to production** by re-syncing with `tls.issuer=letsencrypt-http01` and waiting for the
same `keycloak-tls`/`docs-tls` certificates to go Ready again. No ingress or Certificate resource
changes — the annotation already follows `tls.issuer`.

**Wildcard A record ≠ wildcard certificate; DNS-01 deferred.** The installer generates a wildcard
**A record** (`*.{domain}`) so every subdomain resolves, but v1 keeps issuing **per-host
certificates** (`auth.`, `docs.`) over HTTP-01 — which needs only the port 80 the firewall already
opens. A true `*.{domain}` *certificate* would require explicit Certificate CRs and pointing the
ingresses at a shared secret — exactly the seam rework ADR-013 forbids — so the **DNS-01 wildcard
issuer is deferred**. The seam stays ready: a future `letsencrypt-dns01` ClusterIssuer (with a
DNS-provider token Secret — the first credential *not* derived from the seed) is purely additive.

**Consequences.** Real HTTPS on a bare VPS with **zero DNS-provider credentials**, proven
staging-first so production rate limits stay safe. CI keeps using `selfsigned` (no public DNS).
The single-seed invariant (ADR-012) is preserved in v1 because no DNS-provider credential is
introduced yet.

---

## ADR-020 — Keycloak realm convergence: idempotent OIDC client upsert

**Context.** ADR-016 noted that Keycloak's `--import-realm` only seeds the realm on its **first**
boot, so adding or changing an OIDC client on an already-imported realm has no effect on upgrade —
and slated the fix for "the Phase 4 installer / Phase 5 `suite` CLI". Phase 4 ships it.

**Decision.** A new local chart **`keycloak-config`**, deployed as a Helmfile release ordered
after Keycloak (`needs: keycloak`), runs an idempotent **`kcadm` upsert Job** (a
post-install/post-upgrade Helm hook with `before-hook-creation` delete, so it re-runs on every
sync — mirroring the Garage bootstrap Job of ADR-015). For each `keycloak.clients` entry it
create-or-updates the OIDC client (redirect URIs, web origins, flags, secret) with `kcadm.sh` from
the **already-pinned Keycloak image** — no new image, and no Kubernetes API access (it talks to the
in-cluster Keycloak HTTP service). Per ADR-012, derivation stays in one place:
`platform-configuration` emits a `keycloak-oidc-clients` Secret (one key per client, derived from
the same `<clientId>-oidc` id the app and the realm import use), which the Job consumes by
secretKeyRef — it never re-derives.

**Consequences.** Adding or changing an app's OIDC client now takes effect on a **running**
install, not just a fresh one — the day-2 path ADR-016 deferred. `helm --wait` blocks the sync
until the clients are reconciled, and the e2e exercises the Job on every run (the SSO
definition-of-done mints a token with the upserted `docs` client). The realm import remains the
first-boot seed; the Job is the authoritative reconciler thereafter.
