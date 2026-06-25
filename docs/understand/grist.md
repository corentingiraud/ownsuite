# Grist application

Phase 5 broadens the suite beyond the DoD apps (Docs + Drive). **Grist**
([getgrist](https://github.com/gristlabs/grist-core) — spreadsheets that behave like a
database) is wired to the same Phase 1 foundation, with Keycloak SSO so a user provisioned
once reaches it on first login (JIT — no per-app step).

!!! note "Off by default"
    Grist ships **disabled** (`OWNSUITE_APP_GRIST`, default `false`). It is outside the hard
    Phase 5 definition of done and is **not yet booted in the CI e2e** (the constrained runner
    is already near its ceiling). It is fully wired and validated by `helm template` +
    kubeconform; enable it with one flag (below). See
    [ADR-024](decisions.md#adr-024-grist-integration-local-chart-public-issuer-oidc-pvc-storage-off-by-default).

Unlike Docs/Drive, Grist is **not** a `suitenumerique`/impress app: it is a single-container
Node app with **no official Helm chart**, so OwnSuite ships a thin local chart
(`helmfile/charts/grist`). It is gated on `apps.grist.enabled` and depends, via `needs:`, on a
subset of the shared infrastructure:

| Needs | For |
|---|---|
| `platform-configuration` | Derived secrets (`grist-secrets`, `grist-db`) + the `grist` OIDC client in the realm |
| `postgres` | The dedicated `grist` **home** database (orgs/users/workspaces/ACLs) |
| `keycloak` | SSO — the `grist` OIDC client |
| `issuers` | The `grist-tls` certificate (cert-manager) |

It needs **neither Valkey nor S3**: on a single node, Grist keeps its documents as SQLite files
on a local volume and its metadata in Postgres.

## How it is wired

Three choices differ from the impress apps
([ADR-024](decisions.md#adr-024-grist-integration-local-chart-public-issuer-oidc-pvc-storage-off-by-default)):

- **OIDC by single public issuer.** Grist discovers every endpoint from one
  `GRIST_OIDC_IDP_ISSUER` and has no per-endpoint override, so (unlike Docs/Drive) it points at
  the **public** realm URL `https://auth.{domain}/realms/{realm}`. The browser and the in-cluster
  backend both reach Keycloak there; in production the backend hairpins with the real Let's
  Encrypt certificate, so no TLS-skip or CA wiring is needed. The `grist` confidential OIDC client
  (secret derived from the same seed id the app reads) reuses the existing client template
  verbatim — its `redirectUris: https://grist.{domain}/*` already covers Grist's `/oauth2/callback`.
- **Documents on a PVC, home DB on CNPG.** Grist's document SQLite files live on the
  `grist-persist` volume (mounted at `/persist`); orgs, users and ACLs live in a dedicated CNPG
  `grist` database via `TYPEORM_*`. The session secret and OIDC client secret are seed-derived
  ([ADR-012](decisions.md#adr-012-secrets-derived-from-a-single-secretseed-via-helm-templating))
  in `grist-secrets`; the home-DB password is the per-app `grist-db` Secret.
- **Formula sandbox `unsandboxed` by default.** `gvisor` (the image default) needs node
  capabilities stock K3s does not reliably grant; OwnSuite is a single trusted organisation, so
  `GRIST_SANDBOX_FLAVOR=unsandboxed` boots reliably. Set `OWNSUITE_GRIST_SANDBOX=gvisor` on a node
  configured for it.

All of it is in `helmfile/values/grist.yaml.gotmpl`; nothing secret is committed.

## Run it

```bash
set -a && source .env && set +a          # OWNSUITE_SECRET_SEED, OWNSUITE_DOMAIN, ...
export OWNSUITE_APP_GRIST=true           # opt in (off by default)
make tunnel                              # in another terminal (ADR-014)
make sync                                # brings up the infra + enabled apps + Grist
```

When it finishes, Grist answers at `https://grist.{domain}`; log in with a Keycloak user (e.g.
one created by `suite user add`). Tune the document volume with `OWNSUITE_GRIST_STORAGE` and the
team-site name with `OWNSUITE_GRIST_ORG`.

## Tests

Grist is **template/lint-validated** (`make lint-helm`: `helm lint` the chart standalone +
kubeconform the rendered manifests), but — unlike Docs/Drive — it is **not booted in the k3d
e2e** (runner footprint; it is outside the DoD). The natural next step before it becomes a
default app is a targeted boot check: enable Grist on a beefier/nightly runner and assert a
Keycloak user reaches it
([ADR-010](decisions.md#adr-010-testing-ci-strategy-a-layered-evolving-harness)).

## Limits

- **The documents PVC is not yet off-site-backed** — the same pre-existing gap as Drive's bucket
  (`object-backup` copies a single bucket today). Closing it means teaching the off-site copy to
  cover N buckets / the volume; deferred until Grist graduates from off-by-default
  ([ADR-024](decisions.md#adr-024-grist-integration-local-chart-public-issuer-oidc-pvc-storage-off-by-default)).
- **`unsandboxed` formulas trust the document authors** (true for one organisation); switch to
  `gvisor` otherwise.
