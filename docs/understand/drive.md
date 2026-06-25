# Drive application

Phase 5's DoD-critical app: deploy **Drive** (the [suitenumerique](https://github.com/suitenumerique/drive)
file manager) wired to the same Phase 1 foundation as Docs, so a user provisioned once has
Docs **and** Drive (JIT — no per-app step).

> **Definition of done:** `suite user add firstname@assoc.org` grants access to
> `https://drive.{domain}` over SSO, immediately — machine-verified in CI (token level).

Drive is a `suitenumerique` sibling of Docs, so it reuses the "add an app" pattern almost
verbatim ([ADR-022](decisions.md#adr-022-drive-integration-reuse-the-docs-seam-per-app-buckets)).
It is gated on `apps.drive.enabled` and depends, via `needs:`, on the shared infrastructure:

| Needs | For |
|---|---|
| `platform-configuration` | Derived secrets (`drive-secrets`, `drive-db`, `s3-credentials`) + the `drive` OIDC client in the realm |
| `postgres` | The dedicated `drive` database (CNPG `Database` + owner role) |
| `valkey` | Django cache (db **2**) and Celery broker (db **3**) — distinct from Docs (0/1) |
| `keycloak` | SSO — the `drive` OIDC client |
| `drive-ingress` | Traefik middlewares for authenticated media |
| `garage` *(garage mode)* | The `drive-media-storage` S3 bucket |
| `issuers` | The `drive-tls` certificate (cert-manager) |

## How it is wired

It is the Docs wiring with two pieces removed and a few names changed
([ADR-022](decisions.md#adr-022-drive-integration-reuse-the-docs-seam-per-app-buckets)):

- **Database** — `DB_HOST` points at the CNPG `-rw` service; the `drive` role password comes
  from the seed-derived `drive-db` Secret ([ADR-012](decisions.md#adr-012-secrets-derived-from-a-single-secretseed-via-helm-templating)).
- **Cache / broker** — `REDIS_URL` (db 2) / `DJANGO_CELERY_BROKER_URL` (db 3) embed the
  derived Valkey password. The **separate broker db** keeps Drive's and Docs' Celery queues
  from cross-consuming each other's tasks.
- **Object storage** — `AWS_*` come from `s3-credentials` (the same key Docs uses); the bucket
  is Drive's own `drive-media-storage`. The Garage bootstrap creates one bucket per enabled
  app; on external S3 you pre-create the Drive bucket alongside the Docs one.
- **SSO** — the `drive` confidential OIDC client (secret derived from the same seed id the app
  reads). Browser → `https://auth.{domain}`; backend → Keycloak in-cluster
  ([ADR-016](decisions.md#adr-016-docs-impress-integration-one-namespace-traefik-ingress-oidc-split)).
- **No real-time collaboration** — Drive is a file manager, so (unlike Docs) it ships no
  y-provider/websocket server.

All of it is in `helmfile/values/drive.yaml.gotmpl`; nothing secret is committed.

## Run it

```bash
set -a && source .env && set +a          # OWNSUITE_SECRET_SEED, OWNSUITE_DOMAIN, ...
make tunnel                              # in another terminal (ADR-014)
make sync                                # brings up the infra + Docs + Drive
```

When it finishes, Drive answers at `https://drive.{domain}`; log in with a Keycloak user.
Turn an app off independently with `OWNSUITE_APP_DRIVE=false` (or `OWNSUITE_APP_DOCS=false`).

## Tests

`make test-platform` extends the k3d e2e to deploy Docs **and** Drive in `garage` mode and
assert the Phase 5 DoD: the `drive` database created, Drive pods Ready and answering over
HTTPS, the `drive` OIDC client wired, and — the definition of done — a user **created through
the `suite user` CLI path** obtains a Keycloak token and is JIT-provisioned into **both** Docs
and Drive through their APIs. Heavy/browser checks stay off-CI
([ADR-010](decisions.md#adr-010-testing-ci-strategy-a-layered-evolving-harness)).

## Deferred

The media-**preview** (thumbnail) ingress is left disabled for v1 — a visual nicety, not part
of the DoD, whose upstream rewrite path needs validating against our Traefik setup
([ADR-022](decisions.md#adr-022-drive-integration-reuse-the-docs-seam-per-app-buckets)).
