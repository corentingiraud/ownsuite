# For AI agents

This page (and the [`AGENTS.md`](https://github.com/corentingiraud/ownsuite/blob/main/AGENTS.md)
file at the repository root) orient AI assistants contributing to the project.

## Single source of truth

The documentation **is** the specification. Before writing code, an agent reads the
docs; after a structural decision, it updates the docs in the same change.

## The model, in five facts

Facts an agent must not get wrong (details: [CLI reference](../reference/cli.md),
[configuration reference](../reference/configuration.md),
[under the hood](../understand/platform.md)):

1. **One human-owned file: `suite.yaml`** (written by `suite init`, then edited directly).
   Machine state lives in `.suite-state.json` (git-ignored, never hand-edited). The only
   environment input is `OWNSUITE_SECRET_SEED` (plus external creds / CI overrides); a
   git-ignored `.env` in the repo root is **auto-loaded at startup**, so exports persist
   without `source .env`.
2. **`suite apply` reconciles everything** — Terraform, Ansible bootstrap, DNS, apps —
   touching only what changed. Every operator action is a `suite` verb: `init`, `plan`,
   `apply`, `status`, `apps`, `logs`, `info`, `upgrade`, `backup`, `restore`, `destroy`,
   `user add|passwd|disable`, `deps`. `make` is CI/dev shorthand only.
3. **Apps are enabled by presence** under `apps:` in `suite.yaml`; removing a line
   uninstalls the app but keeps its data. Firewall ports follow the app set.
4. **The CLI lives in `suite/`**: `spec.py` (suite.yaml load/validate), `state.py`
   (machine state), `manifest.py` (the single app manifest), `apply.py` (the reconcile
   pipeline), plus one module per verb.
5. **The e2e drives the real flow**: it writes a throwaway `suite.yaml` to a temp path via
   `OWNSUITE_CONFIG` and runs `suite apply --yes --no-tunnel` — a developer's own files are
   never touched.

## Endpoints for AI

The site automatically publishes, at the root:

- **[`/llms.txt`](/llms.txt)** — a structured index of every page with descriptions;
- **[`/llms-full.txt`](/llms-full.txt)** — the entire content concatenated into one file.

To load the whole project context at once, fetch `/llms-full.txt`.

## Documentation conventions

- **Pure Markdown**: no JSX/MDX components (keep the source AI-readable).
- **One concept per file**, a descriptive `#` title, stable section headings (anchors
  act as entry points).
- **Relative links** between pages (`../understand/overview.md`).
- **Typed code blocks** (always set the language); `!!!` admonitions for notes.
- Document every structural decision and its rationale in the docs.

## Code conventions (reminder)

!!! warning "Language"
    **Everything is written in English** — documentation, code comments, identifiers,
    commit messages. This rule overrides any contrary instruction.

- No going back to **Bitnami** or **MinIO** (both deprecated/archived).
- **Pinned** versions (charts, images, K3s); never `latest` in production. Don't
  hand-edit a pin to chase the newest release — **Renovate** opens tested bump PRs
  (`renovate.json`). Staying current is Renovate's job; staying *tested* is the CI harness's.
- Every secret derives from the `secretSeed` or an explicit override — **never commit a plaintext secret**.

## Build the docs locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-docs.txt
mkdocs serve        # live preview at http://127.0.0.1:8000
mkdocs build        # generates ./site, including /llms.txt and /llms-full.txt
```
