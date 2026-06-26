# Grist application

An **optional** app beyond the core (Docs + Drive). **Grist**
([getgrist](https://github.com/gristlabs/grist-core) — spreadsheets that behave like a
database) is wired to the same shared foundation, with Keycloak SSO so a user provisioned
once reaches it on first login (JIT — no per-app step).

!!! note "Off by default"
    Grist ships **disabled** (`OWNSUITE_APP_GRIST`, default `false`). It's an optional extra,
    not part of the tested core. It's fully wired and ready; turn it on with one flag (below).

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
:

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
make tunnel                              # in another terminal
make sync                                # brings up the infra + enabled apps + Grist
```

When it finishes, Grist answers at `https://grist.{domain}`; log in with a Keycloak user (e.g.
one created by `suite user add`). Tune the document volume with `OWNSUITE_GRIST_STORAGE` and the
team-site name with `OWNSUITE_GRIST_ORG`.

## Tests

Grist's deployment is checked by the static suite (`make lint-helm`), but — unlike Docs and
Drive — it isn't yet started up in the automated end-to-end tests (it's an optional extra, and
the test runner is memory-constrained). The next step before it becomes a default app is a
boot check on a larger runner that confirms a user can reach it.

## Limits

- **`unsandboxed` formulas trust the document authors** (true for one organisation); switch to
  `gvisor` otherwise.

The documents PVC (`/persist`, holding the SQLite documents) is now backed up off-site: when
backups are on, a reusable rclone copy syncs the volume to the off-site store — encrypted — on the
backup schedule, and restores it during recovery, just like the object (media) copy. So enabling
Grist no longer opens a backup gap.
