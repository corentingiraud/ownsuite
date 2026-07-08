# Configuration reference

OwnSuite is configured through **one human-owned file: `suite.yaml`** (ADR-042). It
describes the suite you want — provider, domain, TLS, backups, and which apps to run —
and `suite apply` reconciles reality to it. `suite init` writes it for you; a commented
template ships as
[`suite.yaml.example`](https://github.com/corentingiraud/ownsuite/blob/main/suite.yaml.example).

```yaml
provider: scaleway            # scaleway | omit = bring-your-own server
domain: assoc.example.org
admin_email: admin@assoc.example.org
tls: prod                     # selfsigned | staging | prod

object_storage: {mode: external}

backup:
  enabled: true
  target: external            # external (prod) | in-cluster (CI)

apps:                         # presence = enabled (ADR-035: everything off by default)
  docs: {}
  drive: {}
  tchap: {s3_bucket: tchap-media}
```

Two other places hold state — neither is ever edited by hand:

- **`.suite-state.json`** (git-ignored, `0600`) — the machine state `suite apply`
  maintains: the provisioned SSH target, provider-minted credentials (S3 keys, relay
  account, DKIM key), and change-detection inputs.
- **The environment** — the secret seed (see [Secrets](#secrets)), plus optional
  `OWNSUITE_*` overrides for CI and advanced knobs (see
  [Advanced: environment overrides](#advanced-environment-overrides)).

Anything `suite.yaml` omits keeps its documented default below.

## Top-level keys

| Key | Default | Purpose |
|---|---|---|
| `provider` | _(unset = bring-your-own)_ | `scaleway` — the only provisioning provider (ADR-038). When set, `suite apply` provisions the server, buckets and firewall with Terraform. |
| `domain` | _(required)_ | Base domain. Each component is exposed at `<name>.<domain>` (e.g. `auth.<domain>`, `docs.<domain>`). |
| `admin_email` | `admin@<domain>` | Contact address for app admin accounts and ACME registration. |
| `tls` | _(required)_ | `prod` (Let's Encrypt, staging→production ladder on first issuance — ADR-019), `staging` (untrusted leaf, high rate limits), or `selfsigned` (CI/local; skips the DNS step). |
| `server.ssh` | _(from provisioning)_ | `user@host` of a bring-your-own Debian server. With a `provider`, provisioning stores the target in the machine state instead. |

## Object storage

Pluggable (ADR-003): `external` (a managed EU S3 — files live off the box) or `garage`
(an in-cluster single-node store, deployed and bootstrapped for you). With a `provider`
in external mode, `suite apply` creates the buckets for your enabled apps; in `garage`
mode Garage creates them in-cluster.

!!! tip "`external` needs a CORS-capable S3"
    `external` mode needs an S3 endpoint that can serve **CORS** for Drive's browser
    uploads. **Scaleway** (recommended) and other CORS-capable RGW providers (AWS, OVH)
    support it. On an endpoint that can't (e.g. some OpenStack Swift `s3api` layers), use
    `garage` instead — it proxies media same-origin.

| Key | Default | Purpose |
|---|---|---|
| `object_storage.mode` | `external` | `external` (managed S3) or `garage` (in-cluster). |
| `object_storage.endpoint` | _(from provisioning)_ | External S3 endpoint URL. |
| `object_storage.region` | `eu-west` | S3 region (Scaleway: `fr-par`). |

## Backups & restore

Off-site by construction (the destination must survive losing the server). `suite apply`
and `suite upgrade` snapshot before every change; `suite backup` takes one on demand.
Full guide: [Backups & restore](../operate/backups.md).

| Key | Default | Purpose |
|---|---|---|
| `backup.enabled` | `false` | Off-site backups (PostgreSQL PITR + object/volume copies). |
| `backup.schedule` | `0 2 * * *` | CNPG base-backup cron (5-field). WAL archiving is continuous. |
| `backup.retention` | `30d` | Barman recovery-window retention (PITR window). |
| `backup.target` | `in-cluster` | `external` (production — a **different** account/provider than the primary) or `in-cluster` (CI/hermetic). |
| `backup.provision` | _(true if `provider` set)_ | Whether the CLI/Terraform **provisions** the off-site bucket. `true` (Scaleway default) mints a bucket in `nl-ams` under the *same* account — fine for the restore drill, not a substitute for a separate account. `false` = **bring your own** store, already existing elsewhere (real DR, ADR-006); the CLI never touches it. Decoupled from `endpoint` (issue #86), so you can set the endpoint either way. |
| `backup.endpoint` | _(empty)_ | Off-site S3 endpoint. Valid with any `provision` value — describes *where* the store lives, not who owns it. When provisioned on Scaleway and left empty, apply derives it from `region`. |
| `backup.region` | `eu-west` | Off-site S3 region. |
| `backup.bucket` | `ownsuite-backups` | Off-site backups bucket. |

## Database

| Key | Default | Purpose |
|---|---|---|
| `postgres.storage` | `10Gi` | PostgreSQL volume size. |

## Choosing which apps to deploy

**No app is deployed by default** (ADR-035). An app is enabled by its **presence** under
`apps:` — `docs: {}` is a complete entry. Removing the line and running `suite apply`
uninstalls the app; **its database, volumes and buckets are kept**, so re-adding the
line brings it back with its data.

```yaml
apps:
  docs: {}
  tchap: {}       # add a line, `suite apply`, done -> https://tchap.<domain>/
```

Each app reaches every user you've added through the same single sign-on — see
[Users](../operate/users.md). For how much server each app needs, see
[Sizing](../operate/sizing.md).

### Per-app options

Options go under the app's key; every one is optional.

| App | Option | Default | Purpose |
|---|---|---|---|
| [Docs](../understand/docs.md) | `s3_bucket` | `docs-media-storage` | Media/attachments bucket. |
| [Drive](../understand/drive.md) | `s3_bucket` | `drive-media-storage` | Files bucket. |
| [Grist](../understand/grist.md) | `storage` | `5Gi` | Size of the `/persist` document volume. |
| | `org` | `ownsuite` | Single-tenant team-site name (`GRIST_SINGLE_ORG`). |
| | `sandbox` | `unsandboxed` | Formula sandbox flavor; `gvisor` on a node configured for it. |
| [Projects](../understand/projects.md) | `s3_bucket` | `projects-media-storage` | Uploads bucket. |
| [Mailbox](../understand/messages.md) | `s3_bucket` | `messages-media-storage` | Message blobs/attachments bucket. |
| | `relay_host` | `smtp.tem.scaleway.com:2587` | SMTP relay (`host:port`, STARTTLS). Default is Scaleway TEM; any authenticated relay works. |
| | `spf_include` | `_spf.tem.scaleway.com` | The relay's SPF include for the SPF TXT record. |
| | `dkim_selector` | `ownsuite` | DKIM selector — must match the published `_domainkey` TXT record. |
| | `dmarc_rua` | _(empty)_ | Optional DMARC aggregate-report mailbox. |
| [Meet](../understand/meet.md) | `s3_bucket` | `meet-recordings` | Room-recordings bucket. |
| | `turn` | `false` | TURN on `5349/tcp` for clients behind strict firewalls. |
| [Tchap](../understand/tchap.md) | `s3_bucket` | `tchap-media` | Synapse media bucket (copied off-site, unlike Meet recordings). |

**Firewall ports follow the app set automatically.** Enabling Meet opens its LiveKit
media ports (`7881/tcp` + `7882/udp`, plus `5349/tcp` with `turn: true` — ADR-039);
enabling the Mailbox opens inbound SMTP (`25/tcp`, ADR-027). `suite apply` sets both the
cloud security group (Terraform) and the host firewall (Ansible) — there is nothing to
edit by hand.

## Secrets

Every credential is **derived** from `OWNSUITE_SECRET_SEED`
(`sha256("<seed>:<id>")` truncated, ADR-012), so nothing secret is committed and a
restore needs only the seed. The seed lives **only in your environment and your password
manager** — never in `suite.yaml`, the machine state, or the cluster. A first
`suite apply` offers to generate it (shown once); later runs use the exported value or
prompt for it, and refuse a *wrong* seed instead of silently rotating every credential.

```bash
export OWNSUITE_SECRET_SEED=...        # generate once: openssl rand -hex 24
```

!!! danger "Protect the seed"
    Losing it means rotating every credential; leaking it leaks them all. Store it in a
    password manager.

A few credentials are **external input** that cannot be derived. When `suite apply`
provisions them (Scaleway S3 keys, the TEM relay account), they land in the machine
state automatically — also stash them in your password manager, the state file is
disposable. Bringing your own, export them:

```bash
export OWNSUITE_S3_ACCESS_KEY=... OWNSUITE_S3_SECRET_KEY=...                  # external S3 mode
export OWNSUITE_BACKUP_S3_ACCESS_KEY=... OWNSUITE_BACKUP_S3_SECRET_KEY=...    # own off-site account
export OWNSUITE_RCLONE_CRYPT_PASSWORD=...                                     # backup encryption passphrase
export OWNSUITE_MTA_RELAY_USERNAME=... OWNSUITE_MTA_RELAY_PASSWORD=...        # own SMTP relay account
```

(`garage` mode needs none of the primary S3 keys — they are seed-derived in-cluster.)

## Advanced: environment overrides

Underneath, the deployment layer still reads `OWNSUITE_*` environment variables;
`suite apply` derives them from `suite.yaml` + the machine state. **An exported variable
wins over the derived value** — that is how CI injects test knobs — with one deliberate
exception: the `OWNSUITE_APP_*` toggles always come from `suite.yaml` (the app set has
exactly one source).

A few advanced knobs have no `suite.yaml` key and are set by export only:

| Variable | Default | Purpose |
|---|---|---|
| `OWNSUITE_ACME_SERVER` / `OWNSUITE_ACME_STAGING_SERVER` | Let's Encrypt directories | Override the ACME directory URLs. |
| `OWNSUITE_EMAIL_FROM` | `no-reply@<domain>` | From/envelope address on transactional email (Meet links, share invitations, Keycloak emails). Must be an allowed sender on the relay. |
| `OWNSUITE_MTA_DKIM_PRIVATE_KEY_B64` | generated by apply, stored in the machine state | Base64 DKIM private key (mailbox). |
| `OWNSUITE_GARAGE_META_STORAGE` / `OWNSUITE_GARAGE_DATA_STORAGE` | `1Gi` / `10Gi` | Garage volume sizes (`garage` mode). |
| `OWNSUITE_BACKUP_GARAGE_META_STORAGE` / `OWNSUITE_BACKUP_GARAGE_DATA_STORAGE` | `1Gi` / `10Gi` | Off-site Garage volume sizes (`in-cluster` target). |
| `OWNSUITE_BACKUP_PG_ENCRYPTION` | _(empty)_ | Optional S3 server-side encryption for PG backups (e.g. `AES256`). |
| `OWNSUITE_RESTORE` | `false` | Restore mode — `suite restore` sets it; leave it alone. |
| `OWNSUITE_RESTORE_SERVER_NAME` | `<cluster>-restored` | Advanced: the Barman `serverName` the restored cluster archives under (must differ from the source). |

!!! note "Transactional email is optional"
    One relay account powers both the mailbox and the transactional email other apps
    send (Meet recording links, Docs/Drive invitations, Keycloak account emails). Until
    a relay account exists (provisioned into the state, or exported), transactional
    email is simply skipped and `mta-out` runs local-delivery only.

!!! note "CI / test-only variables"
    `OWNSUITE_KC_*`, `OWNSUITE_E2E_*`, `OWNSUITE_K3S_IMAGE` and `OWNSUITE_CONFIG` (an
    alternate `suite.yaml` path) exist for the automated test harness. Operators never
    set them.
