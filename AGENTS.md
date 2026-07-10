# AGENTS.md

Orientation for AI assistants (and humans) working in this repository. Cross-tool
companion to the docs site. Keep it short; deep detail lives in `docs/`.

## What this project is

**OwnSuite** — an open-source, production-ready way to self-host
[La Suite numérique](https://github.com/suitenumerique) on a **single server** for a
**non-profit**: single-node K3s + Helmfile, shared Keycloak SSO, CloudNativePG,
pluggable S3 storage, and backups with tested restore.

The product vision and feature status board are in
[`docs/project/roadmap.md`](docs/project/roadmap.md). The binding design decisions are in
[`docs/understand/decisions.md`](docs/understand/decisions.md) (ADR). **Read those before
making changes.**

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
| `suite.yaml.example` | Commented template for `suite.yaml` — the one human-owned config file (git-ignored, ADR-042). |
| `Makefile` | CI/dev shorthand only (ADR-037): `install` (alias for `suite apply`), `tunnel`/`sync`/`diff`/`destroy`, `backup`/`restore`, `lint*`, `test`, `test-full`, `test-platform` (full DoD via `suite apply`), `test-pvc-backup` (isolated ADR-032 PVC backup/restore, ~3 min), `test-app` (one optional app per cluster). |
| `ansible/` | Server bootstrap: `bootstrap.yml` + `common`/`security`/`k3s` roles. |
| `helmfile/` | Shared infrastructure + apps (Helmfile): cert-manager, CNPG (+ Barman Cloud Plugin), Valkey, Keycloak, Garage, the apps — Docs, Drive, Grist, Projects, the Mailbox (messages), Meet, Tchap and Calendars, **all off by default** (local charts; Meet and Tchap consume upstream charts) — and the off-site backups (rclone object copy, `garage-backup`); local charts, values, versions, k3d e2e. |
| `suite/` | The declarative CLI (ADR-042, plus 018/023/033/034/036/037): `spec.py` (`suite.yaml` load/validate + env assembly), `state.py` (`.suite-state.json` machine state), `manifest.py` (the single app manifest), `apply.py` (the reconcile pipeline), `backup.py`, `info.py`, and the other verb modules — `init`/`plan`/`apply`/`apps`/`info`/`logs`/`tunnel`/`user`/`status`/`upgrade`/`backup`/`restore`/`destroy`/`deps` (no `sync.py`, no `.env`: human input is `suite.yaml`, machine state is `.suite-state.json`). Every operator action is a CLI verb; `make` is CI/dev only. Minimal deps (`questionary`, `PyYAML` — requirements.txt); lint with `ruff` (`ruff.toml`). |
| `tests/` | Unit tests for the `suite` CLI (pytest; mocked resolvers, no cluster). |
| `molecule/` | `default` (fast, host-prep roles) and `full` (real K3s) test scenarios + Testinfra. |
| `requirements-dev.txt` | Dev/CI toolchain (Ansible, ansible-lint, yamllint, Molecule, Testinfra). |
| `.github/workflows/docs.yml` | Builds & deploys the docs to GitHub Pages. |
| `.github/workflows/ci.yml` | Ansible lint + Molecule (Debian 12/13) on every PR. |
| `.github/workflows/bootstrap-e2e.yml` | Full real-K3s bootstrap, nightly + on K3s changes. |
| `.github/workflows/helmfile-ci.yml` | Helm/Helmfile lint + kubeconform on every `helmfile/` change. |
| `.github/workflows/helmfile-e2e.yml` | Two jobs: `pvc-backup` (isolated ADR-032 backup/restore) gates every PR in ~3 min; `full` (`make test-platform`, the heavy suite — platform + `suite apply` + backup/restore, **no app DoD**) runs nightly / on `main` / on demand only — not on PRs. |
| `.github/workflows/apps-e2e.yml` | Per-app boot e2e for ALL eight apps (Docs/Drive/Grist/Projects/messages/Meet/Tchap/Calendars), one app per fresh k3d cluster (ADR-029) — the single source of each app's boot DoD. A PR touching one app's chart/values boots only that app (fast `detect`-driven matrix); the full eight-app sweep runs nightly / on demand. |

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
5. **Backups go off-site** — the backup destination must survive loss of the server, so it
   is **never** the in-cluster store you are backing up (ADR-006, ADR-017).

## Build the docs

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-docs.txt
mkdocs serve   # http://127.0.0.1:8000
```

## Bootstrap & test the server layer

The bootstrap is a phase of `suite apply` (run when the server was never bootstrapped or
the firewall flags changed); the playbook is still directly testable:

```bash
python3 -m suite deps        # Ansible + collections + test tooling (requirements-dev.txt)
cd ansible && ansible-playbook bootstrap.yml --check --diff   # dev dry-run, applies nothing
make lint test               # static checks + Molecule container tests (CI/dev; Docker required)
```

The testing approach (layered, evolving) is [ADR-010](docs/understand/decisions.md);
the operator guide is [docs/get-started/bootstrap.md](docs/get-started/bootstrap.md).

## Deploy & test the shared infrastructure

```bash
suite apply          # reconcile everything to suite.yaml (make install is its alias)

export OWNSUITE_SECRET_SEED="$(openssl rand -hex 24)"   # required; never committed
make diff            # preview pending helmfile changes (dev)
make lint-helm       # helm lint + helmfile template + kubeconform
make test-pvc-backup # isolated ADR-032 PVC backup→wipe→restore on k3d (~3 min) — the PR gate
make test-platform   # platform + `suite apply` + backup→restore DoD on a throwaway k3d cluster (heavy, nightly/main) — no app DoD
make test-app APP=docs   # boot ONE app on its own k3d cluster + assert its boot DoD (grist|projects|messages|docs|drive|meet|tchap)
make backup          # dev shorthand for `suite backup` (CNPG base backup + off-site copy)
make restore         # low-level restore `suite restore` wraps (ADR-006, ADR-017)
```

A raw helmfile sync (the Makefile's `sync` target) is a **dev/debug escape hatch only**:
it bypasses `suite apply`'s rails (issuer pinning, pre-change snapshot, health checks).
The e2e never touches a developer's real config: it writes a throwaway `suite.yaml` to a
temp path via `OWNSUITE_CONFIG` and drives `suite apply --yes --no-tunnel`.

All credentials derive from `$OWNSUITE_SECRET_SEED` (ADR-012); versions are pinned in
`helmfile/versions/versions.yaml` (Renovate-tracked). See
[docs/understand/platform.md](docs/understand/platform.md) and
[docs/operate/backups.md](docs/operate/backups.md).
