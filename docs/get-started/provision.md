# Provisioning (the Terraform phase of `suite apply`)

Before a server can be bootstrapped, it has to exist. When `suite.yaml` sets a
`provider:`, the **first phase of every [`suite apply`](install.md)** is a Terraform
layer ([`terraform/`](https://github.com/corentingiraud/ownsuite/tree/main/terraform))
that provisions the **infrastructure half** of the deployment:

- a Debian server with a public IP and a firewall,
- the object-storage buckets and S3 keys the apps and backups use,
- on Scaleway, the [Transactional Email](#mailbox-scaleway-tem) sending domain when the
  Mailbox is enabled.

This is **not a command you run** — it is what `suite apply` does first, then hands the
server to the [bootstrap phase](bootstrap.md). It stops at the infrastructure; DNS records
are emitted for you to add (the [DNS phase](install.md)), never created here.

!!! tip "Scaleway is the documented provider"
    OwnSuite is provisioned and tested on **Scaleway**. Its Object Storage is CORS-capable
    (so `external` object storage works end-to-end, including Drive's browser uploads) and
    its native **Transactional Email** gives the Mailbox a working relay — see
    [ADR-038](../understand/decisions.md#adr-038-hosting-provider-scaleway).
    Don't want to provision at all? [Bring your own server](#bring-your-own-server).

## How `suite apply` drives it

With `provider: scaleway` in `suite.yaml`, export the provider credentials once, then
apply — provisioning runs as the first phase:

```bash
export SCW_ACCESS_KEY="SCWXXXXXXXXXXXXXXXXX"
export SCW_SECRET_KEY="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
suite apply
```

(Keep those in a git-ignored `.env` and the CLI [auto-loads them](install.md) — no
`source .env`.)

- The **first run prompts once** for the account-specific values (project/organization
  ids, SSH key, server type) and writes them to `terraform.tfvars`.
- On **every run**, the values derived from `suite.yaml` are regenerated into
  `suite.auto.tfvars`: the bucket list and the firewall flags follow the enabled app set
  (add Meet or the Mailbox under `apps:` and the next apply opens their ports — no tfvars
  to edit).
- The outputs (SSH target, minted S3 keys, TEM relay account) land in the machine state
  file **`.suite-state.json`** and the Ansible inventory — nothing to copy by hand. Stash
  the printed secrets in your password manager; the state file is disposable.

It needs `terraform` **or** `tofu` on PATH. `suite apply` short-circuits this phase with
`infra: up to date` when nothing relevant changed; [`suite plan`](install.md) shows the
Terraform plan without applying. The rest of this page is the manual equivalent (the dev
path) and the reference for every tfvars value.

## Bring your own server

Terraform is optional. To use a Debian server you already have, **omit `provider`** and set
its SSH target:

```yaml
# suite.yaml — no provider: key
server:
  ssh: root@203.0.113.10   # Debian 12/13, reachable over SSH
```

`suite apply` then **skips this whole phase** and starts at the [bootstrap](bootstrap.md) —
it still bootstraps, prints DNS records and deploys. You supply the server, its firewall
(open 22/80/443, plus 25 for the Mailbox and the LiveKit ports for Meet), and, in
`external` object-storage mode, your own S3 endpoint and pre-created buckets (see
[Configuration → Object storage](../reference/configuration.md#object-storage)). Read the
[SSH-key warning](bootstrap.md#caveats) before the first bootstrap.

## Scaleway

Scaleway is the recommended host: its **Object Storage is fully S3-compatible and supports
bucket CORS**, so `external` mode works for everything including Drive's browser-direct
uploads; and **[Transactional Email (TEM)](#mailbox-scaleway-tem)** gives the optional
Mailbox a native outbound relay.

### Prerequisites

- A Scaleway [Project](https://console.scaleway.com/) (note its **Project ID** and
  **Organization ID** — IAM is organization-scoped).
- [Terraform](https://developer.hashicorp.com/terraform) **or**
  [OpenTofu](https://opentofu.org/) ≥ 1.9.
- An **IAM API key** whose principal has **both** product rights
  (`InstancesFullAccess` + `ObjectStorageFullAccess`) **and `IAMManager`**, all scoped to
  the **organization**. Terraform mints the apps' S3 key via an IAM application/policy,
  which a product-only key cannot do (it 403s *"insufficient permissions: write
  application"*). Export it, never commit it:

    ```bash
    export SCW_ACCESS_KEY="SCWXXXXXXXXXXXXXXXXX"
    export SCW_SECRET_KEY="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
    ```

### Use (manual / dev equivalent)

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
| `type` | `PRO2-XXS` (2 vCPU / 8 GB) for a starting set like Docs + Drive; `PRO2-XS` for the Mailbox. PRO2 has no local SSD, so `root_volume_type = "sbs_volume"` (the default). Match it to [Server sizing](../operate/sizing.md). |
| `volume_size_gb` | Root disk, default `50` (min `40`). |
| `bucket_names` | One media bucket per enabled app in `external` mode — see [Object storage](#object-storage). |

### Watch out

- **The apps' S3 key expires.** Scaleway orgs cap API-key lifetime (~1 year); the module
  sets ~11 months and pins it. **Rotate the key and re-apply before it lapses**, then
  re-sync the in-cluster secret, or media/backups break.
- **Scaleway Debian logs in as `root`** (not `debian`). The `ssh_target` output is
  `root@<ip>`; the bootstrap hardens root afterwards.
- **Mailbox → open SMTP.** Enabling `messages:` in `suite.yaml` sets `enable_mailbox` on
  the next apply, opening inbound port 25 and registering the
  [TEM sending domain](#mailbox-scaleway-tem).

## Object storage

OwnSuite's object storage is pluggable
([ADR-003](../understand/decisions.md#adr-003-pluggable-object-storage-garage-or-external-eu-s3)):

- **`external`** (recommended, and the default) — a managed S3 bucket per enabled app.
  Drive uploads/downloads files **straight from the browser** via presigned URLs, which
  needs the S3 endpoint to serve **CORS**. **Scaleway Object Storage supports CORS** (the
  module sets a bucket CORS rule for `https://*.<domain>`), so `external` works end-to-end.
  It also works on any CORS-capable RGW (AWS S3, OVH).
- **`garage`** — an in-cluster single-node store. Media buckets live in the cluster,
  downloads are proxied same-origin through the authenticated `/media/` path, and presigned
  uploads are proxied by Traefik — **no cross-origin request, so no CORS needed**. Use it
  anywhere you want full in-cluster sovereignty, or on an S3 endpoint that can't serve CORS
  (some OpenStack Swift `s3api` layers return `NotImplemented` for `PutBucketCors`). It is
  also the mode the automated tests exercise.

The off-site **backup** store is unaffected either way: backups are written server-side
(CNPG / rclone), never from the browser, so they have no CORS requirement.

## Where the outputs go

`suite apply` reads the outputs itself and stores them in the machine state
(`.suite-state.json`): the SSH target, the S3 endpoint/region, and the minted keys — the
next phases (bootstrap, DNS, deploy) pick them up from there, and the DNS step points your
records at the server IP. Nothing lands in a dotfile you have to source.

Running Terraform by hand (the dev path), wire them yourself:

```bash
terraform output ssh_target            # -> server.ssh / the Ansible inventory
terraform output public_ip             # point your DNS records here
export OWNSUITE_S3_ACCESS_KEY="$(terraform output -raw s3_access_key)"
export OWNSUITE_S3_SECRET_KEY="$(terraform output -raw s3_secret_key)"
```

The S3 **access/secret keys are external secrets** — they cannot be derived from the seed,
so they live in the machine state (or your environment; an exported value always wins),
never in `suite.yaml`.

### Mailbox: Scaleway TEM { #mailbox-scaleway-tem }

With the Mailbox enabled on Scaleway, the module also registers the sending domain in
**Transactional Email (TEM)** and grants the workload key TEM send rights. `suite apply`
stores the relay account (username = your Project ID, password = the workload key secret)
in the machine state and prints the TEM SPF/DKIM/DMARC records to publish so Scaleway
validates the domain. Set the relay host under the app in `suite.yaml`:

```yaml
apps:
  messages:
    relay_host: smtp.tem.scaleway.com:2587
    spf_include: _spf.tem.scaleway.com
```

Port **2587** (STARTTLS) — not 587: Scaleway Instances **block outbound 25/465/587 by
default**, and TEM exposes `2587`/`2465` for exactly this. See
[Mailbox → Outbound](../understand/messages.md#outbound-scaleway-tem-or-an-external-relay).

!!! warning "Off-site backup: same account by default"
    With `backup.provision: true` (the Scaleway default when a provider is set), apply mints
    the backup bucket in `nl-ams` under the **same** account — fine for the restore drill,
    not real DR. For production DR, set `backup.provision: false` and point `backup.endpoint`
    at a store in a **different** account or provider (see
    [Backups & restore](../operate/backups.md)).

## Tearing the server down

Deleting the server is **not** a `suite` verb — [`suite destroy`](../reference/cli.md#suite-destroy)
uninstalls the suite from the cluster but keeps the machine. To tear the infrastructure
itself down, run OpenTofu/Terraform directly:

```bash
cd terraform/environments/scaleway
tofu destroy                           # removes the server, firewall and buckets
```

!!! danger "This deletes data"
    Destroying the infrastructure deletes the server's volumes and — depending on the
    provider — the buckets and their contents. Take a [`suite backup`](../operate/backups.md)
    first; the off-site copy (a different account) is what survives this.

## Adding another cloud provider

The Terraform layout makes another provider an isolated change — each provider is a sibling
module behind the **same output contract**, so bootstrap and Helmfile stay
provider-agnostic:

```
terraform/
  modules/
    scaleway/          # native: server + Object Storage + IAM key (+ TEM)
  environments/
    scaleway/          # provider config + your values; run terraform here
```

1. Create `modules/<provider>/` exposing the same outputs as the Scaleway module:
   `public_ip`, `ssh_target`, `s3_endpoint`, `s3_region`, `buckets`, `s3_access_key`,
   `s3_secret_key`.
2. Create `environments/<provider>/` with that provider's `provider {}` block and a
   `module "suite"` pointing at the new module.

No switch logic, no change to existing providers.

## Validate

```bash
terraform fmt -check -recursive
terraform -chdir=environments/scaleway init -backend=false
terraform -chdir=environments/scaleway validate
```

State and `*.tfvars` are gitignored — keep secrets out of the repo.
