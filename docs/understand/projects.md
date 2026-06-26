# Projects application

An **optional** app beyond the core (Docs + Drive). **Projects**
([suitenumerique/projects](https://github.com/suitenumerique/projects) — kanban boards / task
management, a Sails.js fork of Planka) is wired to the same shared foundation, with Keycloak SSO
so a user provisioned once reaches it on first login.

!!! note "Off by default"
    Projects ships **disabled** (`OWNSUITE_APP_PROJECTS`, default `false`). It's an optional extra,
    not part of the tested core. It's fully wired and ready; turn it on with one flag (below).

Like Grist, Projects is **not** a `suitenumerique`/impress app: a single-container Node (Sails.js)
app with **no official Helm chart**, so OwnSuite ships a thin local chart
(`helmfile/charts/projects`). It is gated on `apps.projects.enabled` and depends, via `needs:`, on
a subset of the shared infrastructure:

| Needs | For |
|---|---|
| `platform-configuration` | Derived secrets (`projects-secrets` incl. the built `DATABASE_URL`, `projects-db`) + the `projects` OIDC client |
| `postgres` | The dedicated `projects` database |
| `keycloak` | SSO — the `projects` OIDC client |
| `issuers` | The `projects-tls` certificate (cert-manager) |

It needs **neither Valkey nor S3**: on a single node, Projects keeps its file uploads on a local
volume and its data in Postgres.

## How it is wired

It mirrors the Grist choices
,
with two Projects-specific details:

- **OIDC by single public issuer.** `OIDC_ISSUER` is the **public** realm URL
  `https://auth.{domain}/realms/{realm}`; openid-client discovers every endpoint from it, and the
  in-cluster backend hairpins with the real certificate in production. The `projects` confidential
  client reuses the existing client template (its `redirectUris: https://projects.{domain}/*` covers
  the OIDC callback). **One wrinkle:** our Keycloak client signs the *userinfo* response with RS256,
  and Projects reads claims from userinfo, so `OIDC_USERINFO_SIGNED_RESPONSE_ALG=RS256` is set —
  without it openid-client cannot parse the signed response.
- **Single `DATABASE_URL`, built with the derived password.** Projects wants one connection string,
  so `platform-configuration` assembles `postgresql://projects:<derived>@<cnpg-rw-host>:5432/projects`
  into the `projects-secrets` Secret — the password never lands in the rendered values.
- **Uploads on a PVC.** Avatars, project backgrounds and attachments live on the `projects-data`
  volume (three subPaths). `SECRET_KEY` and the OIDC client secret are seed-derived.

All of it is in `helmfile/values/projects.yaml.gotmpl`; nothing secret is committed.

## Run it

```bash
set -a && source .env && set +a          # OWNSUITE_SECRET_SEED, OWNSUITE_DOMAIN, ...
export OWNSUITE_APP_PROJECTS=true        # opt in (off by default)
make tunnel                              # in another terminal
make sync                                # brings up the infra + enabled apps + Projects
```

When it finishes, Projects answers at `https://projects.{domain}`; log in with a Keycloak user
(e.g. one created by `suite user add`). Tune the upload volume with `OWNSUITE_PROJECTS_STORAGE`.

## Tests

Projects' deployment is checked by the static suite (`make lint-helm`) and booted nightly on its
own throwaway cluster: the nightly check brings Projects up, confirms it converges, and that its
UI is reachable over HTTPS. It runs on a cluster of its own (separate from Docs and Drive) so the
memory-constrained shared runner never has to hold every app at once. Run it yourself with
`make test-app APP=projects`. The browser single sign-on dance still wants a real human pass on
the first production deployment.

## Limits

- **The uploads PVC is not yet off-site-backed** — the same pre-existing gap as Grist's PVC and
  Drive's bucket (`object-backup` copies a single bucket today).
- **Browser login unverified in CI** — the nightly check boots Projects and confirms its UI is
  reachable, but the full browser single sign-on flow still wants a human pass on the first real
  deployment.
