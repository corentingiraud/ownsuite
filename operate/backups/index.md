# Backups & tested restore

OwnSuite backs up everything that matters and — just as important — **proves it can restore it**. A backup you've never tested isn't really a backup. Copies are kept **off-site**: the destination has to survive losing the whole server, so it's never stored on the server itself.

## What is backed up

| State                  | How                                                                                                                      | Covers                                                                                                                                                                                               |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **PostgreSQL**         | CNPG **Barman Cloud Plugin** — continuous WAL archiving + base backups to off-site S3, with PITR.                        | Every app database (`keycloak`, `docs`, and any enabled app's database) — so **Keycloak realm + users** and each app's documents/metadata (Keycloak DR is PITR of its database, no separate export). |
| **Objects (media)**    | **rclone** `sync` of **every enabled app's media bucket** to the off-site store, client-side encrypted (rclone `crypt`). | Docs, Drive, Projects and Mailbox media/uploads — each bucket copied to its own encrypted off-site path. Required even with external S3 (accidental deletion, lock-in).                              |
| **App volumes (PVCs)** | **rclone** copy of each backed-up volume to the off-site store, encrypted the same way; restored on recovery.            | State that lives on a volume rather than S3 — today **Grist's documents** (`/persist`, its SQLite files). Reusable for any future PVC-backed app.                                                    |

## The off-site destination

Set `backup.target` in `suite.yaml`:

- **`external`** (production) — a managed S3 in a **different account/provider** than your primary storage. Set `backup.endpoint` / `backup.region` / `backup.bucket`. If it is not a different account, it is not off-site.
- **`in-cluster`** (CI / hermetic) — a **second in-cluster RustFS** (`rustfs-backup`) with its own volume and bucket, deployed automatically. Used by the e2e; not for production DR.

### Who owns the bucket: `backup.provision`

`backup.provision` decides whether the CLI/Terraform **provisions** the off-site bucket, independently of where it lives (`endpoint`/`region` describe the store regardless of owner):

- **`provision: true`** — Terraform owns the bucket. Default when a `provider` is set. You can now set `endpoint`/`region`/`bucket` alongside it (e.g. the `nl-ams` default) without turning provisioning off.
- **`provision: false`** — the bucket already exists elsewhere (a separate account/provider, the real-DR case in ADR-006); the CLI never touches it. Default when no `provider` is set.

Provisioned by `suite apply`

On Scaleway with `backup.provision: true` (the default when a provider is set), `suite apply` provisions the backup bucket for you (in `nl-ams` — off the `fr-par` primary) and **reuses the workload S3 key** (same project → not account-isolated, but it survives losing the server, which is what the restore drill tests). **Prod DR** wants a separate account/provider: set `backup.provision: false`, point `backup.endpoint` at that account's S3 and override the keys (below).

### Credentials

The off-site S3 credentials and the rclone encryption passphrase are **derived from `OWNSUITE_SECRET_SEED`** by default (so CI and self-controlled targets need no manual sync). For a real **external** off-site account, override them with that account's keys — secrets never go in `suite.yaml`, so export them (an exported value always wins over the derived one):

```
export OWNSUITE_BACKUP_S3_ACCESS_KEY=...       # the off-site account's key id
export OWNSUITE_BACKUP_S3_SECRET_KEY=...       # its secret
export OWNSUITE_RCLONE_CRYPT_PASSWORD=...      # optional passphrase override; keep it safe
```

The encryption passphrase and the seed are the only secrets you must keep: **losing them loses the ability to restore.** Store them in a password manager.

## Configuration

All knobs live under `backup:` in `suite.yaml` (defaults and details in the [configuration reference](https://corentingiraud.github.io/ownsuite/reference/configuration/#backups-restore)); run `suite apply` after changing them:

```
backup:
  enabled: true
  schedule: "0 2 * * *"        # CNPG base-backup cron; WAL archiving is continuous
  retention: 30d               # Barman recovery window (PITR)
  target: external
  provision: true              # CLI/Terraform owns the bucket (default with a provider); false = BYO store
  endpoint: https://s3.example-eu.com
  region: eu-west
  bucket: ownsuite-backups
```

(One advanced knob stays an export: `OWNSUITE_BACKUP_PG_ENCRYPTION` — optional S3 server-side encryption for the PostgreSQL backups, e.g. `AES256` on AWS.)

Enabling backups installs the [Barman Cloud Plugin](https://cloudnative-pg.io/plugin-barman-cloud/) into `cnpg-system` (pinned, vendored manifest) and attaches a WAL archiver + `ScheduledBackup` to the PostgreSQL cluster, plus the rclone object-copy CronJob (one pass over every enabled app's media bucket) and — when a PVC-backed app such as Grist is enabled — an rclone volume-copy CronJob per backed-up volume.

Encryption & retention

PostgreSQL backups rely on **TLS in transit** + the destination's **at-rest** protection (optional S3 SSE via `OWNSUITE_BACKUP_PG_ENCRYPTION`); **objects** are **client-side** encrypted by rclone. Retention is a Barman **recovery window** (PITR), not full GFS — GFS-style retention is best expressed with the off-site bucket's lifecycle rules.

## Take a backup on demand

```
suite backup   # an on-demand CNPG base backup + an immediate off-site object copy
```

It waits for both to complete — the "before I try something" verb. It is also the snapshot `suite apply` and `suite upgrade` take before any change. Scheduled backups run automatically from `backup.schedule` (PostgreSQL) and the rclone CronJob (objects). WAL archiving is continuous, so PITR is available between base backups.

## Restore (tested)

Restore rebuilds a **clean** instance from the off-site backups. On a cluster with **no prior data** (fresh PVCs) and the same `OWNSUITE_SECRET_SEED` + backup configuration:

```
suite restore
```

`suite restore` is the operator-facing path: it checks the seed and backup configuration are present, **refuses on a cluster that is not clean** (an existing database or bound PVCs would be clobbered — confirm explicitly, or pass `--yes`, to override), pins the TLS issuer from `suite.yaml` so the restore never downgrades certs to `selfsigned`, runs the restore, then verifies single sign-on and each enabled app answered. See the [CLI reference](https://corentingiraud.github.io/ownsuite/reference/cli/#suite-restore).

Everything comes from `suite.yaml` + the seed

Restore needs `OWNSUITE_SECRET_SEED` (use the exported value, or let it prompt you) and the backup configuration from `suite.yaml`. The TLS issuer is **pinned from `suite.yaml`** (`tls:`), so even a bare cluster restores straight to your real issuer — nothing to export.

`make restore` is the dev escape hatch

Under the hood, `suite restore` runs a Helmfile sync in restore mode; `make restore` runs that sync directly, **without the rails** — no clean-cluster check, no issuer pinning, no post-restore verification. Reach for it only when debugging the restore mechanism itself.

The restore-mode sync:

1. **PostgreSQL** bootstraps via CNPG **recovery** from the off-site `ObjectStore` (every backed-up database comes back, to the latest backup / PITR).
1. **Objects** are copied back from the off-site store into each app's primary bucket (rclone restore Job).
1. **Volumes** are copied back into each backed-up PVC (e.g. Grist's `/persist`) by the rclone volume restore Job, before the app reads them.
1. **Apps** come up against the restored databases, buckets and volumes.

## Tested every night

This isn't a backup you hope works. Every night (and whenever the deployment changes), CI runs the whole cycle on a throwaway cluster: it brings the stack up with backups on, creates a document and a file, backs them up, **destroys** the primary data (keeping only the off-site copy), runs `make restore`, and checks that the **document, the user account, and the file all came back**. If restore ever broke, the build would catch it before you ever needed it.
