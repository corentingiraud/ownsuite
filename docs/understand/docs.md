# Docs application

**Docs** (the [suitenumerique](https://github.com/suitenumerique/docs) app, upstream name
*impress*) is collaborative documents wired to the
whole shared foundation, machine-verified end to end in CI. Like every app it is **opt-in / off by default**;
enable it by adding `docs: {}` under `apps:` in `suite.yaml`.

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
| `rustfs` *(in-cluster mode)* | The S3 bucket for media/attachments |
| `issuers` | The `docs-tls` certificate (cert-manager) |

## How it is wired

- **Database** — `DB_HOST` points at the CNPG `-rw` service; the `docs` role password comes
  from the seed-derived `docs-db` Secret.
- **Cache / broker** — `REDIS_URL` / `DJANGO_CELERY_BROKER_URL` embed the derived Valkey
  password and target the in-cluster Valkey service.
- **Object storage** — `AWS_*` come from `s3-credentials`. In `in-cluster` mode the endpoint is
  the in-cluster RustFS service; in `external` mode it is your configured S3 endpoint.
- **SSO** — the `docs` confidential OIDC client (secret derived from the same seed id the app
  reads). The browser hits `https://auth.{domain}`; the backend reaches Keycloak in-cluster.
- **Real-time collaboration** — yhub (Docs 6.0), reached at
  `wss://docs.{domain}/collaboration/ws/v1/docs` through Traefik. It has its own `yhub` Postgres
  database and uses Valkey database 13 (prefix `yhub`) for live state, which it writes to Postgres
  with a 10 second debounce. If Valkey restarts, up to 10 seconds of edits can be lost. Backend and
  yhub verify each other's tokens with two RSA keys created by a chart job. Before it opens a
  websocket, yhub asks the backend who the user is and what they may do with the document. It
  calls `https://docs.{domain}`, so the server must reach its own public name. If the backend
  does not answer, yhub refuses the connection with a 503. With `tls: selfsigned`, yhub and the
  y-provider skip certificate checks on that call, as the backend already does for OIDC.
  y-provider remains only as the document converter. See [ADR-049](decisions.md#adr-049-docs-60-yhub-replaces-y-provider-for-collaboration).

All of it is configured in `helmfile/values/docs.yaml.gotmpl`; nothing secret is committed.

## Object storage modes

```yaml
# suite.yaml — self-hosted, in-cluster (CI / sovereignty): deploys RustFS + bucket.
object_storage: {mode: in-cluster}

# External managed EU S3 (recommended production default): nothing deployed in-cluster.
object_storage: {mode: external, endpoint: https://s3.example-eu.com}
```

In `in-cluster` mode a single-node RustFS store is deployed, taking the seed-derived
S3 key as its root credential directly, and a small post-install `rclone mkdir` Job
creates the `docs-media-storage` bucket — so a fresh cluster is self-sufficient.

## Run it

```bash
$EDITOR suite.yaml     # add `docs: {}` under apps:
suite apply            # -> https://docs.<domain>/
```

When it finishes, Docs answers at `https://docs.{domain}`; log in with a Keycloak user.
The media bucket is tunable with `apps.docs.s3_bucket` (see the
[configuration reference](../reference/configuration.md#per-app-options)).

## Adding or changing an OIDC client (existing realm)

Keycloak imports a realm only on its **first** boot (`--import-realm`), so on a fresh
install (and in CI) the `docs` client is created by the import. On an **already-running**
install the `keycloak-config` release keeps clients in sync: an idempotent `kcadm` **upsert
Job** runs on every apply and creates-or-updates each `keycloak.clients` entry (redirect
URIs, web origins, secret) against the live realm — so adding or changing a client just
works, with no manual admin-console step.

## Tests

`make test-app APP=docs` boots Docs on its own throwaway cluster and checks the whole chain:
the storage bucket is reachable, the database and login client are created, the pods answer
over HTTPS, and — the key check — a real login token **creates and reads back a document**
through the Docs API, proving single sign-on and that data persists. The same user then opens
the collaboration websocket of a new document and yhub must answer `101 Switching Protocols`.
That needs the yhub to backend call to work, so the e2e cluster resolves `*.{domain}` to
Traefik in CoreDNS, as public DNS does on a real server. It runs nightly and on
any PR that touches Docs (`apps-e2e.yml`); the heavy platform suite (`make test-platform`)
keeps Docs enabled only as the bucket used by the backup/restore check, not as an app DoD. A
full browser-driven editing check is left to a separate job.
