# Provision the server (Terraform)

Before the server can be bootstrapped, it has to exist. The Terraform layer in
[`terraform/`](https://github.com/corentingiraud/ownsuite/tree/main/terraform)
provisions the **infrastructure half** of an OwnSuite deployment:

- a Debian server with a public IP and a firewall,
- the object-storage buckets and S3 keys the apps and backups use.

It stops there. `suite apply`'s [bootstrap phase](bootstrap.md) (Ansible) then
turns the server into a single-node K3s cluster and deploys the apps. Terraform
is optional — bring your own Debian server by setting `server: {ssh: user@host}`
in `suite.yaml` and **omitting `provider`**: apply then skips this layer entirely
(it still bootstraps and deploys).

## How `suite apply` drives it

With `provider: scaleway` (or `infomaniak`) in `suite.yaml`, this layer is the
first phase of every `suite apply` — nothing to run separately. Export the
provider credentials, then apply:

```bash
export SCW_ACCESS_KEY="SCWXXXXXXXXXXXXXXXXX"   # Scaleway; Infomaniak uses clouds.yaml
export SCW_SECRET_KEY="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
suite apply
```

- The **first run prompts once** for the account-specific values (project ids, SSH
  key, server type) and writes them to `terraform.tfvars`.
- On **every run**, the values derived from `suite.yaml` are regenerated into
  `suite.auto.tfvars`: the bucket list and the firewall flags follow the enabled
  app set (add Meet or the Mailbox under `apps:` and the next apply opens their
  ports — no tfvars to edit).
- The outputs (SSH target, minted S3 keys, TEM relay account) land in the machine
  state file **`.suite-state.json`** and the Ansible inventory — nothing to copy
  by hand. Stash the printed secrets in your password manager; the state file is
  disposable.

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

### Use (manual equivalent)

`suite apply` runs the same thing from `terraform/environments/scaleway`; by hand:

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
| `type` | `PRO2-XXS` (2 vCPU / 8 GB) for a starting set like Docs + Drive; `PRO2-XS` for Mailbox. PRO2 has no local SSD, so `root_volume_type = "sbs_volume"` (the default). |
| `bucket_names` | One media bucket per enabled app in `external` mode — see [Object storage](#object-storage). |

### Watch out

- **The apps' S3 key expires.** Scaleway orgs cap API-key lifetime (~1 year); the
  module sets ~11 months and pins it. **Rotate the key and re-apply before it
  lapses**, then re-sync the in-cluster secret, or media/backups break.
- **Scaleway Debian logs in as `root`** (not `debian`). The `ssh_target` output is
  `root@<ip>`; the bootstrap hardens root afterwards.
- **Mailbox → open SMTP.** Enabling `messages:` in `suite.yaml` sets
  `enable_mailbox = true` on the next apply, opening inbound port 25 and registering
  the [TEM sending domain](#mailbox-scaleway-tem).

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

### Use (manual equivalent)

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

## Where the outputs go

`suite apply` reads the outputs itself and stores them in the machine state
(`.suite-state.json`): the SSH target, the S3 endpoint/region, and the minted
keys — the next phases (bootstrap, DNS, deploy) pick them up from there, and the
DNS step points your records at the server IP. Nothing lands in a dotfile you
have to source.

Running Terraform by hand (the dev path), wire them yourself:

```bash
terraform output ssh_target            # -> server.ssh / the Ansible inventory
terraform output public_ip             # point your DNS records here
export OWNSUITE_S3_ACCESS_KEY="$(terraform output -raw s3_access_key)"
export OWNSUITE_S3_SECRET_KEY="$(terraform output -raw s3_secret_key)"
```

The S3 **access/secret keys are external secrets** — they cannot be derived from
the seed, so they live in the machine state (or your environment; an exported
value always wins), never in `suite.yaml`.

## Tearing the server down

Deleting the server is **not** a `suite` verb — [`suite destroy`](../reference/cli.md#suite-destroy)
uninstalls the suite from the cluster but keeps the machine. To tear the
infrastructure itself down, run OpenTofu/Terraform directly:

```bash
cd terraform/environments/scaleway     # or infomaniak
tofu destroy                           # removes the server, firewall and buckets
```

!!! danger "This deletes data"
    Destroying the infrastructure deletes the server's volumes and — depending on
    the provider — the buckets and their contents. Take a [`suite backup`](../operate/backups.md)
    first; the off-site copy (a different account) is what survives this.

In `garage` mode the apps use in-cluster Garage with seed-derived keys, so you do
**not** need the S3 keys or endpoint — they are only useful for the off-site
backup store. In `external` mode with a `provider`, apply creates one bucket per
enabled app (`docs-media-storage`, `drive-media-storage`, …; Grist uses a PVC, no
bucket); bringing your own S3, pre-create them — see
[Configuration → Object storage](../reference/configuration.md#object-storage).

### Mailbox: Scaleway TEM { #mailbox-scaleway-tem }

With the Mailbox enabled on Scaleway, the module also registers the sending
domain in **Transactional Email (TEM)** and grants the workload key TEM send
rights. `suite apply` stores the relay account (username = your Project ID,
password = the workload key secret) in the machine state and prints the TEM
SPF/DKIM/DMARC records to publish so Scaleway validates the domain. Set the relay
host under the app in `suite.yaml`:

```yaml
apps:
  messages:
    relay_host: smtp.tem.scaleway.com:2587
    spf_include: _spf.tem.scaleway.com
```

Port **2587** (STARTTLS) — not 587: Scaleway Instances **block outbound 25/465/587
by default**, and TEM exposes `2587`/`2465` for exactly this. See
[Mailbox → Outbound](../understand/messages.md#outbound-scaleway-tem-or-an-external-relay).

!!! warning "Off-site backup must be a second account"
    The backup bucket (`backup.endpoint` / `backup.bucket` in `suite.yaml`) should
    live in a **different** account or provider than the primary (see
    [Backups & restore](../operate/backups.md)) — with `backup.endpoint` left
    empty on Scaleway, apply provisions an `nl-ams` bucket under the **same**
    account: fine for the restore drill, not real DR.

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
