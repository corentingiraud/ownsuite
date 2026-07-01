# Configuration reference

OwnSuite is configured entirely through `OWNSUITE_*` environment variables. The
[guided installer](../get-started/install.md) prompts for the common ones and writes them
to a git-ignored `.env`; everything else has a sensible default you can override by adding
it to `.env` (or exporting it) before `make sync` / `suite upgrade`. The **only** secret
that is never written to `.env` is the seed — see [Secrets](#secrets).

```bash
cp .env.example .env
$EDITOR .env
set -a && source .env && set +a
```

## Choosing which apps to deploy

**No app is deployed by default.** A fresh install brings up only single sign-on
(Keycloak) and the shared platform; you opt each app in explicitly. There are two ways:

- **In the installer** — `suite install` prompts for each app (Docs and Drive are
  presented as the recommended first pair), all defaulting off.
- **By variable** — set the app's flag to `true` in `.env` (or export it) and `make sync`.

```bash
OWNSUITE_APP_DOCS=true        # then: make sync   (or: suite upgrade)
```

| App | Variable | Default | What it is |
|---|---|---|---|
| Docs | `OWNSUITE_APP_DOCS` | `false` | Collaborative documents (recommended core). |
| Drive | `OWNSUITE_APP_DRIVE` | `false` | File manager (recommended core). |
| Grist | `OWNSUITE_APP_GRIST` | `false` | Spreadsheets that behave like a database. |
| Projects | `OWNSUITE_APP_PROJECTS` | `false` | Kanban boards / task management. |
| Mailbox | `OWNSUITE_APP_MESSAGES` | `false` | Mail provider + webmail (advanced). |
| Meet | `OWNSUITE_APP_MEET` | `false` | Video conferencing on LiveKit (advanced — also needs `enable_meet`, see below). |

Turning an app off again (`=false`) and re-syncing removes its workloads. Each app reaches
every user you've added through the same single sign-on — see [Users](../operate/users.md).
Per-app detail: [Docs](../understand/docs.md), [Drive](../understand/drive.md),
[Grist](../understand/grist.md), [Projects](../understand/projects.md),
[Mailbox](../understand/messages.md). For how much server each app needs, see
[Sizing](../operate/sizing.md).

## Core

| Variable | Default | Purpose |
|---|---|---|
| `OWNSUITE_SECRET_SEED` | _(required)_ | Single seed every credential is derived from. Generate with `openssl rand -hex 24`; keep it in a password manager. Never written to `.env`. See [Secrets](#secrets). |
| `OWNSUITE_DOMAIN` | `ownsuite.localhost` | Base domain. Each component is exposed at `<name>.{domain}` (e.g. `auth.{domain}`, `docs.{domain}`). |
| `OWNSUITE_ADMIN_EMAIL` | `admin@example.org` | Contact address for app admin / superuser accounts. |
| `OWNSUITE_SERVER_SSH` | _(empty)_ | Server SSH target (`user@host`) used by `make tunnel` and the `suite` CLI to reach the K8s API. |

## TLS / certificates

`make install` drives staging → production automatically; set the issuer by hand only for
the manual flow. See [TLS issuance (ADR-013/019)](../understand/decisions.md#adr-019-tls-staging-first-issuance-dns-01-deferred).

!!! warning "Export the issuer before any manual `make sync`"
    `OWNSUITE_TLS_ISSUER` defaults to `selfsigned`. `suite install` sets it for you, but a
    hand-run `make sync` / `helmfile sync` without it re-issues **every** certificate as
    self-signed (and flips the ingress annotations). Before any manual sync on a live
    deployment, `export OWNSUITE_TLS_ISSUER=letsencrypt-http01` (or `letsencrypt-staging`).

| Variable | Default | Purpose |
|---|---|---|
| `OWNSUITE_TLS_ISSUER` | `selfsigned` | `selfsigned` (CI/dev, no public DNS), `letsencrypt-staging` (untrusted leaf, high rate limits), or `letsencrypt-http01` (production — needs public DNS + port 80). |
| `OWNSUITE_ACME_EMAIL` | `admin@example.org` | ACME registration email (defaults to `OWNSUITE_ADMIN_EMAIL`). |
| `OWNSUITE_ACME_SERVER` | Let's Encrypt production directory | Override the production ACME directory URL. |
| `OWNSUITE_ACME_STAGING_SERVER` | Let's Encrypt staging directory | Override the staging ACME directory URL. |

## Object storage

Pluggable: `external` (a managed EU S3 — files live off the box) or `garage` (an
in-cluster single-node store, deployed and bootstrapped for you). Buckets are created by
Garage in `garage` mode; in `external` mode pre-create the ones for your enabled apps. See
[Object storage (ADR-003)](../understand/decisions.md#adr-003-pluggable-object-storage-garage-or-external-eu-s3).

!!! tip "`external` on Scaleway, `garage` on Infomaniak"
    `external` mode needs an S3 endpoint that can serve **CORS** for Drive's browser
    uploads. **Scaleway** (recommended) and other CORS-capable RGW providers (AWS, OVH)
    support it. **Infomaniak's** Swift+s3api endpoint cannot, so use `garage` there (it
    proxies media same-origin). Details:
    [Provision → Object storage](../get-started/provision.md#object-storage).

The S3 access/secret keys are **external secrets** (not seed-derived). In `external` mode,
export them before sync — see [Secrets](#secrets).

| Variable | Default | Purpose |
|---|---|---|
| `OWNSUITE_OBJECT_STORAGE_MODE` | `external` | `external` (config-only managed S3) or `garage` (in-cluster). Use `garage` on Infomaniak. |
| `OWNSUITE_S3_ENDPOINT` | _(empty)_ | External S3 endpoint URL (`external` mode). |
| `OWNSUITE_S3_ACCESS_KEY` | _(empty)_ | External S3 access key — **secret**, export before sync (`external` mode). |
| `OWNSUITE_S3_SECRET_KEY` | _(empty)_ | External S3 secret key — **secret** (`external` mode). |
| `OWNSUITE_S3_REGION` | `eu-west` | S3 region. Scaleway uses `fr-par` (also `nl-ams`, `pl-waw`, `it-mil`); Infomaniak reports `us-east-1` (compatibility value; data is in CH). |
| `OWNSUITE_S3_BUCKET` | `docs-media-storage` | Docs media/attachments bucket. |
| `OWNSUITE_DRIVE_S3_BUCKET` | `drive-media-storage` | Drive files bucket. |
| `OWNSUITE_PROJECTS_S3_BUCKET` | `projects-media-storage` | Projects uploads bucket. |
| `OWNSUITE_MESSAGES_S3_BUCKET` | `messages-media-storage` | Mailbox message blobs/attachments bucket. |
| `OWNSUITE_MEET_S3_BUCKET` | `meet-recordings` | Meet room-recordings bucket (`OWNSUITE_APP_MEET=true`). |
| `OWNSUITE_GARAGE_META_STORAGE` | `1Gi` | Garage metadata volume size (`garage` mode). |
| `OWNSUITE_GARAGE_DATA_STORAGE` | `10Gi` | Garage data volume size (`garage` mode). |

## Database

| Variable | Default | Purpose |
|---|---|---|
| `OWNSUITE_PG_STORAGE` | `10Gi` | PostgreSQL volume size. |

## App-specific

| Variable | Default | Purpose |
|---|---|---|
| `OWNSUITE_GRIST_STORAGE` | `5Gi` | Size of Grist's `/persist` document volume (Grist only). |
| `OWNSUITE_GRIST_ORG` | `ownsuite` | Grist single-tenant team-site name (`GRIST_SINGLE_ORG`). |
| `OWNSUITE_GRIST_SANDBOX` | `unsandboxed` | Grist formula sandbox flavor; set `gvisor` on a node configured for it. |

The mailbox has its own mail-flow variables — see [Mailbox](#mailbox-messages) below.

## Backups & restore

Off-site by construction (the destination must survive losing the server). Full guide,
including the encryption passphrase and credential overrides:
[Backups & restore](../operate/backups.md).

| Variable | Default | Purpose |
|---|---|---|
| `OWNSUITE_BACKUP_ENABLED` | `false` | Enable off-site backups (PostgreSQL PITR + object/volume copies). |
| `OWNSUITE_BACKUP_SCHEDULE` | `0 2 * * *` | CNPG base-backup cron (5-field). WAL archiving is continuous; empty = on-demand only. |
| `OWNSUITE_BACKUP_RETENTION` | `30d` | Barman recovery-window retention (PITR window). |
| `OWNSUITE_BACKUP_S3_TARGET` | `in-cluster` | `external` (production — a **different** account/provider than the primary) or `in-cluster` (CI/hermetic — a second in-cluster Garage). |
| `OWNSUITE_BACKUP_S3_ENDPOINT` | _(empty)_ | Off-site S3 endpoint (`external` target). |
| `OWNSUITE_BACKUP_S3_REGION` | `eu-west` | Off-site S3 region. |
| `OWNSUITE_BACKUP_S3_BUCKET` | `ownsuite-backups` | Off-site backups bucket. |
| `OWNSUITE_BACKUP_PG_ENCRYPTION` | _(empty)_ | Optional S3 server-side encryption for PG backups (e.g. `AES256`). Leave empty for stores without SSE. |
| `OWNSUITE_BACKUP_GARAGE_META_STORAGE` | `1Gi` | Off-site Garage metadata volume size (`in-cluster` target). |
| `OWNSUITE_BACKUP_GARAGE_DATA_STORAGE` | `10Gi` | Off-site Garage data volume size (`in-cluster` target). |
| `OWNSUITE_RESTORE` | `false` | Restore mode — set by `make restore` on a **clean** cluster; leave `false` otherwise. |
| `OWNSUITE_RESTORE_SERVER_NAME` | `<cluster>-restored` | Advanced: the Barman `serverName` the restored cluster archives under (must differ from the source). |

## Mailbox (messages)

Only relevant when `OWNSUITE_APP_MESSAGES=true`. The relay account and DKIM key are
**external secrets** — held in the environment, never written to `.env` (the installer
generates the DKIM key on first run and prints it to re-export). See
[Mailbox](../understand/messages.md).

| Variable | Default | Purpose |
|---|---|---|
| `OWNSUITE_MTA_RELAY_HOST` | `mail.infomaniak.com:587` | The SMTP relay outbound mail is sent through (`host:port`, STARTTLS). On Scaleway use TEM: `smtp.tem.scaleway.com:2587` (Instances block 25/465/587). See [Mailbox → Outbound](../understand/messages.md#outbound-scaleway-tem-or-an-external-relay). |
| `OWNSUITE_MTA_RELAY_USERNAME` | _(empty)_ | Relay account username — **secret**, export before sync. Until set, mta-out runs without an external relay (local delivery only). |
| `OWNSUITE_MTA_RELAY_PASSWORD` | _(empty)_ | Relay account password — **secret**. |
| `OWNSUITE_MTA_SPF_INCLUDE` | `spf.infomaniak.ch` | The relay's SPF include, published in the SPF TXT record (Scaleway TEM: `_spf.tem.scaleway.com`). |
| `OWNSUITE_MTA_DKIM_SELECTOR` | `ownsuite` | DKIM selector — must match the published `_domainkey` TXT record. |
| `OWNSUITE_MTA_DKIM_PRIVATE_KEY_B64` | generated by installer | Base64 DKIM private key — **secret**, export on every run (like the seed). |
| `OWNSUITE_MTA_DMARC_RUA` | _(empty)_ | Optional DMARC aggregate-report mailbox. |

## Meet (video conferencing)

Only relevant when `OWNSUITE_APP_MEET=true`. Meet needs LiveKit media ports open on the
server — the **only** non-HTTP ports besides the mailbox's port 25. These are opened by a
separate firewall flag (not an `OWNSUITE_*` env var), so enabling Meet is two switches:
turn the app on **and** open the ports. See [Meet](../understand/meet.md) and
[ADR-039](../understand/decisions.md#adr-039-meet-media-ports-single-udp-mux-tcp-fallback).

| Setting | Where | Purpose |
|---|---|---|
| `OWNSUITE_APP_MEET` | `.env` / environment | Deploy Meet + LiveKit + Egress. |
| `OWNSUITE_MEET_S3_BUCKET` | `.env` / environment | Room-recordings bucket (default `meet-recordings`). |
| `enable_meet` | Terraform `terraform.tfvars` | Open `7881/tcp` + `7882/udp` in the cloud security group. |
| `enable_meet` | Ansible `group_vars/all.yml` | Open `7881/tcp` + `7882/udp` in the host UFW. |

## Secrets

Every credential is **derived** from `OWNSUITE_SECRET_SEED`
(`sha256("<seed>:<id>")` truncated), so nothing secret is committed and a restore needs
only the seed. The seed is read from the environment at sync time and **never** written to
`.env` or the cluster.

```bash
export OWNSUITE_SECRET_SEED="$(openssl rand -hex 24)"   # required
```

!!! danger "Protect the seed"
    Losing it means rotating every credential; leaking it leaks them all. Store it in a
    password manager.

A few credentials are **external input** that cannot be derived — the external S3 keys,
a real off-site backup account, and the mailbox relay account + DKIM key. Supply them by
exporting the matching variables before sync (read the same way as the seed, never written
to `.env`):

```bash
export OWNSUITE_S3_ACCESS_KEY=... OWNSUITE_S3_SECRET_KEY=...           # external S3 mode
export OWNSUITE_BACKUP_S3_ACCESS_KEY=... OWNSUITE_BACKUP_S3_SECRET_KEY=...   # off-site backup
export OWNSUITE_RCLONE_CRYPT_PASSWORD=...                             # backup encryption passphrase
```

(`garage` mode needs none of the primary `OWNSUITE_S3_*` keys — they are seed-derived
in-cluster.) These map to the `s3-access`/`s3-secret`, `backup-s3-access`/`backup-s3-secret`
and `rclone-crypt` secret ids; the `OWNSUITE_MTA_*` secret variables above work the same way. See
[Backups & restore → Credentials](../operate/backups.md#credentials) and
[Secrets (ADR-012)](../understand/decisions.md#adr-012-secrets-derived-from-a-single-secretseed-via-helm-templating).

!!! note "CI / test-only variables"
    `OWNSUITE_KC_*`, `OWNSUITE_E2E_*` and `OWNSUITE_K3S_IMAGE` exist only for the automated
    test harness (direct-access grants, a seeded test user, the k3d image). Operators never
    set them.
