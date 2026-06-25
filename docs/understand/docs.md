# Docs application

Phase 2's deliverable: deploy **Docs** (the [suitenumerique](https://github.com/suitenumerique/docs)
app, upstream name *impress*) wired to the whole Phase 1 foundation, and prove the
end-to-end vertical slice.

> **Definition of done:** a Keycloak user logs into `https://docs.{domain}` via **SSO**
> and creates a **persistent document** — machine-verified in CI.

Docs is a Helmfile release like any other app (the Phase 1 "add an app" pattern). It is
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
  from the seed-derived `docs-db` Secret ([ADR-012](decisions.md#adr-012-secrets-derived-from-a-single-secretseed-via-helm-templating)).
- **Cache / broker** — `REDIS_URL` / `DJANGO_CELERY_BROKER_URL` embed the derived Valkey
  password and target the in-cluster Valkey service.
- **Object storage** — `AWS_*` come from `s3-credentials`. In `garage` mode the endpoint is
  the in-cluster Garage service; in `external` mode it is your configured S3 endpoint
  ([ADR-003](decisions.md#adr-003-pluggable-object-storage-garage-or-external-eu-s3),
  [ADR-015](decisions.md#adr-015-in-cluster-object-storage-garage-single-node-deterministic-key)).
- **SSO** — the `docs` confidential OIDC client (secret derived from the same seed id the app
  reads). The browser hits `https://auth.{domain}`; the backend reaches Keycloak in-cluster
  ([ADR-016](decisions.md#adr-016-docs-impress-integration-one-namespace-traefik-ingress-oidc-split)).
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
`docs-media-storage` bucket — so a fresh cluster is self-sufficient
([ADR-015](decisions.md#adr-015-in-cluster-object-storage-garage-single-node-deterministic-key)).

## Run it

```bash
set -a && source .env && set +a          # OWNSUITE_SECRET_SEED, OWNSUITE_DOMAIN, ...
make tunnel                              # in another terminal (ADR-014)
make sync                                # brings up the infra + Docs
```

When it finishes, Docs answers at `https://docs.{domain}`; log in with a Keycloak user.

## Adding or changing an OIDC client (existing realm)

Keycloak imports a realm only on its **first** boot (`--import-realm`), so on a fresh
install (and in CI) the `docs` client is created by the import. On an **already-running**
install the `keycloak-config` release keeps clients in sync: an idempotent `kcadm` **upsert
Job** runs on every `sync` and creates-or-updates each `keycloak.clients` entry (redirect
URIs, web origins, secret) against the live realm — so adding or changing a client just
works, with no manual admin-console step
([ADR-020](decisions.md#adr-020-keycloak-realm-convergence-idempotent-oidc-client-upsert)).

## Tests

`make test-platform` extends the k3d e2e to deploy Docs in `garage` mode and assert the DoD:
Garage bucket reachable, the `docs` database created, the Docs pods Ready and answering over
HTTPS, the `docs` OIDC client wired, and — the definition of done — a token obtained from
Keycloak **creates and reads back a document** through the Docs API, proving SSO wiring and
database persistence. A full browser-driven SSO + collaboration check is deferred to a
targeted job ([ADR-010](decisions.md#adr-010-testing-ci-strategy-a-layered-evolving-harness)).
