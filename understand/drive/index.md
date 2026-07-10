# Drive application

**Drive** (the [suitenumerique](https://github.com/suitenumerique/drive) file manager) is wired to the same shared foundation as Docs, so someone you add once has Docs **and** Drive — with no extra setup per app. Like every app it is **opt-in / off by default**; enable it by adding `drive: {}` under `apps:` in `suite.yaml`.

> **What it proves:** `suite user add firstname@assoc.org` gives that person access to `https://drive.{domain}` over single sign-on, immediately — checked automatically in CI.

Drive is a `suitenumerique` sibling of Docs, so it reuses the "add an app" pattern almost verbatim. It is gated on `apps.drive.enabled` and depends, via `needs:`, on the shared infrastructure:

| Needs                        | For                                                                                                    |
| ---------------------------- | ------------------------------------------------------------------------------------------------------ |
| `platform-configuration`     | Derived secrets (`drive-secrets`, `drive-db`, `s3-credentials`) + the `drive` OIDC client in the realm |
| `postgres`                   | The dedicated `drive` database (CNPG `Database` + owner role)                                          |
| `valkey`                     | Django cache (db **2**) and Celery broker (db **3**) — distinct from Docs (0/1)                        |
| `keycloak`                   | SSO — the `drive` OIDC client                                                                          |
| `drive-ingress`              | Traefik middlewares for authenticated media                                                            |
| `rustfs` *(in-cluster mode)* | The `drive-media-storage` S3 bucket                                                                    |
| `issuers`                    | The `drive-tls` certificate (cert-manager)                                                             |

## How it is wired

It is the Docs wiring with two pieces removed and a few names changed:

- **Database** — `DB_HOST` points at the CNPG `-rw` service; the `drive` role password comes from the seed-derived `drive-db` Secret.
- **Cache / broker** — `REDIS_URL` (db 2) / `DJANGO_CELERY_BROKER_URL` (db 3) embed the derived Valkey password. The **separate broker db** keeps Drive's and Docs' Celery queues from cross-consuming each other's tasks.
- **Object storage** — `AWS_*` come from `s3-credentials` (the same key Docs uses); the bucket is Drive's own `drive-media-storage`. The RustFS bucket-init Job creates one bucket per enabled app; on external S3 you pre-create the Drive bucket alongside the Docs one.
- **SSO** — the `drive` confidential OIDC client (secret derived from the same seed id the app reads). Browser → `https://auth.{domain}`; backend → Keycloak in-cluster.
- **No real-time collaboration** — Drive is a file manager, so (unlike Docs) it ships no y-provider/websocket server.

All of it is in `helmfile/values/drive.yaml.gotmpl`; nothing secret is committed.

## Run it

```
$EDITOR suite.yaml     # add `drive: {}` under apps:  (alongside docs: {}, or on its own)
suite apply            # -> https://drive.<domain>/
```

When it finishes, Drive answers at `https://drive.{domain}`; log in with a Keycloak user. Turn an app off independently by removing its line and re-applying — its data (database, bucket) is kept.

## Tests

`make test-app APP=drive` boots Drive on its own throwaway cluster and checks the key promise: a person **added with `suite user add`** is just-in-time provisioned on their first authenticated call, proven by `/users/me/` echoing their email — no per-app setup. It runs nightly and on any PR that touches Drive (`apps-e2e.yml`); Docs is checked the same way (`make test-app APP=docs`), so one identity reaching **both** is covered end to end. Heavier browser checks stay off-CI.

## Deferred

The media-**preview** (thumbnail) ingress is left disabled for now — a visual nicety whose upstream rewrite path still needs validating against our setup.
