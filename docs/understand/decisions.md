# Architecture Decision Records (ADR)

A log of the structural choices, in a lightweight *Context → Decision → Consequences*
format. Each decision is numbered so it can be referenced and revised.

---

## ADR-001 — K3s + Helmfile (not Compose or raw Helm)

**Context.** La Suite's official production path is Helm; the apps' `compose.yml`
files are flagged *dev only*. We target a single server.

**Decision.** A **single-node K3s** cluster orchestrated with **Helmfile**. Helmfile
is `helm upgrade --install` done with discipline: it brings dependency ordering
(`config → postgres → keycloak → apps`), a preview (`helmfile diff`) and environments.

**Consequences.** We reuse the official charts (less drift). Traefik and ServiceLB
come bundled with K3s. Trade-off: a Kubernetes learning curve, hidden behind an
installer and a `suite` CLI.

---

## ADR-002 — Ansible for the host (not Nix)

**Context.** We must provision the server (firewall, fail2ban, swap, sysctl, patches,
K3s install) reproducibly. Target audience: non-profit volunteers, not Kubernetes/Nix
experts.

**Decision.** **Ansible** for host configuration and the K3s install.

**Why not Nix.** NixOS's headline advantage — atomic generation rollback — only
restores the **OS config**, not the cluster state (K3s sqlite/etcd, volumes, app
data). For a **stateful** stack, that rollback hands you an empty shell you must
restore from backups anyway: you'd pay Nix's entry cost without reaping its real
benefit. Add a much smaller contributor pool and scarce server images. A community NixOS
variant remains possible later, off the main path.

**Consequences.** Low barrier for admins and contributors; re-runnable playbooks for
OS/K3s version bumps. Drift is possible on manual edits (mitigated by idempotence and CI).

---

## ADR-003 — Pluggable object storage: Garage or external EU S3

**Context.** MinIO (community) is **archived** (February 2026): console removed,
binaries/images discontinued. Drive can store hundreds of GB.

**Decision.** **Pluggable** object storage via config: a **managed EU S3** (Scaleway,
OVH, AWS) **or** **Garage** (self-hosted, French, lightweight). Recommended production
default: **external S3 on Scaleway** — its Object Storage is CORS-capable, which Drive's
browser uploads require ([ADR-038](#adr-038-hosting-provider-scaleway-recommended-infomaniak-alternative)).

**Consequences.** No storage ops with external S3, smaller server disk, simpler backups;
Garage for full sovereignty or CORS-incapable hosts (Infomaniak's Swift+s3api). Even with
external S3, an **off-site application-level backup** of the objects is still required
(accidental deletion, lock-in).

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
command. GitOps (Flux/ArgoCD) is possible later; deemed overkill for a single server in v1.

**Concrete tooling.** **Renovate** (`renovate.json`), not Dependabot — one
tool that tracks *every* pin we ship: Python tooling (`requirements-*.txt`), **Ansible
Galaxy collections** (`ansible/requirements.yml`, `molecule/requirements.yml`), GitHub
Actions, and the **K3s release** in `ansible/group_vars/all.yml` (via a custom manager
against the `k3s-io/k3s` releases). Dependabot would only cover a subset and would race
Renovate with duplicate PRs, so it is intentionally omitted. Each bump is a PR gated by
the [ADR-010](#adr-010-testing-ci-strategy-a-layered-evolving-harness) test harness, so
"stay current" never means "stay untested".

---

## ADR-008 — Mailbox out of scope for v1 (feasible as an add-on)

> **Superseded in part by [ADR-021](#adr-021-mailbox-suitenumeriquemessages-outbound-via-eu-relay).** The "out of v1, optional add-on" stance and
> the "relay outbound through a reputable EU SMTP" workaround still hold; the mail stack is now
> **suitenumerique/messages**, not Stalwart.

**Context.** La Suite numérique provides **no** mail server. The request "create
`firstname@assoc.org` with their mailbox" requires a separate stack.

**Decision.** **Out of v1.** Architecturally feasible later: a mail server
(**Stalwart** recommended, native OIDC) federated to the **same Keycloak**, with
MX/SPF/DKIM/DMARC records added to the DNS flow and provisioning wired into the
`suite` CLI.

**Why deferred.** Outbound email is the hard part (port 25 often blocked, rDNS/PTR at
the host, IP reputation). Recommended workaround when the time comes: self-host the
mailboxes but **relay outbound through a reputable EU SMTP**. Since backups and DNS are
already shared, the add-on blocks none of the earlier work.

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
stays true over time. We need automated tests from the start that are cheap enough to run
on every change, yet able to grow into that full pipeline without being rebuilt.

**Decision.** A **three-layer** test harness, established at the outset and extended
incrementally. The *harness* (Molecule + Testinfra + a Debian 12/13 matrix) is the
stable contract; each increment only adds scenarios and assertions.

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

**How it evolves.** The shared-infra work adds a scenario asserting `helmfile sync` brings
the shared infra up; the backup work adds the install → upgrade → **restore** replay ADR-006
mandates. The Helmfile layer runs on **k3d** (purpose-built for in-cluster Helm e2e) with the
same pytest-style assertions, kept in a dedicated, cost-aware workflow
(`helmfile-e2e.yml`) — the layered philosophy holds; only the substrate fits the tool. The
apps — every one of them — get their boot definition of done in a per-app
matrix ([ADR-029](#adr-029-per-app-nightly-e2e-one-app-per-cluster)), one app per fresh cluster,
which is the **single source** of each app's boot DoD. The full suite e2e therefore asserts **no
application**: it is platform + `suite install` + backup/restore only.
The same reasoning applies *within* the Helmfile layer: the full suite e2e (`make test-platform`,
~15 images, 20–45 min, prone to shared-runner flakiness) is too heavy and slow to gate every PR,
so a change to one component gets an **isolated, fast component e2e** that boots only that
component's dependencies and runs the **same shared assertion code** as the full suite. The first
is the PVC backup/restore round-trip ([ADR-032](#adr-032-standardised-reusable-off-site-pvc-backup)),
which gates PRs in ~3 min via `make test-pvc-backup`; the full suite moved to nightly / `main` /
`workflow_dispatch` only. The shared round-trip lives in `helmfile/tests/lib.sh`, so the fast and
full harnesses can never drift.

**Consequences.** Robust feedback proportional to risk, and a test foundation that the
later work inherits instead of reinventing. Cost: Molecule/Testinfra are Python dev
dependencies, and the nightly full run consumes CI minutes (bounded to the two Debian
targets).

---

## ADR-011 — Keycloak via the `codecentric/keycloakx` chart (not the Operator)

**Context.** ADR-005 mandates a self-hosted Keycloak (1 realm, 1 OIDC client per app).
Bitnami is banned (ADR-004). Three credible install methods remain: the
`codecentric/keycloakx` Helm chart, the official **Keycloak Operator** (Quarkus, with
`Keycloak`/`KeycloakRealmImport` CRs), or a hand-rolled local chart. The deciding
criterion is long-term **upgradeability** on a single server (ADR-007).

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
that is a **single server** run by non-experts. Options range from a secrets manager
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

**Context.** The foundation's goal is **Keycloak reachable over HTTPS**. Traefik is
bundled with K3s; cert-manager handles certificates. ACME offers HTTP-01 (per host, needs
port 80 + public DNS) or DNS-01 (wildcards, needs a DNS-provider API credential).

**Decision.** Use cert-manager with a **`letsencrypt-http01`** ClusterIssuer per subdomain
through the Traefik ingress for production, and a **`selfsigned`** ClusterIssuer for CI/dev
(no public DNS). The Keycloak ingress selects the issuer via `tls.issuer`.

**Why not DNS-01 wildcard now.** A `*.{domain}` certificate needs a chosen DNS provider and
an API credential — exactly the "domain → DNS" experience **the installer** owns. HTTP-01 needs
nothing but the port 80 the firewall already opens, so it is the right minimum for the foundation.

**Consequences.** HTTPS works on a bare server with no DNS-provider integration, and CI proves
end-to-end TLS termination with the self-signed issuer (Let's Encrypt cannot be exercised
without public DNS). DNS-01 wildcard becomes an additive ClusterIssuer in the installer — no
rework of the issuer-selection seam.

---

## ADR-014 — Operator control plane: local workstation + SSH tunnel

**Context.** The Ansible bootstrap (ADR-002) runs remotely (workstation → server over
SSH). The Helmfile layer needs the Kubernetes API (port 6443), but the
firewall opens only 22/80/443 and the fetched kubeconfig points at
`https://127.0.0.1:6443`. We must decide where `helmfile`/`kubectl`/the future `suite`
CLI run, and how they reach the API.

**Decision.** The **operator's workstation is the single control plane**. The repo is
cloned locally once; nothing is installed on the server beyond what the bootstrap lays
down. `helmfile`/`kubectl`/the `suite` CLI reach the cluster through an **SSH tunnel**
to `127.0.0.1:6443` (`make tunnel`). The K8s API is **never exposed** — 6443 stays out
of the firewall. The bootstrap-fetched kubeconfig is used **unchanged**: its
`127.0.0.1:6443` server is correct through the tunnel, and the K3s API certificate
lists `127.0.0.1` in its SANs, so TLS verification holds (no rewriting, no `--insecure`).

**Why not run on the server.** It would mean cloning the repo and installing tooling on
the box, splitting the workflow across two machines. **Why not expose 6443.** It
enlarges the attack surface for no benefit on a single server; a tunnel is free and keeps
the API private.

**Consequences.** One place to operate from, a minimal server, and a private API. The
tunnel must be open during `sync` (a manual `make tunnel` for now). The
installer / the `suite` CLI will open the tunnel automatically, making this
invisible — they implement this model rather than change it.

---

## ADR-015 — In-cluster object storage: Garage (single-node), deterministic key

**Context.** [ADR-003](#adr-003-pluggable-object-storage-garage-or-external-eu-s3) made
object storage pluggable — Garage (self-hosted) or external EU S3 — and the foundation only
*derived* the S3 credentials; nothing was deployed. The Docs app needs a real
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
off-site object backup). The bootstrap Job depends on a pinned community `kubectl` image — acceptable, and
the only non-distroless piece (Garage's own image ships no shell).

---

## ADR-016 — Docs (impress) integration: one namespace, Traefik ingress, OIDC split

**Context.** The first app wired in is **Docs** (`suitenumerique` / impress) — connected to the
whole foundation. Three integration choices were left open by the foundation: where apps live
(namespace), how the upstream chart's **nginx**-oriented ingress maps onto our **Traefik**
(K3s-bundled), and how a backend inside the cluster talks OIDC to a Keycloak that issues
browser-facing URLs.

**Decision.**
- **One workloads namespace.** Docs runs in the same `ownsuite` namespace as the foundation
  infra, reusing the secrets already there. No per-app namespaces or cross-namespace secret
  reflector in v1 — unnecessary moving parts for a single server. (Per-app namespaces remain a
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
upgrade. Acceptable for a fresh install / CI (the path Docs proves). For an existing
install the client must be added out-of-band (Keycloak admin API / `kcadm`, or a one-shot
upsert Job); this is documented and slated for the installer / the `suite` CLI,
which own the upgrade flow.

**Consequences.** Docs is reachable over HTTPS with real SSO and persistent storage, proven
by CI. The DoD is verified at the API level (a Keycloak-issued token creates and reads back
a document — see [ADR-010](#adr-010-testing-ci-strategy-a-layered-evolving-harness)); a full
browser-driven SSO/collaboration check is deferred to a targeted job. The one-namespace and
realm-import-on-first-boot choices are explicit simplifications to revisit as the suite
broadens.

---

## ADR-017 — Backups & tested restore: Barman Cloud Plugin, rclone, off-site by design

**Context.** [ADR-006](#adr-006-backups-and-tested-restore) commits to backing up the **three
sources of state** and to a **tested** restore. This ADR implements it on the running stack:
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
  a recurring Job and RAM pressure on a single server for portability we don't need in v1. Deferred,
  not forbidden — it stays an easy add-on for migration/portability later.
- **Off-site by construction.** The backup destination is a **distinct** S3 (`OWNSUITE_BACKUP_S3_*`)
  that must survive loss of the server — **never** the in-cluster Garage being backed up. In
  **production** it is a managed S3 in a *different account/provider* than the primary; in **CI**
  it is a **second in-cluster Garage** (`garage-backup`, own PVC/service/bucket) that is *kept*
  when the primary is destroyed — hermetic, and respecting the no-MinIO rule. The off-site
  credentials and the rclone crypt passphrase are **seed-derived by default** (so CI and
  self-controlled targets need no manual sync) and **overridable** (`secretOverrides` ids
  `backup-s3-access` / `backup-s3-secret` / `rclone-crypt`, or an untracked Secret) for a real
  external account ([ADR-012](#adr-012-secrets-derived-from-a-single-secretseed-via-helm-templating)).

**Why not the in-tree barmanObjectStore.** It is deprecated (CNPG 1.26+) and slated for removal;
building the backups on it would mean migrating immediately. The plugin is the supported path on our
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
runs one hermetic **backup → destroy → restore** cycle: sync with backups on, provision a
`suite user` (the survivor user), seed a media object, exercise a PVC backup round-trip, take an
on-demand base backup + an off-site object copy, **destroy** the primary state (DB + primary store +
apps; keep `platform-configuration` + `garage-backup` + the operators), `make restore`, then assert
all **three storage classes survived**: the Keycloak user (Postgres PITR), the media object (rclone
object-copy) and the PVC document (`pvc_backup_roundtrip`). The survivor is **app-agnostic** — the
user is looked up through the Keycloak admin REST API (the path `suite user` uses), not an app's OIDC
client, so the restore DoD no longer needs any application booted. (It originally read back a Docs
document; once apps went off-by-default — [ADR-035](#adr-035-every-app-off-by-default-opt-in-install) —
the survivor was decoupled so the full suite asserts no app. Docs stays enabled in the harness
*solely* to give the object-copy check a primary bucket — a fixture, not an app DoD.) Kept on the
existing cost-aware triggers (nightly + on `helmfile/**`), with the same fail-fast watchdog. This is
the machine-checked backup/restore definition of done and the seed of the install→upgrade→restore
replay ADR-006/ADR-010 promise; `make restore` prefigures the backup-gated `suite restore`
([ADR-007](#adr-007-upgrade-model-semver-releases-backup-gated-cli)).

**Consequences.** Credible, *proven* disaster recovery from off-site backups with one seed and
one command. Cost: a heavier nightly e2e, a small barman sidecar next to PostgreSQL, an rclone
CronJob, and (in CI) a second Garage — all kept on modest `requests`/`limits` so Keycloak and
Docs are not starved on a single server. Operator guide: [Backups & restore](../operate/backups.md).

---

## ADR-018 — Guided installer (`suite install`)

**Context.** The earlier work leaves a working stack driven by a **manual sequence** (`make bootstrap`
→ edit/source `.env` → `make tunnel` → `make sync` → curl-check HTTPS — see
[platform.md](platform.md)). The installer's promise is "bare server + a domain →
all-in-HTTPS by following the screen". We must decide the installer's form and language, how it
reaches the cluster, and how it handles the single secret.

**Decision.** A small **Python package `suite/`** (standard library only — `argparse`,
`secrets`, `urllib`, `subprocess`), invoked as `python -m suite install` and wrapped by
`make install`. It **orchestrates the existing layers** rather than reimplementing them: capture
config → (optional) `make bootstrap` → detect the server public IP over SSH → print the exact DNS
records → wait for propagation → open the SSH tunnel (ADR-014) → `helmfile sync` → issue
certificates (ADR-019) → verify HTTPS per host. Every step is idempotent, so the replay story is
simply **re-running `suite install`** (no resume bookkeeping). The **seed is generated with
`secrets.token_hex(24)`, shown once, and never written to the repo**; on re-run the operator
re-exports `OWNSUITE_SECRET_SEED` (non-secret `OWNSUITE_*` are saved to the git-ignored `.env`).
A `--non-interactive` / `--no-tunnel` / `--tls-mode` surface lets CI drive the same code path
against k3d.

**Why Python, standard-library only.** pytest is already the harness (ADR-010), so the
DNS-record generation and propagation logic are unit-tested with fakes, and Python prefigures the
`suite` CLI (ADR-007). **No third-party runtime dependency is added**: propagation shells
out to `dig` (ubiquitous), HTTPS verification uses the standard library's own TLS trust check, and
everything else is `subprocess` to `ssh`/`helmfile`/`kubectl` — tools the operator already has.
The installer runs on the operator's workstation, adding nothing to the single server.

**Consequences.** One command takes an operator from a bare server to HTTPS, the SSH tunnel becomes
invisible, and the manual flow stays documented as the fallback. The installer is a thin
orchestrator with no privileged cluster component. It only *prefigures* the `suite` CLI: a single
`install` verb, with upgrades and restore landing later as
[`suite upgrade`](#adr-034-suite-upgrade-backup-gated-snapshot-diff-apply-health-rollback) and
[`suite restore`](#adr-036-suite-restore-backup-gated-clean-cluster-recovery).

---

## ADR-019 — TLS: staging-first issuance, DNS-01 deferred

**Context.** ADR-013 shipped the issuer seam (`tls.issuer` selects a ClusterIssuer **by name**;
the ingress annotation follows it) with `selfsigned` and `letsencrypt-http01`, and explicitly
handed the wildcard DNS-01 issuer to the installer "as an additive ClusterIssuer — no rework of the
seam". The installer must issue *real* certificates without burning Let's Encrypt's tight
**production** rate limits on a misconfiguration.

**Decision.** Add an **additive `letsencrypt-staging` ClusterIssuer** (HTTP-01 via Traefik, the
Let's Encrypt staging directory, a *distinct* account-key Secret so the staging and production
ACME accounts never collide) and wire the previously-dead `acmeServer`/`acmeStagingServer` chart
values through. The installer issues against **staging first**, verifies the path end to end, then
**promotes to production** by re-syncing with `tls.issuer=letsencrypt-http01` and waiting for the
same `keycloak-tls`/`docs-tls` certificates to go Ready again. No ingress or Certificate resource
changes — the annotation already follows `tls.issuer`.

**Wildcard record ≠ wildcard certificate; DNS-01 deferred.** The installer generates an apex
**A/AAAA** plus a wildcard **CNAME** (`*.{domain}` → apex) so every subdomain resolves off a
single address record, but v1 keeps issuing **per-host certificates** (`auth.`, `docs.`) over
HTTP-01 — which needs only the port 80 the firewall already opens. A true `*.{domain}` *certificate* would require explicit Certificate CRs and pointing the
ingresses at a shared secret — exactly the seam rework ADR-013 forbids — so the **DNS-01 wildcard
issuer is deferred**. The seam stays ready: a future `letsencrypt-dns01` ClusterIssuer (with a
DNS-provider token Secret — the first credential *not* derived from the seed) is purely additive.

**Consequences.** Real HTTPS on a bare server with **zero DNS-provider credentials**, proven
staging-first so production rate limits stay safe. CI keeps using `selfsigned` (no public DNS).
The single-seed invariant (ADR-012) is preserved in v1 because no DNS-provider credential is
introduced yet.

---

## ADR-020 — Keycloak realm convergence: idempotent OIDC client upsert

**Context.** ADR-016 noted that Keycloak's `--import-realm` only seeds the realm on its **first**
boot, so adding or changing an OIDC client on an already-imported realm has no effect on upgrade —
and slated the fix for "the installer / the `suite` CLI". This ADR ships it.

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

---

## ADR-021 — Mailbox: suitenumerique/messages, outbound via EU relay

> **Refined by [ADR-026](#adr-026-mailbox-integration-messages-django-oidc-split-reuse-the-seam-opensearch-deferred) (app integration) and [ADR-027](#adr-027-non-http-ingress-inbound-smtp-on-port-25-via-k3s-servicelb) (port-25 ingress).**
> Two component specifics below were revisited against the verified-current upstream
> (`suitenumerique/messages` v0.8.0, June 2026):
>
> - **OpenSearch is now optional upstream** — every `OPENSEARCH_*` variable is optional and an
>   unset `OPENSEARCH_URL` simply disables full-text mail search; delivery, storage and reading
>   are unaffected. To keep the single-VPS RAM budget honest (OpenSearch single-node is ~1–2 GB
>   of JVM heap), v1 ships **without** it; search returns behind its own flag later. The
>   "heavier than Stalwart" consequence below stands but is lighter than first feared.
> - **DKIM key is supplied, not DB-generated.** messages accepts `MESSAGES_DKIM_PRIVATE_KEY_B64`,
>   so the installer generates the keypair once and treats it as an external override (the S3-creds
>   pattern), publishing the public key as a TXT record up front — no two-step DNS dance.

**Context.** ADR-008 deferred mail and tentatively recommended Stalwart. Since then,
**suitenumerique/messages** has become La Suite's own mail app, so adopting it keeps the
mailbox consistent with the rest of the suite (same look-and-feel, same Keycloak SSO) instead
of bolting on a foreign server + separate webmail. The earlier "IMAP + generic webmail" path
(Stalwart + Roundcube) was the lighter option but loses the integrated La Suite UX.

**Decision.** The mailbox is **suitenumerique/messages**, federated to the **same
Keycloak** via OIDC. It is a full mail provider, not an IMAP client:

- **Inbound:** its own **Postfix MTA-in** receives directly from the internet (domain MX →
  port 25) and relays to a Django **MDA** that stores and indexes mail (Postgres + Redis +
  **OpenSearch**).
- **Webmail:** ships its own **integrated web UI**. **No IMAP/POP3 by design** — users read
  mail in messages, not in Thunderbird/Apple Mail. Accepted trade-off.
- **Outbound:** **never direct from the VPS IP.** `MTA_OUT_MODE=relay` points the MTA-out at a
  reputable SMTP relay (STARTTLS, `MTA_OUT_RELAY_*` credentials,
  `MTA_OUT_SMTP_TLS_SECURITY_LEVEL=secure`). On the recommended Scaleway host that relay is native
  **Transactional Email (TEM)**, `smtp.tem.scaleway.com:2587` — the alternate port matters because
  Scaleway Instances block outbound 25/465/587 ([ADR-038](#adr-038-hosting-provider-scaleway-recommended-infomaniak-alternative)).
  Any EU relay works as an alternative (Infomaniak `mail.infomaniak.com:587`).

**Why.** Owning the easy half (receiving) and renting the hard half (deliverability) is the
same stance ADR-008 took — outbound from a fresh VPS IP loses on reputation/PTR/port-25. The
relay carries SPF/DKIM alignment; messages signs DKIM for the domain and SPF `include`s the relay.

**Consequences.**

- Integrated La Suite webmail; SSO and UX consistent with Docs/Drive. No second webmail to run.
- **No IMAP/POP3** — desktop/mobile mail clients are not supported; the web UI is the only client.
- **Heavier than the Stalwart path:** adds **OpenSearch** (RAM-hungry on a single VPS) + Redis +
  two Postfix containers. Server sizing must budget for it; the mailbox stays **optional and
  isolated**, blocking no earlier work.
- **Outbound is rate-capped by the relay** (Infomaniak: 1440 msg/24h, 100 recipients/msg). Set
  messages' `THROTTLE_MAILBOX_OUTBOUND_EXTERNAL_RECIPIENTS` /
  `THROTTLE_MAILDOMAIN_OUTBOUND_EXTERNAL_RECIPIENTS` below that ceiling so it fails gracefully
  in-app. Not suitable for bulk/newsletters — that's a separate product.
- Supersedes ADR-008's "Stalwart recommended" note; ADR-008's "optional add-on" and "relay
  outbound" decisions carry over unchanged.

---

## ADR-022 — Drive integration: reuse the Docs seam, per-app buckets

**Context.** As the suite broadens, **Drive** (`suitenumerique` / drive) is the
DoD-critical second app: `suite user add` must grant Docs **and** Drive immediately. Drive
is a `suitenumerique` sibling of Docs — same Django/Next.js shape, same official Helm chart
pattern, the same mozilla-django-oidc login — so the question is not *how to integrate a new
kind of app* but *what, if anything, the existing Docs seam
([ADR-016](#adr-016-docs-impress-integration-one-namespace-traefik-ingress-oidc-split)) must
grow* to host a second one. Drive needs no People/teams service (sharing is per-item), so it
takes on no new dependency.

**Decision.** Add Drive as a Helmfile release that **mirrors Docs almost verbatim**, and make
the few shared pieces multi-app instead of forking them:

- **Same foundation, per-app instances.** Drive reuses CNPG (its own `drive` database +
  owner role), Valkey, the pluggable S3 seam, and Keycloak SSO. Each app gets its **own**
  database, its **own** S3 bucket (`drive-media-storage`), and its **own** OIDC client
  (`drive`) — derived from the same seed
  ([ADR-012](#adr-012-secrets-derived-from-a-single-secretseed-via-helm-templating)) by the
  same `<id>` convention the realm import and the app already share. Adding `drive` to
  `keycloak.clients` is all the realm + the idempotent upsert Job
  ([ADR-020](#adr-020-keycloak-realm-convergence-idempotent-oidc-client-upsert)) need.
- **Distinct Valkey databases.** Docs and Drive share the one in-cluster Valkey, so Drive
  uses Redis **db 2** (cache) and **db 3** (Celery broker); Docs keeps 0/1. A separate broker
  db keeps the two apps' Celery queues from cross-consuming each other's tasks — the one real
  trap of co-tenanting a broker.
- **Garage creates a list of buckets.** The Garage bootstrap Job
  ([ADR-015](#adr-015-in-cluster-object-storage-garage-single-node-deterministic-key)) is
  generalised from one bucket to a **list** (the enabled apps' buckets); the single
  seed-derived S3 key owns them all. In `external` S3 mode the operator pre-creates the Drive
  bucket alongside the Docs one, exactly as before.
- **Traefik media glue, sibling chart.** Drive's authenticated media serving is the Docs
  pattern with two cosmetic differences: the media-auth endpoint is `/api/v1.0/items/`
  (Drive calls them *items*, not *documents*) and the rewrite targets the Drive bucket. A
  `drive-ingress` chart carries those two Middleware CRs, mirroring `docs-ingress`. Drive's
  upstream chart already routes `/api` + `/external_api` to the backend on the main ingress,
  so no extra API ingress is needed.
- **No realtime collaboration.** Drive is a file manager, not a collaborative editor, so it
  ships **no y-provider** — its values are the Docs wiring minus the collaboration server and
  its websocket/api ingresses.
- **Individually enable-able.** Each app is gated on its own `apps.<name>.enabled` flag
  (`OWNSUITE_APP_DOCS` / `OWNSUITE_APP_DRIVE`). Both are **off by default** like every other app
  ([ADR-035](#adr-035-every-app-off-by-default-opt-in-install)); the installer offers them as the
  recommended first pair and the Docs+Drive DoD enables them explicitly.

**Consequences.** Drive comes up over HTTPS with real SSO and per-app isolated state, proven
at the API level by the same kind of token→create→read-back e2e as Docs (the DoD). The
seam now hosts N apps without forking: a future app is another `keycloak.clients` entry, a
bucket in the list, a database, and a values file. **Deferred:** the media-**preview**
(thumbnail) ingress — a visual nicety whose upstream rewrite path needs validating against our
Traefik setup, not part of the DoD; it is left off with a `ponytail:` marker and enabled once
proven. External-S3 media keeps the same pre-existing limitation as Docs (the media upstream
points at the in-cluster Garage), out of scope here.

---

## ADR-023 — User provisioning: `suite user`, admin REST over the tunnel, JIT

**Context.** The definition of done is `suite user add firstname@assoc.org` → that person
immediately has Docs **and** Drive. ADR-005 already decided **one Keycloak identity, JIT into
every app**, and ADR-018 built the `suite` CLI (pure standard library) that prefigured this
verb. What was left open: *where* user provisioning runs, *how* it reaches Keycloak, and *how
the admin authenticates* — without exposing the admin API or storing a second secret.

**Decision.** Extend the existing `suite` package with `suite user add|disable|passwd <email>`:

- **JIT only — no per-app calls.** `add` creates **one** Keycloak user (username = email,
  `emailVerified`, enabled) and sets an initial password. Because every app authenticates
  through the same realm and provisions its local account from the token on first login
  ([ADR-005](#adr-005-shared-keycloak-jit-provisioning)), that single create grants access to
  **all enabled apps** — the CLI never touches Docs/Drive/etc. directly, so a newly added app
  needs no change here. `disable` deactivates the user (revoking access everywhere at once);
  `passwd` resets the password. Generated passwords are **temporary** by default (forced reset
  at first login) and shown once.
- **Admin REST over the in-cluster service, through the tunnel.** The CLI talks the Keycloak
  **admin REST API** (stdlib `urllib`, no HTTP-client dependency) to the in-cluster
  `keycloak-keycloakx-http` service, reached over the existing SSH tunnel
  ([ADR-014](#adr-014-operator-control-plane-local-workstation-ssh-tunnel)) plus a short-lived
  `kubectl port-forward`. Admin traffic therefore **stays private** — it never crosses the
  public `auth.{domain}` endpoint — consistent with ADR-014 (the API is never exposed) and
  ADR-020 (the upsert Job also talks to the in-cluster service).
- **Admin password derived from the seed, not read from the cluster.** The admin credential is
  re-derived locally from `$OWNSUITE_SECRET_SEED` with the same helper id (`keycloak-admin`)
  the platform used ([ADR-012](#adr-012-secrets-derived-from-a-single-secretseed-via-helm-templating)),
  so the CLI needs only the seed the operator already guards — no new secret, no `kubectl get
  secret`.
- **HTTP transport is injectable.** The `KeycloakAdmin` client takes its transport as a
  parameter, so the create/disable/reset logic is unit-tested against an in-memory fake admin
  API (no live Keycloak), matching the harness's existing fake-the-boundary style
  ([ADR-010](#adr-010-testing-ci-strategy-a-layered-evolving-harness)). The tunnel/port-forward
  glue is thin orchestration, exercised by the k3d e2e instead.

**Why not kcadm-exec or the public admin API.** `kubectl exec … kcadm.sh` (as the ADR-020 Job
does in-cluster) would couple the CLI to pod internals and a shell session file, and is awkward
to unit-test; the public `auth.{domain}/admin` API would expose admin operations to the
internet. Admin REST to the in-cluster service keeps clean idempotent semantics *and* a private
surface.

**Consequences.** A non-profit admin provisions people with one command and no Kubernetes
knowledge; the verb is app-count-agnostic by construction (JIT). The same path is what the e2e
drives to prove the DoD (create a user via the CLI → it reaches Docs **and** Drive). `suite
upgrade` / `suite restore` remain later verbs (ADR-007). Residual: the CLI assumes the realm's
default (no password policy); a stricter policy would need the generated password to conform.

---

## ADR-024 — Grist integration: local chart, public-issuer OIDC, PVC storage, off by default

> **Two "honest limits" below have since been closed.** The documents PVC **is** now backed up
> off-site (the reusable volume copy of [ADR-032](#adr-032-standardised-reusable-off-site-pvc-backup),
> built on the N-bucket object copy of [ADR-030](#adr-030-n-bucket-off-site-object-backup)), and
> Grist **is** now booted in CI on its own cluster
> ([ADR-029](#adr-029-per-app-nightly-e2e-one-app-per-cluster)). The local chart, public-issuer
> OIDC and off-by-default decisions still hold.

**Context.** The suite broadens beyond the DoD apps. **Grist** (getgrist — spreadsheets
that behave like a database) is the next one. Unlike Drive
([ADR-022](#adr-022-drive-integration-reuse-the-docs-seam-per-app-buckets)), Grist is **not** a
`suitenumerique`/impress sibling: it is a single-container Node app, it ships **no official Helm
chart**, and its OIDC and storage models differ from the Django apps. So the question ADR-022
answered ("what must the Docs seam grow") does not apply — Grist needs its own small chart and a
fresh look at three couplings: how it talks OIDC to our Keycloak, where its documents live, and
whether it is safe to ship enabled. The design was scoped against three facts discovered while
wiring it, which overrode an earlier sketch (internal-discovery + S3 doc storage):

1. **Grist does OIDC by single-issuer discovery only.** It takes one `GRIST_OIDC_IDP_ISSUER`
   and discovers every endpoint from that issuer's `/.well-known/openid-configuration`. It has
   **no** per-endpoint override, so the external/internal split Docs/Drive rely on
   ([ADR-016](#adr-016-docs-impress-integration-one-namespace-traefik-ingress-oidc-split)) is not
   expressible for Grist.
2. **The off-site object backup copies a single bucket.** `object-backup`
   ([ADR-017](#adr-017-backups-tested-restore-barman-cloud-plugin-rclone-off-site-by-design))
   syncs only the Docs media bucket today, so putting Grist documents in a *new* S3 bucket would
   **not** make them off-site-backed without first reworking the restore machinery — defeating the
   one reason ("close the backup gap") to prefer S3 over a volume.
3. **Grist is not part of the DoD** (Docs + Drive), and the constrained CI runner is
   already near its ceiling under the existing stack (the restore step had to shed Drive to stay
   within the node's memory — see `run-e2e.sh`).

**Decision.** Add Grist as a Helmfile release backed by a **small local chart**
(`helmfile/charts/grist`), reusing the shared seams, with these specific choices:

- **Local chart, not Bitnami, not a fork.** One `Deployment` (single replica,
  `strategy: Recreate` so the read-write-once volume is never double-mounted across a rollout),
  one `Service`, one `PersistentVolumeClaim`, one Traefik `Ingress`. The chart renders standalone
  (`helm lint helmfile/charts/*`) like the Garage chart; the pinned image tag (`gristlabs/grist`,
  versions.yaml) is injected by Helmfile.
- **OIDC via the public issuer (discovery), no Keycloak change.** `GRIST_OIDC_IDP_ISSUER` is the
  **public** realm URL `https://auth.{domain}/realms/{realm}`; the browser and the Grist backend
  both reach Keycloak there. In production the backend hairpins to `auth.{domain}` with the real
  Let's Encrypt certificate (standard for an OIDC client that happens to run in-cluster), so no
  TLS-skip or CA wiring is needed. This is the documented Grist↔Keycloak path. **Rejected:**
  pointing Grist at the in-cluster Keycloak service and enabling
  `KC_HOSTNAME_BACKCHANNEL_DYNAMIC` on the *shared* Keycloak — it would make the discovery
  document's `issuer` (still the public host) disagree with the URL Grist discovered against,
  risking an openid-client issuer-mismatch, and it perturbs the Keycloak that Docs/Drive depend on
  for no benefit Grist needs. The `grist` OIDC client is one more `keycloak.clients` entry; the
  existing realm-import + upsert-Job templates already emit `redirectUris: https://grist.{domain}/*`
  (covering Grist's `/oauth2/callback`) and the `profile`+`email` scopes Grist maps to its user —
  so no client-template change ([ADR-020](#adr-020-keycloak-realm-convergence-idempotent-oidc-client-upsert)).
- **Storage: a PVC for documents, CNPG for the home DB.** Grist keeps its document SQLite files on
  its `/persist` volume (a `PersistentVolumeClaim`) and its home database (orgs, users, ACLs) in a
  dedicated CNPG `grist` database via `TYPEORM_*`. **No S3, no Redis** — those exist in Grist for
  multi-worker, horizontally-scaled deployments, which a single node is not, and (per Context #2)
  S3 would not even buy off-site backup yet. The session secret and OIDC client secret are
  seed-derived ([ADR-012](#adr-012-secrets-derived-from-a-single-secretseed-via-helm-templating))
  in a `grist-secrets` Secret; the home-DB password reuses the per-app `grist-db` Secret.
- **Formula sandbox: unsandboxed by default, overridable.** Grist runs document formulas in a
  Python sandbox; `gvisor` (the image default) needs node capabilities that stock K3s/containerd
  does not reliably grant unprivileged, which would block boot. OwnSuite is a **single trusted
  organisation** — only its own members author documents — so `GRIST_SANDBOX_FLAVOR=unsandboxed`
  is an acceptable, boot-reliable default, surfaced as `OWNSUITE_GRIST_SANDBOX` for anyone who has
  set their node up for gvisor.
- **Off by default, fully gated.** Every Grist piece (release, OIDC client, `grist` database,
  secrets) is gated on `apps.grist.enabled`, which defaults **false** (`OWNSUITE_APP_GRIST`).
  Reasons: it is outside the hard DoD, it is not yet booted in the constrained CI e2e (Context #3),
  and enabling is a single flag. Because it is gated off, the e2e renders and deploys **identically**
  to before; the chart is validated cheaply by `helm template` + kubeconform on every change.

**Consequences.** A non-profit gets Grist over HTTPS with real SSO by flipping one flag, reusing
Keycloak + CNPG with no new infrastructure and no change to the apps already in the DoD. **Honest
limits, each with an upgrade path:** (a) the documents PVC is **not** off-site-backed — the same
pre-existing gap as Drive's bucket (Context #2); closing it means teaching `object-backup` to copy
N buckets / a volume, deferred until Grist graduates from off-by-default. (b) `unsandboxed`
formulas trust the document authors (true for one org); switch to `gvisor` on a suitably-configured
node otherwise. (c) Grist is **template/lint-validated, not yet CI-booted**; a targeted boot check
(enable Grist on a beefier/nightly runner and assert a Keycloak user reaches it) is the natural next
step before it becomes a default app. The public-issuer OIDC choice assumes the in-cluster backend
can reach `auth.{domain}` (DNS + hairpin), which holds on a normal single-server install.

---

## ADR-025 — Projects integration: local chart, public-issuer OIDC, PVC storage, off by default

> **Superseded in part by [ADR-031](#adr-031-projects-uploads-on-s3-eliminating-the-pvc).** The
> local chart, public-issuer OIDC and off-by-default stance still hold; Projects' uploads now live
> on **S3** (its own bucket on the shared seam), not the `projects-data` PVC — so the PVC and its
> not-off-site-backed limitation no longer apply. The "not yet CI-booted" limit below is also
> closed: Projects is now booted in CI on its own cluster
> ([ADR-029](#adr-029-per-app-nightly-e2e-one-app-per-cluster)).

**Context.** The suite broadens beyond the DoD apps, and **Projects**
(`suitenumerique/projects` — kanban boards / task management, a Sails.js fork of Planka) is the
last broadening candidate after Drive
([ADR-022](#adr-022-drive-integration-reuse-the-docs-seam-per-app-buckets)) and Grist
([ADR-024](#adr-024-grist-integration-local-chart-public-issuer-oidc-pvc-storage-off-by-default)).
It was first scoped as *defer* (was the seam ready for a second never-CI-booted app?); that call
was **reversed** — Projects is **built**, on the same terms as Grist. Like Grist it is **not** a
`suitenumerique`/impress app: a single-container Node app with **no official Helm chart** (a Docker
image `lasuite/projects` + a docker-compose), so it needs its own small chart. The integration was
scoped against the upstream `server/.env.sample` + `Dockerfile`:

- **Single container, port 1337**, Node 22, serving its built React client from `public/`. **No
  Redis.** Files (avatars, project backgrounds, attachments) are written to three local paths
  (Planka heritage); the database is PostgreSQL via a single `DATABASE_URL`.
- **OIDC by single-issuer discovery** (openid-client), exactly like Grist — one `OIDC_ISSUER`, no
  per-endpoint split.

**Decision.** Add Projects as a Helmfile release backed by a **small local chart**
(`helmfile/charts/projects`), reusing the shared seams and mirroring the Grist choices (ADR-024):

- **Local chart.** One `Deployment` (single replica, `strategy: Recreate`), one `Service`, one
  `Ingress`, and one `PersistentVolumeClaim` whose three subPaths back the upload directories
  (`/app/public/user-avatars`, `/app/public/project-background-images`, `/app/private/attachments`).
  The pinned image (`lasuite/projects`, versions.yaml) is injected by Helmfile.
- **OIDC via the public issuer, no Keycloak change.** `OIDC_ISSUER` is the public realm URL
  `https://auth.{domain}/realms/{realm}`; the backend hairpins with the real cert in production.
  The `projects` OIDC client is one more `keycloak.clients` entry — the existing templates already
  emit `redirectUris: https://projects.{domain}/*` (covering the callback) and the `profile`+`email`
  scopes. **One wrinkle vs Grist:** our realm client signs the **userinfo** response RS256
  (`user.info.response.signature.alg`) and Projects reads claims from userinfo
  (`OIDC_CLAIMS_SOURCE=userinfo`), so `OIDC_USERINFO_SIGNED_RESPONSE_ALG=RS256` is set or
  openid-client cannot parse the signed response.
- **`DATABASE_URL` built in one place.** Projects wants a single connection string, not separate
  vars, so the URL (embedding the seed-derived `projects-db` password) is assembled in
  `platform-configuration` (`projects-secrets`) from the CNPG `-rw` host — keeping the password out
  of the rendered values. `SECRET_KEY` and the OIDC client secret are seed-derived too
  ([ADR-012](#adr-012-secrets-derived-from-a-single-secretseed-via-helm-templating)).
- **PVC for uploads, no S3.** Same reasoning as Grist: a single node doesn't need S3, and the
  off-site copy is single-bucket today, so S3 wouldn't close the backup gap.
- **Off by default, fully gated.** Every Projects piece (release, OIDC client, `projects`
  database, secrets) is gated on `apps.projects.enabled`, default **false**
  (`OWNSUITE_APP_PROJECTS`): outside the hard DoD and not yet CI-booted. Gated off, the e2e
  renders/deploys identically; validated by `helm lint` + kubeconform.

**Consequences.** A non-profit gets Projects over HTTPS with real SSO by flipping one flag,
reusing Keycloak + CNPG with no new infrastructure. **Honest limits, with upgrade paths:** the
uploads PVC is **not** off-site-backed (the same gap as Grist's PVC / Drive's bucket), and Projects
is **template/lint-validated, not yet CI-booted** — its OIDC env was wired from the upstream sample
+ our RS256 Keycloak, so the first real deployment should confirm login end to end. People remains
the only documented-and-deferred item; the "add an app" seam now hosts Docs, Drive, Grist and
Projects without forking.

---

## ADR-026 — Mailbox integration: messages, Django OIDC split, reuse the seam, OpenSearch deferred

> **The "not yet CI-booted" limit below is closed.** The hermetic mail loopback this ADR
> describes as the intended boot check now runs in CI on the mailbox's own cluster
> ([ADR-029](#adr-029-per-app-nightly-e2e-one-app-per-cluster)). OpenSearch and the off-CI
> external-deliverability check still stand as described.

**Context.** This ADR implements the mailbox decided in
[ADR-021](#adr-021-mailbox-suitenumeriquemessages-outbound-via-eu-relay): **suitenumerique/messages**,
La Suite's own mail app, federated to the same Keycloak. Where Grist
([ADR-024](#adr-024-grist-integration-local-chart-public-issuer-oidc-pvc-storage-off-by-default)) and
Projects ([ADR-025](#adr-025-projects-integration-local-chart-public-issuer-oidc-pvc-storage-off-by-default))
asked *"how to bolt on a foreign single-container app"*, messages is the opposite: a
`suitenumerique` Django sibling of Docs, so the question is again ADR-022's — *what the existing seam
must grow* — plus the genuinely new mail machinery (port 25, DKIM/SPF/DMARC), which
[ADR-027](#adr-027-non-http-ingress-inbound-smtp-on-port-25-via-k3s-servicelb) covers. The design was scoped against the verified-current upstream
(v0.8.0, June 2026: `compose.yaml`, `docs/env.md`, the `core` management commands), **not** memory —
an earlier scout pass wrongly claimed messages publishes no images and had no recent release.

**Decision.** Add messages as a Helmfile release backed by a **small local chart**
(`helmfile/charts/messages`) — upstream ships images (`ghcr.io/suitenumerique/messages-{backend,frontend,mta-in,mta-out}`, semver-tagged, pinned `0.8.0`) but **no** Helm chart — reusing the shared seams:

- **OIDC by the external/internal split, like Docs.** messages is `mozilla-django-oidc`, so it takes
  the per-endpoint `OIDC_OP_{AUTHORIZATION,TOKEN,USER,JWKS}_ENDPOINT` + `OIDC_RP_CLIENT_{ID,SECRET}`
  contract ([ADR-016](#adr-016-docs-impress-integration-one-namespace-traefik-ingress-oidc-split)),
  **not** Grist/Projects single-issuer discovery: browser-facing endpoints at the public
  `auth.{domain}`, token/userinfo/jwks hairpinned to the in-cluster Keycloak service. The `messages`
  OIDC client is one more `keycloak.clients` entry; the existing realm-import + idempotent upsert Job
  ([ADR-020](#adr-020-keycloak-realm-convergence-idempotent-oidc-client-upsert)) need no template change.
- **Reuse the shared infrastructure, per-app instances.** A dedicated CNPG `messages` database; the
  shared **Valkey** with dedicated DB numbers (**4** cache / **5** Celery broker — Docs uses 0/1,
  Drive 2/3, so the queues never cross-consume, the one real co-tenancy trap, ADR-022); a per-app
  **S3 bucket** for mail blobs/attachments on the pluggable seam (mirror ADR-022 — messages stores
  blobs in object storage, `create_bucket`/`verify_blobs`). The Django `SECRET_KEY`, the OIDC client
  secret and the internal `MDA_API_SECRET` (MTA↔MDA) are seed-derived
  ([ADR-012](#adr-012-secrets-derived-from-a-single-secretseed-via-helm-templating)); the relay
  credentials and the DKIM private key are **external overrides**, not derived (ADR-021 refinement).
- **OpenSearch deferred.** Verified optional upstream (an unset `OPENSEARCH_URL` only turns off
  full-text search); omitted from v1 to protect the single-VPS RAM budget, behind a future flag. This
  is the one ADR-021 component we drop — it was the heaviest.
- **rspamd and socks-proxy skipped.** rspamd (inbound spam filter) is not on the path to the DoD
  ("outbound reaches the inbox, not spam" is an SPF/DKIM/DMARC-via-relay property); mta-in delivers to
  the MDA without it. socks-proxy only serves `MTA_OUT_MODE=direct`, and we relay. Both carry a
  `ponytail:` marker and a one-line re-enable path.
- **Outbound relayed, throttled.** `MTA_OUT_MODE=relay`, `MTA_OUT_SMTP_TLS_SECURITY_LEVEL=secure` to
  the EU relay (Infomaniak `mail.infomaniak.com:587`); `THROTTLE_{MAILBOX,MAILDOMAIN}_OUTBOUND_EXTERNAL_RECIPIENTS`
  set below the relay's 1440 msg/24h ceiling so it fails gracefully in-app.
- **Mailbox provisioning needs no `suite user add` change.** A maildomain with `oidc_autojoin=True`
  auto-creates a user's mailbox on first OIDC login — exactly the JIT model the CLI already relies on
  (ADR-023). The one new piece is a **one-time maildomain seed Job** (mirrors `keycloak-config`) that
  creates the domain, enables autojoin and registers the supplied DKIM key.
- **Off by default, fully gated.** Every piece (release, OIDC client, `messages` DB, bucket, secrets,
  seed Job) is gated on `apps.messages.enabled`, default **false** (`OWNSUITE_APP_MESSAGES`): it is the
  optional, advanced add-on. Gated off, the e2e renders/deploys identically; the chart is validated by
  `helm lint` + kubeconform on every change. Like Grist and Projects
  ([ADR-024](#adr-024-grist-integration-local-chart-public-issuer-oidc-pvc-storage-off-by-default),
  [ADR-025](#adr-025-projects-integration-local-chart-public-issuer-oidc-pvc-storage-off-by-default)),
  it is **not booted in the constrained k3d e2e** — heavier still (five pods), it would push the runner,
  already shedding Drive during the restore step, over its memory ceiling. The hermetic loopback below
  is the natural next step on a beefier/nightly runner.

**Consequences.** A non-profit gets an integrated webmail over HTTPS with real SSO by enabling one
flag and supplying a relay account — reusing Keycloak, CNPG, Valkey and the S3 seam with **one** new
heavy dependency removed (OpenSearch). **Honest limits, each with an upgrade path:** no full-text mail
search until OpenSearch is re-enabled; **no IMAP/POP3** by design (ADR-021); the mail bucket shares
Drive/Grist's not-yet-off-site backup gap; and messages is **template/lint-validated, not yet CI-booted**
(runner footprint). The intended boot check is the **hermetic loopback** — pods converge, webmail 200s,
OIDC login works, and a message delivered between two local mailboxes reads back via the API (the Docs
create-and-read-back analog) — run on a beefier/nightly runner. **Real external deliverability**
(SPF/DKIM/DMARC-aligned, inbox-not-spam) is an **off-CI human check** on a real domain + relay account,
exactly as real ACME issuance is validated off-CI.

---

## ADR-027 — Non-HTTP ingress: inbound SMTP on port 25 via K3s ServiceLB

**Context.** Every public port in the stack so far is HTTP/S, carried by Traefik with cert-manager
TLS. The mailbox (ADR-026) needs the stack's **first non-HTTP public port**: its Postfix MTA-in must
receive mail from the internet on **port 25** (domain `MX` → port 25). Traefik's web/websecure
entrypoints don't carry raw SMTP, so port 25 needs a different ingress path on single-node K3s.

**Decision.** Expose mta-in with a Kubernetes **`Service` of `type: LoadBalancer`**, which K3s'
bundled **ServiceLB (klipper-lb)** — already in the cluster and already fronting Traefik — realizes by
binding host port **25** and routing it to the mta-in pod. No new controller, no MetalLB, no Traefik
TCP entrypoint to configure.

- **Firewall.** The Ansible `security` role must allow **inbound TCP 25** (it is closed by default);
  this is the only host-firewall change the mailbox needs. Added there, gated on the mailbox being
  enabled.
- **Outbound 25 stays blocked — fine.** Most VPS providers block *outbound* 25; we never send directly
  (ADR-021 relays out via 587), so only *inbound* 25 matters. The installer documents confirming the
  provider permits inbound 25 as a pre-flight check.
- **rDNS / PTR is a manual host step.** A correct reverse-DNS record for the server IP is set at the
  provider/host level and **cannot** be set in-cluster; the install flow documents it as a manual step
  alongside the MX/SPF/DKIM/DMARC records (the relay carries most reputation, but PTR still matters).

**Consequences.** The mailbox receives mail with no addition to the cluster's networking stack —
ServiceLB was already there. The seam now distinguishes HTTP apps (Traefik + cert-manager, the norm)
from the single raw-TCP exception (port 25), documented so it isn't mistaken for a Traefik route.
**Trade-off:** ServiceLB is single-node-simple and binds the host port directly; a multi-node or
HA mail setup would need a real LB / MetalLB — out of scope for the single-server target.

## ADR-028 — Resource requests/limits and probes for every workload

**Context.** Production hardening for a non-expert operator means two things the cluster can act on
without a human: a workload must declare what it costs (so the scheduler protects the node and the
operator can size a VPS), and it must say when it is healthy (so a wedged pod recovers and a rollout
waits for readiness). Most workloads already had requests/probes, but with gaps: the messages chart
shipped one shared resource block for five very different components, the single-container apps
(Grist, Projects, messages) had a *readiness* probe only — no liveness, and the boot delay was
faked with a large `initialDelaySeconds` — and the PostgreSQL `Cluster` and Valkey ran with no
declared resources at all.

**Decision.** Give every workload OwnSuite directly defines sane requests/limits and a
startup/readiness/liveness probe set.

- **Memory limit, no CPU limit.** Each workload *requests* CPU + memory (its guaranteed floor) and
  *limits* memory only. A CPU limit throttles queries, migrations and first-boot work on a shared
  single node; a memory limit stops one app OOM-ing its neighbours. This is the convention every
  chart now follows.
- **startupProbe gates the boot; liveness/readiness run fast after.** A `startupProbe` with a
  generous `failureThreshold` (~5 min budget) absorbs the first-boot DB migration, so readiness and
  liveness no longer need a long `initialDelaySeconds` hack. Once startup passes, **readiness** gates
  the Service/rollout and **liveness** restarts a pod that has wedged (a deadlock readiness alone
  would only pull from the Service, never recover). The probe action (httpGet/tcpSocket) is defined
  once per chart and reused for all three.
- **Per-component sizing where components differ.** The messages chart sizes each component
  separately — the Django backend/worker are heavier than the lightweight Postfix MTAs — instead of
  one shared block.
- **PostgreSQL and Valkey get explicit resources.** The CNPG `Cluster` and the Valkey release now
  declare requests + a memory limit like everything else.

A few **upstream** operator/sidecar pods (cert-manager, the CNPG operator, Drive's Celery split)
keep their chart defaults rather than being force-overridden — fragile to track per chart version,
and small/stable enough to fall under the recommended-RAM headroom. The
[server sizing guide](../operate/sizing.md) accounts for them and is derived by summing these
declarations.

**Consequences.** The scheduler can protect the node, rollouts wait for genuine readiness, wedged
pods self-heal, and a volunteer can read one [sizing guide](../operate/sizing.md) to buy the right
VPS. **Trade-off:** the limits are deliberately generous ceilings (headroom for migrations and
upgrade overlap), so steady-state usage sits well below them — the recommended-RAM figure is a safe
buy, not a tight one.

---

## ADR-029 — Per-app nightly e2e: one app per cluster

**Context.** [ADR-010](#adr-010-testing-ci-strategy-a-layered-evolving-harness) runs the combined
end-to-end check (`helmfile-e2e.yml`) on a single k3d cluster: the shared infrastructure plus the
**Docs + Drive** core, then a full backup → restore cycle. The optional apps (Grist, Projects,
messages) are deliberately **left out** of that run — bringing them up alongside the core, the
operators, Keycloak and a CNPG recovery would push the GitHub runner past its memory ceiling.
messages alone is five pods. So the optional apps were lint/template-validated but never actually
booted in CI, and the messages mail loopback stayed an off-CI manual check. That is the last
coverage gap before any of them could graduate to on-by-default.

**Decision.** A **dedicated workflow** (`apps-e2e.yml`) with a **matrix, one app per
job, each on its own fresh k3d cluster**. Because each job holds only the platform plus one app,
none competes for RAM. Per job it brings the app up, asserts it converges, that its UI is reachable
over HTTPS through Traefik, and an app-appropriate read-back:

- **Grist** — the health endpoint answers and an unauthenticated visit bounces to the SSO login page.
- **Projects** — the UI is reachable over HTTPS (its SSO redirect happens client-side, so the bounce
  target is not asserted; the browser flow stays a human check on first deployment).
- **messages** — the local mail-delivery loopback: a message injected over SMTP to the inbound MTA
  is delivered (MTA → delivery agent → mailbox) and reads back via the API, with no external relay,
  so nothing leaves the cluster. This finally exercises the inbound mail path in CI.
- **Docs** — an SSO user (seeded realm user, direct-access grant) creates a document through the API
  and reads it back, proving OIDC client wiring + DB persistence.
- **Drive** — a user created through the `suite user` CLI is just-in-time provisioned on its first
  authenticated call, proven by `/users/me/` echoing its email.

**Update (Docs/Drive folded in).** Docs and Drive originally kept their boot DoD in the full suite
([ADR-010](#adr-010-testing-ci-strategy-a-layered-evolving-harness)) because that suite already booted
them as the restore survivor. Once apps went off-by-default ([ADR-035](#adr-035-every-app-off-by-default-opt-in-install))
they are optional like the rest, so they now get the **same fast per-app PR gate** here — making this
workflow the single source of **all five** apps' boot DoD. The full suite (`run-e2e.sh`) keeps Docs
enabled only as the object-bucket vehicle for the object-copy restore check (a fixture, not an app
DoD) and asserts no application; its restore survivor is decoupled accordingly (see
[ADR-006](#adr-006-backups-and-tested-restore)/[ADR-017](#adr-017-backups-tested-restore-barman-cloud-plugin-rclone-off-site-by-design)).

The fail-fast watchdog, the cert wait, the failure diagnostics and the PVC backup/restore round-trip
are **factored into a shared `helmfile/tests/lib.sh`** sourced by `run-e2e.sh`, `run-app-e2e.sh` and
`run-pvc-backup-e2e.sh`, so the harnesses share one implementation. Locally: `make test-app
APP=<grist|projects|messages>`.

The workflow is **split like `helmfile-e2e.yml`** (the same cost-aware pattern as the
[ADR-032 PVC backup gate](#adr-032-standardised-reusable-off-site-pvc-backup)): the full
five-app matrix runs nightly and on demand, but a **PR that touches an app's chart or
values boots only *that* app** as a fast, fail-fast gate, so a change to one app gets a real boot
signal in minutes — not just lint/template — without waiting on (or paying for) the other four. A
change to the shared harness (`lib.sh`, `run-app-e2e.sh`, `test_apps.py`) or the workflow itself
fans out to all five, since it can affect any of them. Docs and Drive have no `charts/<app>/`
directory (they are upstream charts + a local `*-ingress` chart + a values file), so the `detect`
mapping watches `charts/docs-ingress/**` + `values/docs.yaml.gotmpl` (and the drive equivalents).

GitHub `paths:` filters gate a *workflow*, not a matrix entry — they cannot say "this app changed,
run only its job". Two ways to bridge that, and we rejected both: **(a) one workflow file per app**,
each with its own `paths:` filter, duplicates the tool-install boilerplate five ways and drifts;
**(b) a single matrix that boots all five on any app change** wastes four clusters' runner time
whenever one app changes. Instead a tiny `detect` job diffs the PR against its base and emits a JSON
matrix of only the changed app(s) — one file, no duplication, no wasted clusters. The cost is one
extra ~30 s job and a small amount of shell; cheap next to a 15–20 min app boot.

**Consequences.** Every shipped app is now actually booted in CI, the messages mail loopback is
automated rather than manual, and the optional apps have the boot evidence they need to graduate
later. A PR that changes one app now gets that app's boot signal pre-merge at the cost of a single
cluster; the full five-app sweep stays nightly. Real external mail deliverability
([ADR-021](#adr-021-mailbox-suitenumeriquemessages-outbound-via-eu-relay)) remains the one check a
hermetic cluster cannot stand in for: it needs a real domain, relay and inbox.

---

## ADR-030 — N-bucket off-site object backup

**Context.** The off-site object copy ([ADR-006](#adr-006-backups-and-tested-restore),
[ADR-017](#adr-017-backups-tested-restore-barman-cloud-plugin-rclone-off-site-by-design)) copied a
**single** bucket — Docs' `docs-media-storage`. As the suite grew per-app buckets (Drive, Mailbox,
and now Projects on [ADR-031](#adr-031-projects-uploads-on-s3-eliminating-the-pvc)), every bucket
but Docs' was an unbacked gap: enabling Drive, Projects or the Mailbox meant media that no off-site
copy covered.

**Decision.** Generalise the `object-backup` chart to copy a **list of buckets** instead of one. The
Helmfile values drive the list from the **enabled apps' buckets** (`docs`/`drive`/`messages`/
`projects`), mirroring the Garage `buckets:` list so backup coverage always tracks what is deployed.
The sync script loops the list, copying each `primary:<bucket>` to its **own sub-path** under the
existing rclone `crypt` overlay (`offsitecrypt:<bucket>`), so the buckets never collide and the
restore path stays symmetric (each restored from its own sub-path).

- **Invariants preserved.** The off-site store is still a **different** account/Garage than the
  primary (the off-site-≠-primary rule), and every copy is still **client-side encrypted** by the
  same `crypt` remote — only the number of buckets changed.
- **No new secret, no new image.** The shared seed-derived S3 key still owns every bucket, and the
  already-pinned rclone image runs the loop.

**Consequences.** Turning on any media-storing app now backs up its bucket with no extra config — the
single-bucket gap is closed. **Trade-off:** the copy runs the buckets sequentially in one CronJob
pass (simple, and fine at single-VPS data volumes); a future parallel/per-bucket schedule is a small
change if data ever outgrows it.

---

## ADR-031 — Projects uploads on S3, eliminating the PVC

**Context.** Projects ([ADR-025](#adr-025-projects-integration-local-chart-public-issuer-oidc-pvc-storage-off-by-default))
stored its uploads (avatars, project backgrounds, attachments) on the `projects-data` PVC, which
forced `strategy: Recreate` (a read-write-once volume must never be double-mounted) and — like
Grist's and Drive's earlier gaps — was **not** off-site-backed. Upstream `suitenumerique/projects`
ships an **S3 file manager** that activates when `S3_ENDPOINT`/`S3_REGION` are set (verified against
`server/.env.sample` + `api/hooks/s3`), exposing
`S3_ENDPOINT`/`S3_REGION`/`S3_ACCESS_KEY_ID`/`S3_SECRET_ACCESS_KEY`/`S3_BUCKET`/`S3_FORCE_PATH_STYLE`.

**Decision.** Switch Projects' uploads to **S3** on the shared object-storage seam, exactly as Docs,
Drive and Mailbox do, and **remove the PVC**:

- **Its own bucket** (`projects-media-storage`), provisioned by the Garage bootstrap in `garage` mode
  (or pre-created on external S3), joining the N-bucket off-site copy
  ([ADR-030](#adr-030-n-bucket-off-site-object-backup)) — so uploads are now backed up.
- **Shared credentials, mode-aware endpoint.** The S3 key/secret are the same seed-derived
  `s3-credentials` pair; the endpoint/region follow the garage-vs-external split used by the other
  apps.
- **Chart simplified.** The `projects-data` PVC, its three subPath mounts, `strategy: Recreate` and
  the storage knobs are gone; the Deployment is now a plain rolling-update single container.

**Consequences.** Projects gains off-site-backed uploads and a simpler chart, and the suite's per-app
storage is uniformly S3 (no app-specific PVC for uploads). This **supersedes the PVC part of
ADR-025**. **Trade-off:** Projects now requires the object-storage seam (Garage in `garage` mode, a
pre-created bucket on external S3) where before it needed only a volume — acceptable, since the seam
is already mandatory for the core apps.

---

## ADR-032 — Standardised reusable off-site PVC backup

**Context.** Some state lives on a **volume**, not S3: Grist keeps its documents as SQLite files in
`/persist/docs` (no upstream S3 document store), so the N-bucket object copy
([ADR-030](#adr-030-n-bucket-off-site-object-backup)) cannot cover it. Rather than bolt a one-off
backup onto Grist, the volume case deserves the same reusable treatment the object copy gives
buckets — any future PVC-backed app should get off-site backup by adding one list entry.

**Decision.** Add a small reusable **`pvc-backup`** local chart: a CronJob (and a restore Job)
**parametrised by a list of `{pvcName, subPath}`**. For each volume it mounts the PVC, and copies the
subtree to the off-site store with the **same rclone `crypt` overlay and off-site config** the object
copy uses (off-site-≠-primary, client-side encrypted), under a per-PVC sub-path. The restore Job
(rendered in restore mode, a `post-install` hook) copies the encrypted copy back into the freshly
bound PVC before the app reads it — symmetric with the object restore.

- **First consumer: Grist.** `grist-persist` (`/persist`, holding the document SQLite). The release
  is gated on backups **and** Grist enabled, and `needs` the Grist release so the PVC exists before
  the Job mounts it; on restore the documents land before any document is opened (Grist reads
  document files lazily, not on boot).
- **Reuse, not a new dependency.** The already-pinned rclone image and the existing
  `backup-s3-credentials` + crypt passphrase are reused; no new image or secret.
- **Single-node mount.** The backup CronJob mounts the PVC read-only alongside the app pod, which is
  fine on single-node K3s (same node); a multi-node setup would need a volume-snapshot seam, noted in
  the chart.

**Consequences.** Grist's documents are now backed up off-site and restored on recovery, closing the
last PVC backup gap, and the pattern is ready for any future volume-backed app by adding a list
entry. An e2e proves a seeded Grist document survives a PVC backup → wipe → restore — packaged as
an **isolated, fast harness** (`make test-pvc-backup` / `run-pvc-backup-e2e.sh`) that boots only a
single off-site `garage-backup` store and runs the shared `pvc_backup_roundtrip`
([ADR-010](#adr-010-testing-ci-strategy-a-layered-evolving-harness)), so it gates every PR in ~3 min
instead of waiting on the heavy full suite. **Trade-off:**
the backup container mounts the live volume rather than a snapshot, so a copy taken mid-write captures
a crash-consistent (not quiesced) state — acceptable for SQLite documents on a single VPS; snapshotting
is the upgrade path if needed.

---

## ADR-033 — `suite status` for monitoring (CLI, no in-cluster workload)

**Context.** A non-expert operator needs a quick, trustworthy answer to "is my OwnSuite
healthy?" — node, database, certificates, off-site backups, and each enabled app. The
single-server target makes a full monitoring stack (Prometheus/Grafana/Alertmanager) a poor
trade: it costs RAM and operational surface on a node sized for the apps themselves, and it is
one more thing the volunteer must learn, secure, and keep alive.

**Decision.** Add a read-only `suite status` subcommand that reads live state over the existing
SSH tunnel (ADR-014) with `kubectl get -o json` and prints a readable, line-per-check summary.
It reuses the CLI's tunnel/kubectl plumbing — no new server-side workload, no extra Helm
release, no scrape endpoints. The k8s/CNPG/cert/backup JSON is parsed by small pure functions
that are unit-tested against fixtures, so the parsing has coverage without a live cluster. Only
the apps switched on (via `OWNSUITE_APP_*`, same precedence the Helmfile uses) are reported.

**Consequences.** The operator gets an at-a-glance health check with nothing extra running on
the server, on demand, over the private tunnel. **Trade-off:** it is a point-in-time snapshot,
not continuous alerting — there is no history and nothing pages you when something breaks at
3am. For the single-server, volunteer-run target that is the right altitude; a deployment that
outgrows it can layer a real monitoring stack on top later.

## ADR-034 — `suite upgrade` (backup-gated snapshot → diff → apply → health → rollback)

**Context.** Version bumps land as Renovate-proposed edits to the pinned versions (ADR-007),
gated by CI. Applying them on a live server is the dangerous moment: a bad upgrade can wedge an
app or, worse, touch data with no undo. The operator needs a single safe path that makes the
right thing the easy thing — never an upgrade without a fresh restore point, and automatic
recovery when an upgrade fails its health check.

**Decision.** Add `suite upgrade`, the operationalisation of ADR-007's "explicit, reviewable,
CI-gated bump" into a safe apply:

1. **Refuse if backups are disabled.** A destructive operation requires a recovery net; with
   `OWNSUITE_BACKUP_ENABLED` not true, the command stops before doing anything (ADR-006).
2. **Pre-upgrade snapshot.** It reuses the `make backup` machinery (CNPG base backup + off-site
   object copy) — the backup path is not reinvented.
3. **Show the diff and confirm.** `helmfile diff` is printed and confirmed interactively,
   skippable with `--yes` like `suite install`'s non-interactive mode.
4. **Apply** with `helmfile apply`.
5. **Health-check** by reusing `suite.verify` against single sign-on and each enabled app's
   public HTTPS host.
6. **Roll back on failure.** Each host that fails its health check has its Helm release rolled
   back to the previous revision; the command then exits with an error naming what failed.

The flow's branching — the backup gate and the rollback-on-health-failure path in particular —
is unit-tested with mocked subprocess and HTTPS calls, no live cluster.

**Consequences.** Upgrades become a one-command, low-anxiety operation: there is always a fresh
snapshot, the change is shown before it applies, and a regression self-heals back to the working
version. **Trade-off:** a rollback restores the previous *version*, not the data — the
pre-upgrade snapshot is the only undo for data changes, which is exactly why backups are a hard
precondition. The health check is HTTPS-reachability of each app, not a deep functional test;
deeper assertions live in the nightly e2e (ADR-010), not in the hot upgrade path.

---

## ADR-035 — Every app off by default; opt-in install

**Context.** Until now Docs and Drive defaulted **on** (the core DoD wants both immediately),
while Grist, Projects and the mailbox defaulted **off**
([ADR-024](#adr-024-grist-integration-local-chart-public-issuer-oidc-pvc-storage-off-by-default),
[ADR-025](#adr-025-projects-integration-local-chart-public-issuer-oidc-pvc-storage-off-by-default),
[ADR-026](#adr-026-mailbox-integration-messages-django-oidc-split-reuse-the-seam-opensearch-deferred)). That split was an accident of sequencing, not
a principle: a fresh `suite install` brought up two apps the operator might not want, on a
single-server box where every pod competes for the same RAM (ADR-029). It also made the default
footprint a moving target as more apps land.

**Decision.** **No app is enabled by default — only Keycloak and the shared platform
(cert-manager, CNPG, Valkey, Garage, backups) come up unattended.** Every app, Docs and Drive
included, is now gated the same way: `apps.<name>.enabled` defaults to `false`, flipped per app
via `OWNSUITE_APP_<NAME>=true`. The operator opts in explicitly:

- The guided installer (ADR-018) **prompts for each app** (Docs and Drive presented as the
  recommended first pair), all defaulting off.
- `suite install` now issues and HTTPS-verifies **Keycloak always, plus a cert + public host for
  each enabled app** — the same "Keycloak + enabled apps" shape `suite upgrade` already used
  ([ADR-034](#adr-034-suite-upgrade-backup-gated-snapshot-diff-apply-health-rollback)). A
  platform-only install no longer hangs waiting on a `docs-tls` that was never requested.
- `suite status` mirrors the new defaults (all off) when reporting which apps are on.

Docs+Drive remain the **recommended** core and the machine-checked DoD: the full platform e2e
(`run-e2e.sh`, ADR-010/029) enables them explicitly and still asserts the token→create→read-back
round-trip and the restore survival. The per-app boot gate (ADR-029) is unchanged — Grist,
Projects and messages each boot on their own cluster.

The always-provisioned `docs`/`drive` databases and S3 buckets are **left in place** even when the
apps are off: an empty database and an unused bucket name cost nothing, and gating them would add
surface area (the derived owner secrets, the Garage bootstrap) for no operational gain. Only the
heavier optional apps' databases (Grist/Projects/messages) stay conditionally provisioned, as before.

**Consequences.** The default install is now the smallest honest thing — SSO and the platform,
nothing presumed. Operators choose their apps up front, and the resource footprint is whatever
they switched on rather than a baked-in pair. **Trade-off:** a brand-new operator who expected
Docs out of the box must now tick it (or set `OWNSUITE_APP_DOCS=true`); the installer prompt and
the docs make that the obvious first step, so the cost is one keystroke, not a surprise.

---

## ADR-036 — `suite restore` (backup-gated, clean-cluster recovery)

**Context.** Disaster recovery already worked: `make restore` runs a Helmfile sync in restore
mode (CNPG recovery + the object/PVC restore Jobs, ADR-006/ADR-017), and the nightly e2e proves
the full backup → destroy → restore cycle (ADR-010). But the operator-facing surface stopped at
`install` / `user` / `status` / `upgrade`; restore was a bare `make` target with two sharp edges.
First, it renders nothing without `OWNSUITE_SECRET_SEED` and means nothing without a backup source,
yet failed late and opaquely when either was missing. Second — and worse — it assumes a **clean**
cluster: CNPG recovery and the restore Jobs expect no prior data, so running it over a live install
can clobber the very data it is meant to protect. ADR-018 anticipated a matching `suite restore`
verb to close this gap.

**Decision.** Add `suite restore`, the disaster-recovery counterpart of
[`suite upgrade`](#adr-034-suite-upgrade-backup-gated-snapshot-diff-apply-health-rollback) and built
on the same idioms (shared connection flags, the SSH tunnel of ADR-014, `OWNSUITE_SECRET_SEED`
required up front, reuse of `make`/`helmfile` and `suite.verify` rather than reimplementation):

1. **Require the seed.** Fail clearly if `OWNSUITE_SECRET_SEED` is not exported — Helmfile cannot
   render without it (ADR-012).
2. **Require a backup source.** Refuse unless off-site backups are enabled
   (`OWNSUITE_BACKUP_ENABLED`) and a target store is configured — restoring from nothing is
   meaningless (ADR-006).
3. **Safety gate: refuse on a non-clean cluster.** Over the tunnel it probes for prior state (an
   existing CNPG `Cluster` or bound PVCs in the `ownsuite` namespace). Because this is destructive,
   the override is an **explicit typed confirmation** ("type `restore`"), not a bare `y/N`;
   `--yes` skips it for unattended runs.
4. **Restore + verify.** It runs the restore-mode sync
   (`OWNSUITE_RESTORE=true OWNSUITE_BACKUP_ENABLED=true helmfile sync`) — exactly what `make restore`
   runs — then verifies single sign-on and each enabled app over HTTPS, surfacing what came back.

`make restore` stays the **low-level mechanism the CLI wraps**: the nightly e2e keeps driving it
directly (a clean cluster by construction, no guardrails needed). The gates and the restore-mode
env handed to Helmfile are unit-tested with mocked subprocess/HTTPS calls, no live cluster.

**Consequences.** Recovery becomes a single guarded command that fails fast on the two ways a
restore goes wrong silently (no seed, no source) and cannot quietly destroy a live install. **Safety
gate trade-off:** the clean-cluster check is a heuristic (CNPG cluster + bound PVCs), not a proof of
emptiness — a partially-provisioned cluster could slip through, and a genuinely fresh one with leftover
PVCs would prompt unnecessarily. We accept both: the typed confirmation makes the destructive override
deliberate, and `--yes` keeps automation unblocked. Like `suite upgrade`, verification is HTTPS
reachability, not a deep functional test — the nightly e2e remains the deep check.

---

## ADR-037 — One entrypoint for operators: every action is a `suite` CLI verb

**Context.** The operator surface had drifted across two tools. Setup and provisioning lived as
`make` targets (`make deps`, `make bootstrap`, `make check`), while the lifecycle lived on the
`suite` CLI (`install` / `user` / `status` / `upgrade` / `restore`, ADR-018 onward). An operator
had to know *which* tool a given action lived on, and the installer itself shelled out to
`make bootstrap` from inside Python — a CLI calling a Makefile calling Ansible. The `make` surface
also mixed two audiences: genuine CI/dev plumbing (lint, the Molecule/e2e harnesses) and
operator-facing commands, with nothing signalling which was which.

**Decision.** **Every user-facing operation is a `suite` CLI verb; `make` is CI/dev shorthand
only.** The three setup/provisioning targets become verbs in a new `suite/bootstrap.py`:

- `suite deps` — install the Python tooling + Ansible collections (pip + `ansible-galaxy`).
  `suite` is pure standard library, so this runs from a bare checkout with nothing pre-installed.
- `suite bootstrap` — provision the server via the Ansible playbook (ADR-002), the work
  `make bootstrap` used to do.
- `suite check` — the same playbook with `--check --diff`, a no-op dry-run.

`suite install` now calls `bootstrap.provision()` directly instead of shelling out to `make`, so
the installer no longer depends on a Makefile being present. The remaining `make` targets are
exactly the CI/dev set — `lint*`, `test*`, and the low-level helmfile/ssh helpers the CLI wraps
(`tunnel` / `sync` / `diff` / `destroy` / `backup`, plus `restore` as the documented low-level
mechanism behind [`suite restore`](#adr-036-suite-restore-backup-gated-clean-cluster-recovery)).
`make install` is kept as a one-line alias to the canonical `suite install`. The new verbs are
flag-free (they read the repo's requirements files and the Ansible inventory) and unit-tested with
mocked subprocess/tool-discovery calls, no pip/Ansible/server.

**Consequences.** There is one place to look for anything an operator does (`suite --help`), and the
docs lead with `python3 -m suite …` throughout. The CLI/Makefile layering inverts cleanly: Python is
the entrypoint, Ansible/helmfile/kubectl are the tools it drives, and `make` stops being part of the
operator's mental model. **Trade-off:** the headline commands grow one token longer
(`make bootstrap` → `python3 -m suite bootstrap`) until a `suite` shim is on `PATH` — now
resolved by [ADR-040](#adr-040-suite-on-path-via-a-global-pipx-install-static-shell-completion). CI is
unaffected because it already invoked `pip`/`ansible-galaxy` directly rather than through `make deps`.

---

## ADR-038 — Hosting provider: Scaleway recommended (Infomaniak alternative)

**Context.** OwnSuite provisions its infrastructure half with Terraform ([Provision](../get-started/provision.md)),
and two providers now ship. The first target was **Infomaniak** Public Cloud (OpenStack) for its
low EU/CH price, but a full end-to-end trial surfaced two structural limits: (a) its object storage
is **Swift with an `s3api` layer that does not implement bucket CORS** ([OpenStack bug #2077629](https://bugs.launchpad.net/swift/+bug/2077629)),
which Drive's browser-direct uploads need in `external` mode; and (b) it has **no native
transactional-email product**, so the Mailbox's outbound relay must be bolted on separately.

**Decision.** **Scaleway is the recommended host; Infomaniak stays a supported alternative.** Both
ship as sibling Terraform modules behind the **same output contract** (`public_ip`, `ssh_target`,
`s3_endpoint`, `s3_region`, `buckets`, `s3_access_key`, `s3_secret_key`), so bootstrap and Helmfile
are provider-agnostic ([ADR-003](#adr-003-pluggable-object-storage-garage-or-external-eu-s3)). Scaleway
wins on the two limits above:

- **Object Storage is fully S3-compatible and CORS-capable** → `external` mode works end-to-end,
  including Drive uploads (the module sets a bucket CORS rule); no in-cluster Garage required.
- **Transactional Email (TEM)** is a native relay → the Mailbox gets deliverability with no third
  party. Because Scaleway Instances **block outbound 25/465/587**, the module wires TEM's alternate
  port **2587** (STARTTLS) ([ADR-021](#adr-021-mailbox-suitenumeriquemessages-outbound-via-eu-relay),
  [ADR-027](#adr-027-non-http-ingress-inbound-smtp-on-port-25-via-k3s-servicelb)).

The Scaleway module is also **shorter** than the OpenStack one (no floating-IP-via-port indirection,
no Swift/S3 namespace split):

| Need | Infomaniak (OpenStack) | Scaleway (native) |
|---|---|---|
| Server | `openstack_compute_instance_v2` + boot volume | `scaleway_instance_server` (root `sbs_volume`; PRO2 has no local SSD) |
| Public IP | floating IP + port + associate | `scaleway_instance_ip` (attached to the server) |
| Firewall | `openstack_networking_secgroup*` | `scaleway_instance_security_group` |
| SSH key | `openstack_compute_keypair_v2` | `scaleway_iam_ssh_key` (project, injected via cloud-init) |
| Object storage | EC2 credential + `aws` provider → S3 | `scaleway_object_bucket` + `scaleway_iam_application`/`policy`/`api_key` |
| Outbound mail | external SMTP relay | `scaleway_tem_domain` (native) |

**Consequences.** The happy path is `external` S3 + TEM on Scaleway, with Garage and an external
relay as the fallbacks for Infomaniak or full sovereignty. Two Scaleway specifics the module already
handles but operators must know: **Object Storage is IAM-authorized** — the S3 key needs a policy
(`ObjectStorageFullAccess`) scoped to the project *and* `default_project_id` set to that project, or
every S3 call 403s; and the Terraform key itself needs **`IAMManager`** (org-scoped) to mint the
apps' S3 key. Scaleway also **caps API-key lifetime** (~1 year), so the apps' key must be rotated
and re-applied before it lapses. Scaleway Debian images log in as **`root`** (Infomaniak uses
`debian`); the bootstrap hardens root afterward.

## ADR-039 — Meet media ports: single UDP mux + TCP fallback

**Context.** [Meet](../understand/meet.md) (`suitenumerique/meet`) is built on **LiveKit**, so
unlike every other app it cannot run entirely behind Traefik: WebRTC media is **UDP** (with a TCP
fallback), not HTTP. LiveKit's default deployment opens a **10 000-port UDP range** (50000–60000)
and can bundle a TURN server — far more surface than a single small association VPS wants, and
awkward for a firewall that is otherwise 22/80/443 (+25 for the mailbox).

**Decision.** Run LiveKit in its **smallest reachable footprint** and open the media path with a
dedicated `enable_meet` flag, reusing the port-25 seam from
[ADR-027](#adr-027-non-http-ingress-inbound-smtp-on-port-25-via-k3s-servicelb) — now extended to UDP:

- **One muxed UDP port `7882`** (`rtc.udp_port`, range zeroed) for all media, plus **one TCP port
  `7881`** (`rtc.tcp_port`) as a fallback for UDP-hostile clients. **No port range, no TURN.**
- LiveKit runs with **`hostNetwork`** and binds those two ports on the node directly
  (`use_external_ip: true` to advertise the server's public IP). Signaling stays a normal Traefik
  ingress on 443 (`wss://livekit.{domain}`).
- **`enable_meet`** opens `7881/tcp` + `7882/udp` in both the Terraform security group (Scaleway +
  Infomaniak) and the Ansible UFW rules — a boolean mirror of `enable_mailbox`. Off by default.
- Recording (LiveKit Egress) writes to its own **`meet-recordings`** S3 bucket; the AI/transcription
  components ship at zero replicas.

**Consequences.** A single UDP port keeps the firewall and k3s host-port model simple and is enough
for association-scale concurrency. The trade-offs, recorded so they are a choice not an omission:
a client on a network that blocks **both** UDP/7882 and TCP/7881 cannot connect until embedded
TURN/TLS is added; and authenticated recording **download** (the upstream nginx `auth_request`
`/media/` path) is deferred — recordings are stored in S3 but a Traefik media-proxy for downloads
is a follow-up, as for Docs.

**Update (issue #55).** Both trade-offs above are now resolved, without changing the default
footprint:

- **Recording/file download proxy shipped.** A `meet-media-proxy` release (the shared
  `charts/media-proxy`, as for Docs/Drive) serves `/media/recordings/` and `/media/files/` on
  Traefik, each authorized by its own backend media-auth route. No new ports.
- **Embedded TURN/TLS is now opt-in.** Set `OWNSUITE_MEET_TURN=true` (app side) **and**
  `enable_meet_turn=true` (Terraform/Ansible) to have LiveKit terminate TURN/TLS on the node at
  **`5349/tcp`**, reusing the `livekit-tls` cert on `livekit.{domain}` — so no extra certificate
  and no new DNS record. Off by default: it is only needed for clients blocked on both media ports,
  and it adds one open port. `enable_meet_turn` mirrors `enable_meet` in both the Terraform security
  group and the Ansible UFW rules.

---

## ADR-040 — `suite` on PATH via a global pipx install + static shell completion

**Context.** [ADR-037](#adr-037-one-entrypoint-for-operators-every-action-is-a-suite-cli-verb) made
every operator action a `suite` verb but left the CLI unpackaged: with no `pyproject.toml`, nothing
puts a `suite` executable on `PATH`, so every command is spelled `python3 -m suite …`. ADR-037
flagged this as a deferred trade-off ("until a `suite` shim is on `PATH`"). There was also **no shell
completion** — argparse gives `--help` but no tab-completion, and completion keys off a command name
on `PATH`, so it was blocked on the shim.

**Decision.** Ship a minimal `pyproject.toml` (setuptools/PEP 621, distribution name `ownsuite`,
import package stays `suite`) with a `[project.scripts] suite = "suite.cli:main"` entry point, and
install the command **globally with `pipx install --editable .`**. pipx keeps the CLI in its own
isolated environment yet exposes `suite` on `PATH` in **every** shell, active virtualenv or not; the
CLI operates on cwd-relative paths (`ansible/`, `helmfile/`, `.env`), so a global command run from
the checkout works. pyproject reads the pinned runtime dep from `requirements.txt` via `dynamic`
dependencies, so `requirements.txt` stays the single source of truth (AGENTS.md). `suite deps`
keeps installing that runtime dep (`pip install -r requirements.txt`) plus the dev/Ansible tooling,
for the `python -m suite` path; it does **not** install the `suite` command. `python -m suite` is
unchanged and always works from a bare checkout, including the first `suite deps` itself. For
completion, ship **hand-written `completions/suite.{bash,zsh}`** an operator sources from their shell
rc — no runtime dependency (keeps the base CLI pure standard library), unlike `argcomplete`. A unit
test (`tests/test_completion.py`) parses `build_parser()` and asserts every subcommand appears in
both completion scripts, so a new verb can't ship with a stale completion.

**Rejected: `pip install -e .` inside the project venv.** It was the first cut (issue #69) but puts
`suite` only on the *venv's* `PATH`. Outside the venv — and with zsh `AUTO_CD`, which the maintainer
runs — a bare `suite` typed in the repo root is silently read as `cd suite/` (the package directory),
not "command not found", because the executable isn't on `PATH`. A global pipx install puts the
command on `PATH` unconditionally, so the shell always resolves it as the command and `AUTO_CD` never
fires. pipx over a system-wide `pip install` because it isolates the CLI's dependency and is the
standard way to install a Python end-user CLI.

**Consequences.** The docs' canonical `suite <verb>` spelling is now literally runnable in any shell,
closing ADR-037's trade-off. pipx is an extra prerequisite for the short form, but it is optional —
`python -m suite <verb>` needs nothing beyond the checkout. The completion scripts are maintained by
hand — accepted, guarded by the drift test, and cheaper than adding `argcomplete` as a runtime
dependency, preserving the "pure standard library, no dependency to run" property that lets
`python -m suite deps` work from a bare clone.
