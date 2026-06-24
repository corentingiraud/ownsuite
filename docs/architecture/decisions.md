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
infra up; Phase 3 adds the install → upgrade → **restore** replay ADR-006 mandates —
both plug into the same Molecule/Testinfra/matrix harness rather than introducing a new
one.

**Consequences.** Robust feedback proportional to risk, and a test foundation that the
later phases inherit instead of reinventing. Cost: Molecule/Testinfra are Python dev
dependencies, and the nightly full run consumes CI minutes (bounded to the two Debian
targets).
