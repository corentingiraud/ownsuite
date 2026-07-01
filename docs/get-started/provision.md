# Provision the server (Terraform)

Before the server can be bootstrapped, it has to exist. The Terraform layer in
[`terraform/`](https://github.com/corentingiraud/ownsuite/tree/main/terraform)
provisions the **infrastructure half** of an OwnSuite deployment:

- a Debian server with a public IP and a firewall,
- the object-storage buckets and S3 keys the apps and backups use.

It stops there. [Prepare the server](bootstrap.md) (Ansible) then turns the
server into a single-node K3s cluster, and the [installer](install.md) deploys
the apps. Terraform is optional — if you already have a Debian server and an S3
bucket, skip straight to [Prepare the server](bootstrap.md).

## Guided (`suite provision`)

The quickest path is the CLI, which wraps everything below — it prompts for the
provider and the required `terraform.tfvars` values, runs `init` / `plan` /
`apply`, then wires the outputs into `.env` and the Ansible inventory
(`ansible/inventory/hosts.yml`), and prints the external secrets (S3 keys, TEM
relay) to export:

```bash
export SCW_ACCESS_KEY="SCWXXXXXXXXXXXXXXXXX"   # Scaleway; Infomaniak uses clouds.yaml
export SCW_SECRET_KEY="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
suite provision                # or: suite provision --provider scaleway --yes
```

`suite install` also offers to run this for you when no server is configured yet.
It needs `terraform` **or** `tofu` on PATH. The rest of this page is the manual
equivalent (and the reference for every tfvars value).

Two providers ship, both exposing the **same output contract** so the rest of the
flow is identical:

| Provider | Status | Object storage | Outbound mail |
|---|---|---|---|
| **[Scaleway](#scaleway-recommended)** | **recommended** | native S3 (CORS-capable → `external` mode) | native [TEM](#mailbox-scaleway-tem) relay |
| **[Infomaniak](#infomaniak-alternative)** | alternative | Swift + s3api (no CORS → use `garage`) | external EU SMTP relay |

```
terraform/
  modules/
    scaleway/          # native: server + Object Storage + IAM key (+ TEM)
    infomaniak/        # OpenStack: server + Swift/S3 buckets + S3 keys
  environments/
    scaleway/          # provider config + your values; run terraform here
    infomaniak/
```

## Scaleway (recommended)

Scaleway is the recommended host: its **Object Storage is fully S3-compatible and
supports bucket CORS**, so `external` mode works for everything including Drive's
browser-direct uploads; and **[Transactional Email (TEM)](#mailbox-scaleway-tem)**
gives the optional Mailbox a native outbound relay. Both are absent on Infomaniak.
See [ADR-038](../understand/decisions.md#adr-038-hosting-provider-scaleway-recommended-infomaniak-alternative).

### Prerequisites

- A Scaleway [Project](https://console.scaleway.com/) (note its **Project ID**
  and **Organization ID** — IAM is organization-scoped).
- [Terraform](https://developer.hashicorp.com/terraform) **or**
  [OpenTofu](https://opentofu.org/) ≥ 1.9.
- An **IAM API key** whose principal has **both** product rights
  (`InstancesFullAccess` + `ObjectStorageFullAccess`) **and `IAMManager`**, all
  scoped to the **organization**. Terraform mints the apps' S3 key via an IAM
  application/policy, which a product-only key cannot do (it 403s *"insufficient
  permissions: write application"*). Export it, never commit it:

    ```bash
    export SCW_ACCESS_KEY="SCWXXXXXXXXXXXXXXXXX"
    export SCW_SECRET_KEY="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
    ```

### Use

```bash
cd terraform/environments/scaleway
cp terraform.tfvars.example terraform.tfvars   # fill in project/org id, name, SSH key, buckets
terraform init
terraform plan
terraform apply
```

Confirm these account-specific values before you apply:

| Variable | Notes |
|---|---|
| `project_id` / `organization_id` | `scw config get default-project-id` / `default-organization-id`. |
| `image` | `scw marketplace image list` — `debian_bookworm` (12) is confirmed; check the label before setting Debian 13. |
| `type` | `PRO2-XXS` (2 vCPU / 8 GB) for the core apps; `PRO2-XS` for Mailbox. PRO2 has no local SSD, so `root_volume_type = "sbs_volume"` (the default). |
| `bucket_names` | One media bucket per enabled app in `external` mode — see [Object storage](#object-storage). |

### Watch out

- **The apps' S3 key expires.** Scaleway orgs cap API-key lifetime (~1 year); the
  module sets ~11 months and pins it. **Rotate the key and re-apply before it
  lapses**, then re-sync the in-cluster secret, or media/backups break.
- **Scaleway Debian logs in as `root`** (not `debian`). The `ssh_target` output is
  `root@<ip>`; the bootstrap hardens root afterwards.
- **Mailbox → open SMTP.** Set `enable_mailbox = true` to open inbound port 25 and
  register the [TEM sending domain](#mailbox-scaleway-tem).

## Infomaniak (alternative)

Infomaniak Public Cloud (OpenStack) is a cheaper EU/CH alternative, with one
important constraint: its object storage is **Swift with an `s3api`
compatibility layer that does not implement bucket CORS**, so you **must** run
object storage in [`garage`](#object-storage) mode there. It also has no native
transactional-email product — the Mailbox needs an [external SMTP
relay](../understand/messages.md#outbound-scaleway-tem-or-an-external-relay).

### Prerequisites

- An Infomaniak Public Cloud project.
- Terraform / OpenTofu ≥ 1.9.
- An **unrestricted application credential**, referenced from `clouds.yaml` so no
  secrets land in the repo. It **must** be unrestricted: Terraform mints the S3
  key via `openstack_identity_ec2_credential_v3`, and a restricted credential
  cannot create further credentials. In Horizon: *Identity → Application
  Credentials → Create*, tick **Unrestricted**.

    ```yaml
    # ~/.config/openstack/clouds.yaml
    clouds:
      ownsuite:
        auth_type: v3applicationcredential
        auth:
          auth_url: https://api.pub1.infomaniak.cloud/identity
          application_credential_id: "..."
          application_credential_secret: "..."
        region_name: dc3-a
        interface: public
        identity_api_version: 3
    ```

### Use

```bash
cd terraform/environments/infomaniak
cp terraform.tfvars.example terraform.tfvars   # fill in (auth via clouds.yaml)
terraform init && terraform plan && terraform apply
```

Confirm these against your project — a mismatch fails the apply:

| Variable | Find it with |
|---|---|
| `image_name` | `openstack image list` — copy the name **exactly**; Infomaniak's is `Debian 13 trixie` (lowercase, no minor), not `Debian 13.0 Trixie`. |
| `external_network_name` | `openstack network list --external` |
| `flavor_name` | `openstack flavor list` — see [Server sizing](../operate/sizing.md) |

In `garage` mode Terraform creates **no** buckets (`bucket_names = []`, the
default); it only provisions the server and mints S3 keys (useful for the off-site
backup store). Note the S3 region is `us-east-1` (a compatibility value; data is
in CH), and buckets — if you do create any — are made through the **S3 API**, not
as Swift containers (separate namespaces on Infomaniak).

## Object storage

OwnSuite's object storage is pluggable
([ADR-003](../understand/decisions.md#adr-003-pluggable-object-storage-garage-or-external-eu-s3)):

- **`external`** (recommended, and the default) — a managed S3 bucket per enabled
  app. Drive uploads/downloads files **straight from the browser** via presigned
  URLs, which needs the S3 endpoint to serve **CORS**. **Scaleway Object Storage
  supports CORS** (the module sets a bucket CORS rule for `https://*.<domain>`), so
  `external` works end-to-end. It also works on any CORS-capable RGW (AWS S3, OVH).
- **`garage`** — an in-cluster single-node store. Media buckets live in the
  cluster, downloads are proxied same-origin through the authenticated `/media/`
  path, and presigned uploads are proxied by Traefik — **no cross-origin request,
  so no CORS needed**. Use it on **Infomaniak** (whose `s3api` layer returns
  `NotImplemented` for `PutBucketCors`,
  [OpenStack bug #2077629](https://bugs.launchpad.net/swift/+bug/2077629)), or
  anywhere you want full in-cluster sovereignty. It is also the mode the automated
  tests exercise.

The off-site **backup** store is unaffected either way: backups are written
server-side (CNPG / rclone), never from the browser, so they have no CORS
requirement.

## Wire the outputs into your config

```bash
terraform output ssh_target            # -> OWNSUITE_SERVER_SSH + ansible_host
terraform output public_ip             # point your DNS records here
terraform output -raw s3_access_key    # secret (the minted S3 access key)
terraform output -raw s3_secret_key    # secret (the minted S3 secret key)
```

The S3 **access/secret keys are external secrets** — they cannot be derived from
the seed, so they are not written to `.env`. In `external` mode, export them (like
the seed) before `make sync` / `suite install`, and set the endpoint/region/bucket
from `terraform output` (Scaleway endpoint is `https://s3.<region>.scw.cloud`,
region `fr-par`):

```bash
export OWNSUITE_S3_ACCESS_KEY="$(terraform output -raw s3_access_key)"
export OWNSUITE_S3_SECRET_KEY="$(terraform output -raw s3_secret_key)"
```

In `garage` mode the apps use in-cluster Garage with seed-derived keys, so you do
**not** need those lines or any `OWNSUITE_S3_*` endpoint/bucket — the keys are only
useful for the off-site backup store. Either way, pre-create one bucket per enabled
app in `external` mode (`docs-media-storage`, `drive-media-storage`,
`projects-media-storage`, `messages-media-storage`; Grist uses a PVC, no bucket) —
see [Configuration → Object storage](../reference/configuration.md#object-storage).

Point your DNS records (`OWNSUITE_DOMAIN`) at the `public_ip` output, then continue
with [Prepare the server](bootstrap.md).

### Mailbox: Scaleway TEM { #mailbox-scaleway-tem }

With `enable_mailbox = true` on Scaleway, the module also registers the sending
domain in **Transactional Email (TEM)** and grants the workload key TEM send
rights. Publish the SPF/DKIM/DMARC records from `terraform output tem_dns` so
Scaleway validates the domain, then wire the relay from the outputs:

```bash
export OWNSUITE_MTA_RELAY_USERNAME="$(terraform output -raw mta_relay_username)"  # your Project ID
export OWNSUITE_MTA_RELAY_PASSWORD="$(terraform output -raw mta_relay_password)"  # = the S3 secret key
export OWNSUITE_MTA_RELAY_HOST="smtp.tem.scaleway.com:2587"
```

Port **2587** (STARTTLS) — not 587: Scaleway Instances **block outbound 25/465/587
by default**, and TEM exposes `2587`/`2465` for exactly this. See
[Mailbox → Outbound](../understand/messages.md#outbound-scaleway-tem-or-an-external-relay).

!!! warning "Off-site backup must be a second account"
    The backup bucket (`OWNSUITE_BACKUP_S3_*`) must live in a **different** account
    or provider than the primary (see
    [Backups & restore](../operate/backups.md)). Use the commented second-module
    example in `environments/<provider>/main.tf` — do not reuse the primary bucket.

## Adding another cloud provider

The layout makes another provider an isolated change:

1. Create `modules/<provider>/` exposing the **same output contract** as the
   existing modules: `public_ip`, `ssh_target`, `s3_endpoint`, `s3_region`,
   `buckets`, `s3_access_key`, `s3_secret_key`.
2. Create `environments/<provider>/` with that provider's `provider {}` block and a
   `module "suite"` pointing at the new module.

No switch logic, no change to existing providers. The Scaleway ↔ OpenStack
resource mapping is in
[ADR-038](../understand/decisions.md#adr-038-hosting-provider-scaleway-recommended-infomaniak-alternative).

## Validate

```bash
terraform fmt -check -recursive
terraform -chdir=environments/scaleway init -backend=false
terraform -chdir=environments/scaleway validate
```

State and `*.tfvars` are gitignored — keep secrets out of the repo.
