# Shared infrastructure (Helmfile)

Bring up the **shared infrastructure** on the K3s cluster with one command, and reach
**Keycloak over HTTPS** — the foundation every app builds on.

> **Definition of done:** `helmfile sync` brings up all shared infra; Keycloak is
> reachable over HTTPS.

This is orchestrated with **Helmfile** (see
[ADR-001](decisions.md#adr-001-k3s-helmfile-not-compose-or-raw-helm)). It
deploys, in dependency order:

| Order | Release | What | ADR |
|---|---|---|---|
| 1 | `cert-manager` + `issuers` | TLS certificates (Let's Encrypt / self-signed ClusterIssuers) | [ADR-013](decisions.md#adr-013-tls-issuance-cert-manager-http-01-per-subdomain-wildcard-dns-01-deferred) |
| 2 | `cnpg-operator` | CloudNativePG operator (Postgres CRDs) | [ADR-004](decisions.md#adr-004-cloudnativepg-valkey-leaving-bitnami) |
| 3 | `barman-cloud-plugin` | CNPG backup/recovery plugin (only when `backup.enabled`) | [ADR-017](decisions.md#adr-017-backups-tested-restore-barman-cloud-plugin-rclone-off-site-by-design) |
| 4 | `platform-configuration` | All derived secrets + the Keycloak realm ConfigMap | [ADR-012](decisions.md#adr-012-secrets-derived-from-a-single-secretseed-via-helm-templating) |
| 5 | `postgres` | One CNPG `Cluster` + one `Database` per app (+ backup `ObjectStore`/`ScheduledBackup` when enabled) | [ADR-004](decisions.md#adr-004-cloudnativepg-valkey-leaving-bitnami) |
| 6 | `valkey` | Cache / broker | [ADR-004](decisions.md#adr-004-cloudnativepg-valkey-leaving-bitnami) |
| 7 | `garage` | In-cluster object store + bucket bootstrap (only in `garage` mode) | [ADR-015](decisions.md#adr-015-in-cluster-object-storage-garage-single-node-deterministic-key) |
| 8 | `garage-backup` | Off-site object store for backups (only when `backup.s3.target=in-cluster`) | [ADR-017](decisions.md#adr-017-backups-tested-restore-barman-cloud-plugin-rclone-off-site-by-design) |
| 9 | `object-backup` | rclone off-site media copy CronJob (+ restore Job, when `backup.enabled`) | [ADR-017](decisions.md#adr-017-backups-tested-restore-barman-cloud-plugin-rclone-off-site-by-design) |
| 10 | `keycloak` | SSO over HTTPS — the foundation's keystone | [ADR-011](decisions.md#adr-011-keycloak-via-the-codecentrickeycloakx-chart-not-the-operator) |
| 11 | `keycloak-config` | Idempotent `kcadm` OIDC-client upsert — realm convergence on every sync | [ADR-020](decisions.md#adr-020-keycloak-realm-convergence-idempotent-oidc-client-upsert) |

After the shared infrastructure, **apps** are deployed as further releases (each
gated on `apps.<name>.enabled`). The first is **Docs** — see
[Docs application](docs.md) and [ADR-016](decisions.md#adr-016-docs-impress-integration-one-namespace-traefik-ingress-oidc-split).
Backups (off-site, with a tested restore) are covered in [Backups & restore](../operate/backups.md).

## Layout

```text
helmfile/
  helmfile.yaml.gotmpl        # releases, needs ordering, enable/disable conditions
  versions/versions.yaml      # pinned chart + image versions (Renovate-tracked)
  environments/default.yaml.gotmpl  # one environment for v1: domain, seed, toggles
  values/*.gotmpl             # per-release values (rendered by Helmfile)
  charts/                     # local charts
    platform-configuration/   #   derives secrets, builds the Keycloak realm
    issuers/                  #   cert-manager ClusterIssuers
    postgres/                 #   CNPG Cluster + Database + backup ObjectStore/ScheduledBackup
    barman-cloud-plugin/      #   vendored CNPG backup/recovery plugin (ADR-017)
    garage/                   #   in-cluster object store (primary + off-site backup)
    object-backup/            #   rclone off-site media copy + restore (ADR-017)
  tests/                      # k3d end-to-end DoD check (incl. backup→restore cycle)
```

## Secrets — one seed, nothing committed

Every credential is **derived** from a single `secretSeed`
([ADR-012](decisions.md#adr-012-secrets-derived-from-a-single-secretseed-via-helm-templating)):
`deriveSecret = sha256sum("<seed>:<id>")` truncated. The seed is read from the environment
at sync time and never written to the repo or the cluster.

```bash
export OWNSUITE_SECRET_SEED="$(openssl rand -hex 24)"   # required
```

!!! danger "Protect the seed"
    `$OWNSUITE_SECRET_SEED` is the single high-value secret: it reproduces every
    credential. Store it in a password manager. Losing it means rotating everything;
    leaking it means leaking all derived secrets.

Other knobs are plain configuration via `OWNSUITE_*` variables (all optional, with
sensible defaults), e.g.:

| Variable | Default | Purpose |
|---|---|---|
| `OWNSUITE_DOMAIN` | `ownsuite.localhost` | Base domain; each app is `<name>.{domain}` |
| `OWNSUITE_TLS_ISSUER` | `selfsigned` | `letsencrypt-staging` / `letsencrypt-http01` for production — `make install` drives staging→prod |
| `OWNSUITE_ACME_EMAIL` | `admin@example.org` | ACME registration email |
| `OWNSUITE_ADMIN_EMAIL` | `admin@example.org` | Contact for app admin / superuser accounts |
| `OWNSUITE_OBJECT_STORAGE_MODE` | `external` | `external` (managed S3) or `garage` (in-cluster) |
| `OWNSUITE_S3_ENDPOINT` | _(empty)_ | External S3 endpoint URL (`external` mode) |
| `OWNSUITE_S3_BUCKET` | `docs-media-storage` | Bucket for app media (created by Garage in `garage` mode) |
| `OWNSUITE_GARAGE_META_STORAGE` | `1Gi` | Garage metadata volume size (`garage` mode) |
| `OWNSUITE_GARAGE_DATA_STORAGE` | `10Gi` | Garage data volume size (`garage` mode) |
| `OWNSUITE_PG_STORAGE` | `10Gi` | Postgres volume size |
| `OWNSUITE_BACKUP_ENABLED` | `false` | Enable off-site backups (see [Backups & restore](../operate/backups.md)) |
| `OWNSUITE_BACKUP_S3_TARGET` | `in-cluster` | `external` (prod) or `in-cluster` (CI) off-site destination |

The backup/restore knobs (`OWNSUITE_BACKUP_*`, `OWNSUITE_RESTORE`) are documented in full in
[Backups & restore](../operate/backups.md).

## Run it (manual fallback)

!!! tip "Prefer the guided installer"
    [`make install`](../get-started/install.md) now wraps every step below — config prompts, the SSH
    tunnel, the DNS records, propagation, and staging→production certificates
    ([ADR-018](decisions.md#adr-018-phase-4-guided-installer-suite-install)).
    The manual flow stays here as a fallback and to show what the installer does; the
    `suite` CLI also covers user provisioning.

Everything runs from **your workstation** (clone the repo locally once; nothing to
install on the server beyond the bootstrap — [ADR-014](decisions.md#adr-014-operator-control-plane-local-workstation-ssh-tunnel)).

```bash
# 1. Provision the server (Ansible, remote over SSH) — fetches ./kubeconfig
make bootstrap

# 2. Configure (copy the example, edit, load into the shell)
cp .env.example .env && $EDITOR .env
set -a && source .env && set +a

# 3. Open an SSH tunnel to the K8s API — keep it running in another terminal
make tunnel            # ssh -N -L 6443:127.0.0.1:6443 $OWNSUITE_SERVER_SSH

# 4. Deploy the shared infrastructure
make diff              # preview
make sync              # apply
```

`make sync` uses `./kubeconfig` (server `127.0.0.1:6443`) through the tunnel, so the
K8s API is never exposed (the firewall keeps only 22/80/443). When it finishes,
Keycloak answers at `https://auth.{domain}`:

```bash
curl -s https://auth.assoc.example.org/realms/ownsuite/.well-known/openid-configuration
```

## Design notes (v1)

- **One workloads namespace.** cert-manager and CNPG run in their own namespaces
  (`cert-manager`, `cnpg-system`); all workloads and their secrets share a single
  `ownsuite` namespace. Per-app namespaces and cross-namespace secret distribution are not
  used — a single node keeps one workloads namespace.
- **One database per app.** The `databases` list in the environment drives both the
  derived owner secret and the CNPG managed role + `Database` CR, so they always match.
  The shared infrastructure alone provisions only the `keycloak` database; each enabled app
  adds its own.
- **Pluggable object storage.** S3 credentials are always derived (the seam is ready), but
  no in-cluster storage is deployed by default — the production default is an external EU
  S3 endpoint ([ADR-003](decisions.md#adr-003-pluggable-object-storage-garage-or-external-eu-s3)).
  Garage is wired but off until an app needs it.
- **Off-site backups, tested restore.** CNPG PITR + an off-site object copy, with a
  CI-proven restore (off by default; enable with `OWNSUITE_BACKUP_ENABLED`)
  — see [Backups & restore](../operate/backups.md),
  [ADR-006](decisions.md#adr-006-backups-and-tested-restore) and
  [ADR-017](decisions.md#adr-017-backups-tested-restore-barman-cloud-plugin-rclone-off-site-by-design).

## Tests

The Helmfile stack has its own layered checks
([ADR-010](decisions.md#adr-010-testing-ci-strategy-a-layered-evolving-harness)):

```bash
make lint-helm       # helm lint + helmfile template + kubeconform (CRD-aware)
make test-platform   # full DoD on a throwaway k3d cluster (heavy)
```

`make lint-helm` runs on every change under `helmfile/` (`helmfile-ci.yml`).
`make test-platform` provisions a real K3s with **k3d**, runs `helmfile sync` with the
self-signed issuer, asserts cert-manager / CNPG / Valkey / Keycloak / Docs are up (incl. the
SSO document DoD), then runs a full **backup → destroy → restore** cycle and asserts the
document, the Keycloak user and the media object survived (see
[Backups & restore](../operate/backups.md)). It is heavy, so it runs nightly and on Helmfile changes
(`helmfile-e2e.yml`), not on every PR.

!!! note "HTTPS in CI"
    CI uses the **self-signed** ClusterIssuer: there is no public DNS to satisfy an ACME
    challenge, but TLS termination through Traefik is still proven end to end. Real
    Let's Encrypt issuance happens in production with `OWNSUITE_TLS_ISSUER=letsencrypt-http01`.
