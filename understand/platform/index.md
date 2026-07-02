# Under the hood

The shared foundation comes up with one command (`helmfile sync`), and when it's done your login system (Keycloak) is reachable over HTTPS. Everything else builds on top of it. You won't run these pieces by hand — the installer does — but here's what's inside and the order it comes up in.

| Order | Piece                    | What it provides                                                       |
| ----- | ------------------------ | ---------------------------------------------------------------------- |
| 1     | `cert-manager` + issuers | Automatic HTTPS certificates (Let's Encrypt, or self-signed for local) |
| 2     | `cnpg-operator`          | Manages the PostgreSQL database                                        |
| 3     | `barman-cloud-plugin`    | Database backup/recovery (only when backups are on)                    |
| 4     | `platform-configuration` | Generates every password from your seed + the login config             |
| 5     | `postgres`               | The database — one per app                                             |
| 6     | `valkey`                 | The shared cache                                                       |
| 7     | `garage`                 | Self-hosted file storage (only if you're not using external S3)        |
| 8     | `garage-backup`          | A separate off-site store for backups (test setups only)               |
| 9     | `object-backup`          | Copies files off-site on a schedule (when backups are on)              |
| 10    | `keycloak`               | The single sign-on everyone logs in through                            |
| 11    | `keycloak-config`        | Keeps each app's login registration in sync                            |

After the foundation, the **apps** come up as further pieces, each turned on or off by a simple flag. The first is **Docs** — see [Docs application](https://corentingiraud.github.io/ownsuite/understand/docs/index.md). Backups (off-site, with a tested restore) are covered in [Backups & restore](https://corentingiraud.github.io/ownsuite/operate/backups/index.md).

## Layout

```
helmfile/
  helmfile.yaml.gotmpl        # releases, needs ordering, enable/disable conditions
  versions/versions.yaml      # pinned chart + image versions (Renovate-tracked)
  environments/default.yaml.gotmpl  # one environment for v1: domain, seed, toggles
  values/*.gotmpl             # per-release values (rendered by Helmfile)
  charts/                     # local charts
    platform-configuration/   #   derives secrets, builds the Keycloak realm
    issuers/                  #   cert-manager ClusterIssuers
    postgres/                 #   CNPG Cluster + Database + backup ObjectStore/ScheduledBackup
    barman-cloud-plugin/      #   vendored CNPG backup/recovery plugin
    garage/                   #   in-cluster object store (primary + off-site backup)
    object-backup/            #   rclone off-site media copy + restore
    pvc-backup/               #   rclone off-site volume copy + restore (reusable)
  tests/                      # end-to-end checks (platform, per-app, PVC backup/restore)
```

## Secrets — one seed, nothing committed

Every credential is **derived** from a single `secretSeed`: `deriveSecret = sha256sum("<seed>:<id>")` truncated. The seed is read from the environment at sync time and never written to the repo or the cluster.

```
export OWNSUITE_SECRET_SEED="$(openssl rand -hex 24)"   # required
```

Protect the seed

`$OWNSUITE_SECRET_SEED` is the single high-value secret: it reproduces every credential. Store it in a password manager. Losing it means rotating everything; leaking it means leaking all derived secrets.

Everything else is plain configuration via `OWNSUITE_*` variables — the domain, TLS issuer, object-storage mode, volume sizes, **which apps to enable**, backups, and more — all optional with sensible defaults. The full list, with defaults, is the [Configuration reference](https://corentingiraud.github.io/ownsuite/reference/configuration/index.md); the backup/restore knobs have their own guide in [Backups & restore](https://corentingiraud.github.io/ownsuite/operate/backups/index.md).

## Run it (manual fallback)

Prefer the guided installer

[`make install`](https://corentingiraud.github.io/ownsuite/get-started/install/index.md) now wraps every step below — config prompts, the SSH tunnel, the DNS records, propagation, and staging→production certificates. The manual flow stays here as a fallback and to show what the installer does; the `suite` CLI also covers user provisioning.

Everything runs from **your workstation** (clone the repo locally once; nothing to install on the server beyond the bootstrap).

```
# 1. Provision the server (Ansible, remote over SSH) — fetches ./kubeconfig
python3 -m suite bootstrap

# 2. Configure (copy the example, edit, load into the shell)
cp .env.example .env && $EDITOR .env
set -a && source .env && set +a

# 3. Open an SSH tunnel to the K8s API — keep it running in another terminal
make tunnel            # ssh -N -L 6443:127.0.0.1:6443 $OWNSUITE_SERVER_SSH

# 4. Deploy the shared infrastructure
make diff              # preview
make sync              # apply
```

`make sync` uses `./kubeconfig` (server `127.0.0.1:6443`) through the tunnel, so the K8s API is never exposed (the firewall keeps only 22/80/443). When it finishes, Keycloak answers at `https://auth.{domain}`:

```
curl -s https://auth.assoc.example.org/realms/ownsuite/.well-known/openid-configuration
```

## Design notes (v1)

- **One workloads namespace.** cert-manager and CNPG run in their own namespaces (`cert-manager`, `cnpg-system`); all workloads and their secrets share a single `ownsuite` namespace. Per-app namespaces and cross-namespace secret distribution are not used — a single node keeps one workloads namespace.
- **One database per app.** The `databases` list in the environment drives both the derived owner secret and the CNPG managed role + `Database` CR, so they always match. The shared infrastructure alone provisions only the `keycloak` database; each enabled app adds its own.
- **Pluggable object storage.** S3 credentials are always derived (the seam is ready), but no in-cluster storage is deployed by default — the production default is an external EU S3 endpoint. Garage is wired but off until an app needs it.
- **Off-site backups, tested restore.** Point-in-time database backups + an off-site file copy, with a CI-proven restore (off by default; enable with `OWNSUITE_BACKUP_ENABLED`) — see [Backups & restore](https://corentingiraud.github.io/ownsuite/operate/backups/index.md).

## Tests

The Helmfile stack has its own layered checks, sized so every PR gets a real signal fast while the heavy run stays off the PR path:

```
make lint-helm        # helm lint + helmfile template + kubeconform (CRD-aware)
make test-pvc-backup  # isolated PVC backup → wipe → restore on k3d (~3 min) — the PR gate
make test-app APP=docs # boot ONE app on its own k3d cluster + assert its boot DoD
make test-platform    # platform + installer + backup/restore, on a throwaway k3d cluster (heavy)
```

- `make lint-helm` runs on every change under `helmfile/` (`helmfile-ci.yml`), on PRs and on `main`.
- **PR gate (fast):** `make test-pvc-backup` runs the isolated backup → wipe → restore round-trip in ~3 min (`helmfile-e2e.yml`), and `apps-e2e.yml` boots whichever app a PR touches on its own cluster — so a change gets a real boot/restore signal pre-merge.
- **Full suite (heavy, off the PR path):** `make test-platform` provisions a real K3s with **k3d**, brings the platform up through `suite install` (self-signed issuer), provisions a user with `suite user`, seeds a media object, then runs a full **backup → destroy → restore** cycle and asserts all three storage classes survived — the **Keycloak user** (Postgres PITR), the **media object** (rclone object copy) and a **PVC document** (the reusable volume copy). It asserts **no application** — each app's boot is checked by the per-app e2e above. It runs nightly, on `main`, and on demand — not on PRs (`helmfile-e2e.yml`).

HTTPS in CI

CI uses the **self-signed** ClusterIssuer: there is no public DNS to satisfy an ACME challenge, but TLS termination through Traefik is still proven end to end. Real Let's Encrypt issuance happens in production with `OWNSUITE_TLS_ISSUER=letsencrypt-http01`.
