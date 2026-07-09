# Calendars application

**Calendars**
([suitenumerique/calendars](https://github.com/suitenumerique/calendars) — La Suite
numérique's shared-calendar app) is wired to the same shared foundation, with Keycloak SSO
so a user provisioned once reaches it on first login (JIT — no per-app step). The whole
point of packaging it here is **coupling with the rest of the suite**: a one-click
[Meet](meet.md) link on an event, colleagues seeing each other's availability, and — when
[Messages](messages.md) is also on — a user's mailboxes offered as invitation-sender addresses.

!!! note "Off by default"
    Calendars ships **disabled** (no `calendars:` entry under `apps:` by default). It's an
    optional extra, not part of the tested core. Turn it on with one line in `suite.yaml`
    (below).

!!! warning "Early upstream"
    Calendars is a **pre-production prototype** (upstream v0.1.0, 2026-06). Its two headline
    coupling features are asymmetric in maturity: **org free/busy sharing is real and
    e2e-tested upstream**, while the **Meet link is only URL-string generation** (a random
    room id), not authenticated room provisioning. Image tags are pinned in
    `versions.yaml`; treat upstream `main` as moving.

Like Grist and Projects, Calendars is **not** a `suitenumerique`/impress app with an
official Helm chart — it ships only a `compose.yaml`. So OwnSuite runs it from a thin local
chart (`helmfile/charts/calendars`), gated on `apps.calendars.enabled`, depending via
`needs:` on a subset of the shared infrastructure:

| Needs | For |
|---|---|
| `platform-configuration` | Derived secrets (`calendars-secrets`, `calendars-db`) + the `calendars` OIDC client (with the org-claim mapper) in the realm |
| `postgres` | The dedicated `calendars` database (events/calendars/organizations/sharing; the CalDAV service keeps its tables in a `sabre` schema of the same DB) |
| `valkey` | Cache + the Dramatiq broker/results (three DB indices on the shared Valkey) |
| `keycloak` | SSO — the `calendars` OIDC client |
| `issuers` | The `calendars-tls` certificate (cert-manager) |

It needs **no S3** — Calendars stores no object attachments today.

## The four components

Unlike the single-container Grist, Calendars is four Deployments from one chart:

| Component | Image | Role |
|---|---|---|
| **backend** | `calendars-backend` | Django/DRF — the API, OIDC, and the config the SPA reads |
| **worker** | `calendars-backend` (same image, `worker.py`) | **Dramatiq** background tasks (not Celery), Valkey broker |
| **frontend** | `calendars-frontend` | The web UI (SPA) |
| **caldav** | `calendars-caldav` | SabreDAV/PHP/Apache — **where sharing & free-busy are enforced**, and what makes standard CalDAV clients work |

The backend runs its `manage.py migrate` as a pre-upgrade Helm hook; the CalDAV service
initialises its own `sabre` schema on start.

## How it is wired

- **OIDC by the external/internal split** (like [Docs](docs.md)/Meet, not Grist's
  single-issuer discovery). The browser hits Keycloak at `https://auth.{domain}`; the
  backend reaches it in-cluster over plain HTTP. New confidential client `calendars`
  (secret seed-derived), reusing the shared client template — its
  `redirectUris: https://calendars.{domain}/*` already cover the OIDC callback.
- **One host, served same-origin.** The frontend's API origin is baked at **build time**,
  so it can only talk to a backend on its own origin. The single `calendars.{domain}`
  ingress therefore routes the Django prefixes (`/api`, `/admin`, `/static`) to the backend
  and everything else to the frontend.
- **State on Postgres + Valkey, no S3.** One CNPG `calendars` database holds Django's data;
  the CalDAV service keeps its SabreDAV tables in a `sabre` schema of that same database
  (upstream's own topology), connecting as the same owner role. The Dramatiq broker,
  its results and the Django cache use three dedicated indices on the shared Valkey
  (dbs 9/10/11), so no separate Redis pod is added.

All of it is in `helmfile/values/calendars.yaml.gotmpl`; nothing secret is committed.

## The coupling features

### One-click Meet link on an event

The event editor has a "create visio" button that generates a room under
`FRONTEND_MEET_BASE_URL`. OwnSuite sets that to `https://meet.{domain}` **only when
[Meet](meet.md) is also enabled** — so the button attaches a link straight to your own Meet,
and never dangles a link to a host that doesn't exist. Today this is only URL-string
generation with a random room id; deeper (pre-provisioned/authenticated) rooms are upstream
work ([calendars#19](https://github.com/suitenumerique/calendars/issues/19)) and deferred.

### See colleagues' calendars when shared to the org

Sharing levels `none` / `freebusy` / `read` / `write` are stored on each calendar and
**enforced in the CalDAV (SabreDAV) layer** — at `freebusy` level event details are stripped
server-side so sharees see only availability. The org-wide default is `freebusy`
(`sharing_level`), so same-org "find a time" works out of the box. **Cross-org is
hard-blocked upstream; there is no internet-public calendar.**

The one piece of genuinely new Keycloak config this needs: org membership comes from an
**OIDC claim**. OwnSuite adds a hardcoded-claim mapper to the `calendars` client that emits a
constant `organization` claim in userinfo (single-org OwnSuite: everyone in one org); the
backend maps it (`OIDC_USERINFO_ORGANIZATION_CLAIM`) into its `Organization` model. Without
that claim every user would be org-less and org sharing would do nothing.

### Your mailboxes as invitation senders (only with Messages)

When [Messages](messages.md) is also enabled, Calendars discovers the mailboxes you own and
offers them as the "from" address on an invitation, instead of falling back to the system
address. It reads them from Messages' provisioning API **service-to-service** — not with your
login token: Calendars sends `X-Channel-Id` + `X-API-Key` headers that Messages validates
against a global `api_key` **Channel** with the `mailboxes:read` scope. The channel id
(a UUID) and the key both come from the shared `calendars-secrets` (seed-derived, ADR-012), so
the two sides agree byte-for-byte. Messages has no command to create that channel, so a small
**idempotent Job on the Messages release** upserts it on every `suite apply` (the same ORM-shell
seam as its mail-domain seed). It only wires up when **both** apps are on; with Messages off the
integration stays disabled and you simply see the system-address fallback.

## Run it

```bash
$EDITOR suite.yaml     # add `calendars: {}` under apps:
suite apply            # -> https://calendars.<domain>/
```

When it finishes, Calendars answers at `https://calendars.{domain}`; log in with a Keycloak
user (e.g. one created by `suite user add`). The one option, `sharing_level`
(`none|freebusy|read|write`), goes under the app's key — e.g.
`calendars: {sharing_level: read}`; see the
[configuration reference](../reference/configuration.md#per-app-options).

## Tests

Calendars' deployment is checked by the static suite (`make lint-helm`) and booted on its own
throwaway cluster: the check brings all four components up, confirms they converge, and that
the web UI answers over HTTPS through Traefik with SSO wired. It runs on a cluster of its own
(separate from the other apps) so the memory-constrained runner never holds every app at
once. Run it yourself with `make test-app APP=calendars`.

## Limits

- **Meet coupling is shallow** — a generated room URL, not an authenticated/provisioned room
  (upstream [#19](https://github.com/suitenumerique/calendars/issues/19)).
- **CalDAV is cluster-internal in v1** — the web UI works, but there is no external
  `caldav.{domain}` host for desktop/mobile CalDAV clients (Thunderbird, iOS) yet.
- **No off-site attachment backup gap** — Calendars stores no objects; its database is
  covered by the automatic CNPG PITR backups like every other app's.
- **Upstream is v0.1.0** — expect churn; the frontend's build-time API origin means a future
  image that bakes a non-relative origin would need same-origin serving to keep working.
