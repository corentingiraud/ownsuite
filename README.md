# OwnSuite

Self-host **[La Suite numérique](https://github.com/suitenumerique)**,
*production-ready*, on a **single VPS**, for a **non-profit** — single-node K3s +
Helmfile, shared Keycloak SSO, CloudNativePG, pluggable S3 storage, and backups with
tested restore.

> **Status:** early-stage. The design is documented; code follows the roadmap.

## Documentation

The full design lives in the documentation site (built with MkDocs Material):

- **Overview & vision** — `docs/index.md`
- **Architecture** — `docs/architecture/overview.md`
- **Decisions (ADR)** — `docs/architecture/decisions.md`
- **Roadmap** — `docs/roadmap.md`
- **For AI agents** — `docs/contributing/for-ai-agents.md`

Preview locally:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-docs.txt
mkdocs serve   # http://127.0.0.1:8000
```

## Contributing

See [`AGENTS.md`](AGENTS.md) for repository conventions. In short: **everything is
written in English**, versions are pinned, and no plaintext secrets.

## License

[AGPL-3.0](LICENSE) — you may use it commercially and offer paid hosting, but a modified version exposed over a network must publish its source under AGPL-3.0.
