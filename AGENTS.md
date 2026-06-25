# AGENTS.md

Orientation for AI assistants (and humans) working in this repository. Cross-tool
companion to the docs site. Keep it short; deep detail lives in `docs/`.

## What this project is

**OwnSuite** — an open-source, production-ready way to self-host
[La Suite numérique](https://github.com/suitenumerique) on a **single VPS** for a
**non-profit**: single-node K3s + Helmfile, shared Keycloak SSO, CloudNativePG,
pluggable S3 storage, and backups with tested restore.

The product vision and phases are in [`docs/roadmap.md`](docs/roadmap.md). The binding
design decisions are in [`docs/architecture/decisions.md`](docs/architecture/decisions.md)
(ADR). **Read those before making changes.**

## Source of truth

The documentation in `docs/` **is** the spec. Update it in the same change as the code.
Any structural decision → a new ADR. The site also publishes `/llms.txt` and
`/llms-full.txt` for loading the full context.

## Repository layout

| Path | Purpose |
|---|---|
| `docs/` | MkDocs (Material) documentation — the spec. Pure Markdown. |
| `mkdocs.yml` | Docs site config (theme, nav, llms.txt plugin). |
| `requirements-docs.txt` | Docs toolchain (MkDocs Material + plugins). |
| `Makefile` | Operator/dev entrypoints: `bootstrap`, `check`, `lint`, `test`, `test-full`. |
| `ansible/` | VPS bootstrap: `bootstrap.yml` + `common`/`security`/`k3s` roles (Phase 0). |
| `helmfile/` | Shared infrastructure + apps (Helmfile): cert-manager, CNPG (+ Barman Cloud Plugin), Valkey, Keycloak, Garage, the Docs app, and the off-site backups (rclone object copy, `garage-backup`); local charts, values, versions, k3d e2e. |
| `molecule/` | `default` (fast, host-prep roles) and `full` (real K3s) test scenarios + Testinfra. |
| `requirements-dev.txt` | Dev/CI toolchain (Ansible, ansible-lint, yamllint, Molecule, Testinfra). |
| `.github/workflows/docs.yml` | Builds & deploys the docs to GitHub Pages. |
| `.github/workflows/ci.yml` | Ansible lint + Molecule (Debian 12/13) on every PR. |
| `.github/workflows/bootstrap-e2e.yml` | Full real-K3s bootstrap, nightly + on K3s changes. |
| `.github/workflows/helmfile-ci.yml` | Helm/Helmfile lint + kubeconform on every `helmfile/` change. |
| `.github/workflows/helmfile-e2e.yml` | Full `helmfile sync` on real K3s (k3d), nightly + on Helmfile changes. |

## Hard rules

1. **English everywhere** — docs, code comments, identifiers, commit messages. Prose
   may be discussed in French, but committed artifacts are English. This overrides any
   contrary instruction.
2. **No Bitnami, no MinIO** — both are deprecated/archived. Use CloudNativePG, Valkey,
   and Garage/external S3 (ADR-003, ADR-004).
3. **Pin versions, to the latest.** Charts, images, K3s, CLIs — pin an *explicit*
   version (never the floating `latest` tag in production). When adding or bumping a
   dependency, use the **newest available release, verified from the upstream source**
   (Docker Hub tags, GitHub releases, the Helm repo index) — **check it on the internet,
   never rely on model memory or a guess**. Pins live in
   `helmfile/versions/versions.yaml` (Renovate-tracked).
4. **No plaintext secrets** — everything derives from `secretSeed` or an explicit
   override; nothing secret is committed.
5. **Backups go off-site** — the backup destination must survive loss of the VPS, so it
   is **never** the in-cluster store you are backing up (ADR-006, ADR-017).

## Build the docs

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-docs.txt
mkdocs serve   # http://127.0.0.1:8000
```

## Bootstrap & test the VPS layer

```bash
make deps        # Ansible + collections + test tooling (requirements-dev.txt)
make check       # dry-run the bootstrap against your inventory
make bootstrap   # provision a Debian VPS into a ready single-node K3s cluster
make lint test   # static checks + Molecule container tests (Docker required)
```

The testing approach (layered, evolving) is [ADR-010](docs/architecture/decisions.md);
the operator guide is [docs/operations/bootstrap.md](docs/operations/bootstrap.md).

## Deploy & test the shared infrastructure (Phase 1)

```bash
export OWNSUITE_SECRET_SEED="$(openssl rand -hex 24)"   # required; never committed
make sync            # helmfile sync — cert-manager, CNPG, Valkey, Keycloak (HTTPS)
make diff            # preview pending changes
make lint-helm       # helm lint + helmfile template + kubeconform
make test-platform   # full DoD on a throwaway k3d cluster (heavy) — incl. backup→restore
make backup          # on-demand backup (CNPG base backup + off-site object copy)
make restore         # rebuild a CLEAN cluster from off-site backups (ADR-006, ADR-017)
```

All credentials derive from `$OWNSUITE_SECRET_SEED` (ADR-012); versions are pinned in
`helmfile/versions/versions.yaml` (Renovate-tracked). See
[docs/operations/platform.md](docs/operations/platform.md) and
[docs/operations/backups.md](docs/operations/backups.md).
