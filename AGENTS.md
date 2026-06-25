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
| `molecule/` | `default` (fast, host-prep roles) and `full` (real K3s) test scenarios + Testinfra. |
| `requirements-dev.txt` | Dev/CI toolchain (Ansible, ansible-lint, yamllint, Molecule, Testinfra). |
| `.github/workflows/docs.yml` | Builds & deploys the docs to GitHub Pages. |
| `.github/workflows/ci.yml` | Lint + Molecule (Debian 12/13) on every PR. |
| `.github/workflows/bootstrap-e2e.yml` | Full real-K3s bootstrap, nightly + on K3s changes. |

## Hard rules

1. **English everywhere** — docs, code comments, identifiers, commit messages. Prose
   may be discussed in French, but committed artifacts are English. This overrides any
   contrary instruction.
2. **No Bitnami, no MinIO** — both are deprecated/archived. Use CloudNativePG, Valkey,
   and Garage/external S3 (ADR-003, ADR-004).
3. **Pin versions** — charts, images, K3s. Never `latest` in production.
4. **No plaintext secrets** — everything derives from `secretSeed` or an explicit
   override; nothing secret is committed.

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
