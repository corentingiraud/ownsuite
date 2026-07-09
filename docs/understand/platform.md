# Under the hood

The shared foundation comes up with one command (`helmfile sync`), and when it's done your
login system (Keycloak) is reachable over HTTPS. Everything else builds on top of it. You
won't run these pieces by hand — `suite apply` does — but here's what's inside and the order
it comes up in.

| Order | Piece | What it provides |
|---|---|---|
| 1 | `cert-manager` + issuers | Automatic HTTPS certificates (Let's Encrypt, or self-signed for local) |
| 2 | `cnpg-operator` | Manages the PostgreSQL database |
| 3 | `barman-cloud-plugin` | Database backup/recovery (only when backups are on) |
| 4 | `platform-configuration` | Generates every password from your seed + the login config |
| 5 | `postgres` | The database — one per app |
| 6 | `valkey` | The shared cache |
| 7 | `garage` | Self-hosted file storage (only if you're not using external S3) |
| 8 | `garage-backup` | A separate off-site store for backups (test setups only) |
| 9 | `object-backup` | Copies files off-site on a schedule (when backups are on) |
| 10 | `keycloak` | The single sign-on everyone logs in through |
| 11 | `keycloak-config` | Keeps each app's login registration in sync |

After the foundation, the **apps** come up as further pieces, each enabled by its entry
under `apps:` in `suite.yaml`. The single app manifest — which apps exist, their options,
buckets and firewall needs — lives in `suite/manifest.py`; the CLI maps it onto the
helmfile toggles. The first app is **Docs** — see [Docs application](docs.md). Backups
(off-site, with a tested restore) are covered in [Backups & restore](../operate/backups.md).

## Layout

```text
suite.yaml                    # the ONE human-owned file (git-ignored; template: suite.yaml.example)
.suite-state.json             # machine state apply maintains (git-ignored, 0600) — never edit
suite/                        # the declarative CLI
  spec.py                     #   load/validate suite.yaml + assemble the env helmfile reads
  state.py                    #   the .suite-state.json machine state
  manifest.py                 #   the single app manifest: apps, options, buckets, firewall needs
  apply.py                    #   the reconcile pipeline behind `suite apply`
  backup.py, info.py, ...     #   the other verbs (init, plan, status, upgrade, restore, users, ...)
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

Nothing secret is committed: the human input is `suite.yaml`, the machine state is
`.suite-state.json`, and the environment carries the secret seed plus any external
credentials (S3 / backup / relay keys). A git-ignored **`.env`** in the repo root is
**auto-loaded at CLI startup**, so those exports persist between `suite` commands without
`source .env` — an already-exported variable still wins over the file.

## Secrets — one seed, nothing committed

Every credential is **derived** from a single `secretSeed`:
`deriveSecret = sha256sum("<seed>:<id>")` truncated. The seed is read from the environment
at sync time and never written to the repo or the cluster.

```bash
export OWNSUITE_SECRET_SEED="$(openssl rand -hex 24)"   # required
```

!!! danger "Protect the seed"
    `$OWNSUITE_SECRET_SEED` is the single high-value secret: it reproduces every
    credential. Store it in a password manager. Losing it means rotating everything;
    leaking it means leaking all derived secrets.

Everything else is plain configuration: underneath, helmfile reads `OWNSUITE_*` variables —
the domain, TLS issuer, object-storage mode, volume sizes, **which apps to enable**,
backups, and more. `suite apply` derives them from `suite.yaml` + the machine state; an
exported variable still wins (that's how CI injects knobs), except the `OWNSUITE_APP_*`
toggles, which always come from `suite.yaml`. The full schema, with defaults, is the
[Configuration reference](../reference/configuration.md); the backup/restore knobs have
their own guide in [Backups & restore](../operate/backups.md).

## Run it (manual fallback)

!!! tip "Operators: `suite apply` is the path"
    [`suite apply`](../get-started/install.md) reconciles every step below from
    `suite.yaml` — bootstrap, tunnel, DNS, issuer pinning, snapshot, health checks. The
    raw flow stays here for **development and debugging only**, and to show what apply
    does underneath.

Everything runs from **your workstation** (clone the repo locally once; nothing to
install on the server beyond the bootstrap).

```bash
# 1. Bootstrap the server (Ansible, remote over SSH) — normally apply's bootstrap phase
cd ansible && ansible-playbook bootstrap.yml && cd -

# 2. Export the configuration helmfile reads (apply derives these from suite.yaml)
export OWNSUITE_SECRET_SEED=...
export OWNSUITE_DOMAIN=assoc.example.org
export OWNSUITE_APP_DOCS=true OWNSUITE_APP_DRIVE=true     # the app set, by hand
export OWNSUITE_TLS_ISSUER=letsencrypt-http01             # pin the issuer (see below)
export KUBECONFIG="$PWD/ansible/kubeconfig"               # absolute — helmfile changes cwd

# 3. Open an SSH tunnel to the K8s API — keep it running in another terminal
make tunnel            # ssh -N -L 6443:127.0.0.1:6443 $OWNSUITE_SERVER_SSH

# 4. Deploy the shared infrastructure with raw helmfile
helmfile -f helmfile/helmfile.yaml.gotmpl diff    # preview
helmfile -f helmfile/helmfile.yaml.gotmpl sync    # apply
# debugging a single release: helmfile -f helmfile/helmfile.yaml.gotmpl -l name=<release> apply
```

!!! warning "Raw helmfile bypasses every rail"
    This path skips the pre-change snapshot, the health checks, the per-app rollback —
    and the **issuer pinning**: a hand-run sync without `OWNSUITE_TLS_ISSUER` exported
    defaults the issuer to `selfsigned` and silently reissues live certificates.
    `suite apply` pins the issuer from `suite.yaml`, which is why it's the operator path.

The sync reaches the cluster through `ansible/kubeconfig` (server `127.0.0.1:6443`)
over the tunnel, so the K8s API is never exposed (the firewall keeps only 22/80/443).
When it finishes, Keycloak answers at `https://auth.{domain}`:

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
  S3 endpoint. Garage is wired but off until an app needs it.
- **Off-site backups, tested restore.** Point-in-time database backups + an off-site file copy,
  with a CI-proven restore (off by default; enable with `backup.enabled: true` in `suite.yaml`)
  — see [Backups & restore](../operate/backups.md).
- **App switcher via Keycloak, not a per-app waffle.** Since everyone logs in through Keycloak and
  each app already has its own OIDC client, the launcher is Keycloak's own Account Console
  "Applications" page at `https://auth.{domain}/realms/ownsuite/account/` — it lists exactly the
  enabled apps (a disabled app is hidden, so no dead links) and links to each `https://<app>.{domain}`.
  No new service, no external dependency (ADR-044). La Gaufre, La Suite's in-header waffle, is not used:
  at the pinned image versions it is unconfigurable or build-time on most frontends and would pull a
  hardcoded gouv.fr app list.

## Tests

The Helmfile stack has its own layered checks, sized so every PR gets a real signal fast
while the heavy run stays off the PR path:

```bash
make lint-helm        # helm lint + helmfile template + kubeconform (CRD-aware)
make test-pvc-backup  # isolated PVC backup → wipe → restore on k3d (~3 min) — the PR gate
make test-app APP=docs # boot ONE app on its own k3d cluster + assert its boot DoD
make test-platform    # platform + `suite apply` + backup/restore, on a throwaway k3d cluster (heavy)
```

- `make lint-helm` runs on every change under `helmfile/` (`helmfile-ci.yml`), on PRs and on `main`.
- **PR gate (fast):** `make test-pvc-backup` runs the isolated backup → wipe → restore
  round-trip in ~3 min (`helmfile-e2e.yml`), and `apps-e2e.yml` boots whichever app a PR
  touches on its own cluster — so a change gets a real boot/restore signal pre-merge.
- **Full suite (heavy, off the PR path):** `make test-platform` provisions a real K3s with
  **k3d**, writes a throwaway `suite.yaml` into a temp dir (pointed at via
  `OWNSUITE_CONFIG`, so a developer's real file is never touched), brings the platform up
  through `suite apply --yes --no-tunnel` (self-signed issuer), provisions a
  user with `suite user`, seeds a media object, then runs a full **backup → destroy →
  restore** cycle and asserts all three storage classes survived — the **Keycloak user**
  (Postgres PITR), the **media object** (rclone object copy) and a **PVC document** (the
  reusable volume copy). It asserts **no application** — each app's boot is checked by the
  per-app e2e above. It runs nightly, on `main`, and on demand — not on PRs
  (`helmfile-e2e.yml`).

!!! note "HTTPS in CI"
    CI uses the **self-signed** ClusterIssuer: there is no public DNS to satisfy an ACME
    challenge, but TLS termination through Traefik is still proven end to end. Real
    Let's Encrypt issuance happens in production with `tls: prod` in `suite.yaml`.
