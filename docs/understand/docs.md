# Docs application

**Docs** (the [suitenumerique](https://github.com/suitenumerique/docs) app, upstream name
*impress*) is OwnSuite's first core app — collaborative documents wired to the whole shared
foundation, machine-verified end to end in CI.

> **What it proves:** a user logs into `https://docs.{domain}` with single sign-on and
> creates a document that's still there afterwards — checked automatically in CI.

Docs is a Helmfile release like any other app (the shared "add an app" pattern). It is
gated on `apps.docs.enabled` and depends, via `needs:`, on the shared infrastructure:

| Needs | For |
|---|---|
| `platform-configuration` | Derived secrets (`docs-secrets`, `docs-db`, `s3-credentials`) + the `docs` OIDC client in the realm |
| `postgres` | The dedicated `docs` database (CNPG `Database` + owner role) |
| `valkey` | Django cache (db 0) and Celery broker (db 1) |
| `keycloak` | SSO — the `docs` OIDC client |
| `garage` *(garage mode)* | The S3 bucket for media/attachments |
| `issuers` | The `docs-tls` certificate (cert-manager) |

## How it is wired

- **Database** — `DB_HOST` points at the CNPG `-rw` service; the `docs` role password comes
  from the seed-derived `docs-db` Secret.
- **Cache / broker** — `REDIS_URL` / `DJANGO_CELERY_BROKER_URL` embed the derived Valkey
  password and target the in-cluster Valkey service.
- **Object storage** — `AWS_*` come from `s3-credentials`. In `garage` mode the endpoint is
  the in-cluster Garage service; in `external` mode it is your configured S3 endpoint.
- **SSO** — the `docs` confidential OIDC client (secret derived from the same seed id the app
  reads). The browser hits `https://auth.{domain}`; the backend reaches Keycloak in-cluster.
- **Real-time collaboration** — the y-provider websocket server, exposed at
  `/collaboration/ws/` through Traefik; backend and y-provider share a seed-derived secret.

All of it is configured in `helmfile/values/docs.yaml.gotmpl`; nothing secret is committed.

## Object storage modes

```bash
# Self-hosted, in-cluster (default for CI / sovereignty): deploys Garage + bucket.
OWNSUITE_OBJECT_STORAGE_MODE=garage

# External managed EU S3 (recommended production default): nothing deployed in-cluster.
OWNSUITE_OBJECT_STORAGE_MODE=external
OWNSUITE_S3_ENDPOINT=https://s3.example-eu.com
```

In `garage` mode a single-node Garage `StatefulSet` is deployed and a post-install Job
bootstraps the cluster layout, **imports the seed-derived S3 key**, and creates the
`docs-media-storage` bucket — so a fresh cluster is self-sufficient.

## Run it

```bash
set -a && source .env && set +a          # OWNSUITE_SECRET_SEED, OWNSUITE_DOMAIN, ...
make tunnel                              # in another terminal
make sync                                # brings up the infra + Docs
```

When it finishes, Docs answers at `https://docs.{domain}`; log in with a Keycloak user.

## Adding or changing an OIDC client (existing realm)

Keycloak imports a realm only on its **first** boot (`--import-realm`), so on a fresh
install (and in CI) the `docs` client is created by the import. On an **already-running**
install the `keycloak-config` release keeps clients in sync: an idempotent `kcadm` **upsert
Job** runs on every `sync` and creates-or-updates each `keycloak.clients` entry (redirect
URIs, web origins, secret) against the live realm — so adding or changing a client just
works, with no manual admin-console step.

## Tests

`make test-platform` brings Docs up on a throwaway cluster and checks the whole chain: the
storage bucket is reachable, the database and login client are created, the pods answer over
HTTPS, and — the key check — a real login token **creates and reads back a document** through
the Docs API, proving single sign-on and that data persists. A full browser-driven login +
collaboration check is left to a separate job.
