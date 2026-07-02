# For AI agents

This page (and the [`AGENTS.md`](https://github.com/corentingiraud/ownsuite/blob/main/AGENTS.md) file at the repository root) orient AI assistants contributing to the project.

## Single source of truth

The documentation **is** the specification. Before writing code, an agent reads the docs; after a structural decision, it updates the docs in the same change.

## Endpoints for AI

The site automatically publishes, at the root:

- **[`/llms.txt`](/llms.txt)** — a structured index of every page with descriptions;
- **[`/llms-full.txt`](/llms-full.txt)** — the entire content concatenated into one file.

To load the whole project context at once, fetch `/llms-full.txt`.

## Documentation conventions

- **Pure Markdown**: no JSX/MDX components (keep the source AI-readable).
- **One concept per file**, a descriptive `#` title, stable section headings (anchors act as entry points).
- **Relative links** between pages (`../understand/overview.md`).
- **Typed code blocks** (always set the language); `!!!` admonitions for notes.
- Document every structural decision and its rationale in the docs.

## Code conventions (reminder)

Language

**Everything is written in English** — documentation, code comments, identifiers, commit messages. This rule overrides any contrary instruction.

- No going back to **Bitnami** or **MinIO** (both deprecated/archived).
- **Pinned** versions (charts, images, K3s); never `latest` in production. Don't hand-edit a pin to chase the newest release — **Renovate** opens tested bump PRs (`renovate.json`). Staying current is Renovate's job; staying *tested* is the CI harness's.
- Every secret derives from the `secretSeed` or an explicit override — **never commit a plaintext secret**.

## Build the docs locally

```
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-docs.txt
mkdocs serve        # live preview at http://127.0.0.1:8000
mkdocs build        # generates ./site, including /llms.txt and /llms-full.txt
```
