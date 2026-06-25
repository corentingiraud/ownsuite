# Shared infrastructure (Helmfile)

Phase 1's deliverable: bring up the **shared infrastructure** on the K3s cluster from
Phase 0 with one command, and reach **Keycloak over HTTPS**.

> **Definition of done:** `helmfile sync` brings up all shared infra; Keycloak is
> reachable over HTTPS.

This is orchestrated with **Helmfile** (see
[ADR-001](../architecture/decisions.md#adr-001-k3s-helmfile-not-compose-or-raw-helm)). It
deploys, in dependency order:

| Order | Release | What | ADR |
|---|---|---|---|
| 1 | `cert-manager` + `issuers` | TLS certificates (Let's Encrypt / self-signed ClusterIssuers) | [ADR-013](../architecture/decisions.md#adr-013-tls-issuance-cert-manager-http-01-per-subdomain-wildcard-dns-01-deferred) |
| 2 | `cnpg-operator` | CloudNativePG operator (Postgres CRDs) | [ADR-004](../architecture/decisions.md#adr-004-cloudnativepg-valkey-leaving-bitnami) |
| 3 | `platform-configuration` | All derived secrets + the Keycloak realm ConfigMap | [ADR-012](../architecture/decisions.md#adr-012-secrets-derived-from-a-single-secretseed-via-helm-templating) |
| 4 | `postgres` | One CNPG `Cluster` + one `Database` per app | [ADR-004](../architecture/decisions.md#adr-004-cloudnativepg-valkey-leaving-bitnami) |
| 5 | `valkey` | Cache / broker | [ADR-004](../architecture/decisions.md#adr-004-cloudnativepg-valkey-leaving-bitnami) |
| 6 | `keycloak` | SSO over HTTPS — the Phase 1 DoD | [ADR-011](../architecture/decisions.md#adr-011-keycloak-via-the-codecentrickeycloakx-chart-not-the-operator) |

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
    postgres/                 #   CNPG Cluster + Database CRs
  tests/                      # k3d end-to-end DoD check
```

## Secrets — one seed, nothing committed

Every credential is **derived** from a single `secretSeed`
([ADR-012](../architecture/decisions.md#adr-012-secrets-derived-from-a-single-secretseed-via-helm-templating)):
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
| `OWNSUITE_TLS_ISSUER` | `selfsigned` | `letsencrypt-http01` in production |
| `OWNSUITE_ACME_EMAIL` | `admin@example.org` | ACME registration email |
| `OWNSUITE_OBJECT_STORAGE_MODE` | `external` | `external` (managed S3) or `garage` |
| `OWNSUITE_S3_ENDPOINT` | _(empty)_ | External S3 endpoint URL |
| `OWNSUITE_PG_STORAGE` | `10Gi` | Postgres volume size |

## Run it (interim manual flow)

!!! note "This becomes the `suite` CLI"
    Everything below is the Phase 1 manual path, documented lightly. The Phase 4
    installer and the `suite` CLI (Phase 5) will wrap these steps — config prompts
    and the SSH tunnel — so an admin won't run them by hand.

Everything runs from **your workstation** (clone the repo locally once; nothing to
install on the VPS beyond the bootstrap — [ADR-014](../architecture/decisions.md#adr-014-operator-control-plane-local-workstation-ssh-tunnel)).

```bash
# 1. Provision the VPS (Ansible, remote over SSH) — fetches ./kubeconfig
make bootstrap

# 2. Configure (copy the example, edit, load into the shell)
cp .env.example .env && $EDITOR .env
set -a && source .env && set +a

# 3. Open an SSH tunnel to the K8s API — keep it running in another terminal
make tunnel            # ssh -N -L 6443:127.0.0.1:6443 $OWNSUITE_VPS_SSH

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
  `ownsuite` namespace. Per-app namespaces and cross-namespace secret distribution arrive
  in Phase 2 (when the first app lands).
- **One database per app.** The `databases` list in the environment drives both the
  derived owner secret and the CNPG managed role + `Database` CR, so they always match.
  Phase 1 provisions only the `keycloak` database.
- **Pluggable object storage.** S3 credentials are always derived (the seam is ready), but
  no in-cluster storage is deployed by default — the production default is an external EU
  S3 endpoint ([ADR-003](../architecture/decisions.md#adr-003-pluggable-object-storage-garage-or-external-eu-s3)).
  Garage is wired but off until an app needs it.
- **No backups yet.** CNPG PITR to S3 and tested restore are Phase 3
  ([ADR-006](../architecture/decisions.md#adr-006-backups-and-tested-restore)).

## Tests

The Helmfile stack has its own layered checks
([ADR-010](../architecture/decisions.md#adr-010-testing-ci-strategy-a-layered-evolving-harness)):

```bash
make lint-helm       # helm lint + helmfile template + kubeconform (CRD-aware)
make test-platform   # full DoD on a throwaway k3d cluster (heavy)
```

`make lint-helm` runs on every change under `helmfile/` (`helmfile-ci.yml`).
`make test-platform` provisions a real K3s with **k3d**, runs `helmfile sync` with the
self-signed issuer, and asserts cert-manager / CNPG / Valkey / Keycloak are up and that
**Keycloak answers over HTTPS** — the machine-checked DoD. It is heavy, so it runs nightly
and on Helmfile changes (`helmfile-e2e.yml`), not on every PR.

!!! note "HTTPS in CI"
    CI uses the **self-signed** ClusterIssuer: there is no public DNS to satisfy an ACME
    challenge, but TLS termination through Traefik is still proven end to end. Real
    Let's Encrypt issuance happens in production with `OWNSUITE_TLS_ISSUER=letsencrypt-http01`.
