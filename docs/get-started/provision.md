# Provision the server (Terraform)

Before the server can be bootstrapped, it has to exist. The Terraform layer in
[`terraform/`](https://github.com/corentingiraud/ownsuite/tree/main/terraform)
provisions the **infrastructure half** of an OwnSuite deployment on
[Infomaniak Public Cloud](https://www.infomaniak.com/en/hosting/public-cloud)
(OpenStack):

- a Debian server with a floating IP and a firewall,
- the object-storage buckets and S3 keys the apps and backups use.

It stops there. [Prepare the server](bootstrap.md) (Ansible) then turns the
server into a single-node K3s cluster, and the [installer](install.md) deploys
the apps. Terraform is optional — if you already have a Debian server and an S3
bucket, skip straight to [Prepare the server](bootstrap.md).

!!! note "Object storage: garage by default on Infomaniak"
    The **recommended** object-storage mode on Infomaniak is `garage` (in-cluster):
    Garage creates the media buckets itself, and Drive's browser uploads are proxied
    same-origin so they need no S3 CORS — which Infomaniak's Swift+s3api endpoint
    [cannot provide](#object-storage-caveat). In that mode Terraform creates **no
    buckets** (`bucket_names = []`, the default); it only provisions the server and
    mints the S3 keys via `openstack_identity_ec2_credential_v3`.

    If you do use external S3 (a CORS-capable RGW provider, or the off-site backup
    store), note that buckets are created through the **S3 API**, not as Swift
    containers: on Infomaniak the two are separate namespaces, and a Swift container
    is invisible to the S3 endpoint the apps use. The module handles this with the
    `aws` provider pointed at the Infomaniak S3 endpoint.

## Layout

```
terraform/
  modules/
    infomaniak/        # OpenStack: host + Swift/S3 buckets + S3 keys
  environments/
    infomaniak/        # provider config + your values; run terraform here
```

## Prerequisites

- An Infomaniak Public Cloud project.
- [Terraform](https://developer.hashicorp.com/terraform) **or**
  [OpenTofu](https://opentofu.org/) ≥ 1.9.
- An **unrestricted application credential** for the project, referenced from a
  `clouds.yaml` entry so no secrets land in the repo. It **must** be unrestricted:
  Terraform mints the S3 access key via `openstack_identity_ec2_credential_v3`, and
  a restricted application credential cannot create further credentials (OpenStack
  returns *"application_credential is not allowed for managing additional application
  credentials"*). In Horizon: *Identity → Application Credentials → Create*, tick
  **Unrestricted**.

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

## Use

```bash
cd terraform/environments/infomaniak
cp terraform.tfvars.example terraform.tfvars   # fill in (auth via clouds.yaml)
terraform init
terraform plan
terraform apply
```

Three account-specific values must match your project — confirm them before you
apply:

| Variable | Find it with |
|---|---|
| `image_name` (Debian 12/13) | `openstack image list` — copy the name **exactly**; Infomaniak's is `Debian 13 trixie` (lowercase, no minor), not `Debian 13.0 Trixie`. A mismatch fails the apply with "no image found". |
| `external_network_name` | `openstack network list --external` |
| `flavor_name` | `openstack flavor list` — see [Server sizing](../operate/sizing.md) |

## Wire the outputs into your config

```bash
terraform output ssh_target           # -> OWNSUITE_SERVER_SSH + ansible_host
terraform output -raw s3_access_key    # secret (the minted S3 access key)
terraform output -raw s3_secret_key    # secret (the minted S3 secret key)
```

The S3 **access/secret keys are external secrets** — they cannot be derived from the
seed, so they are not written to `.env`. Export them (like the seed) before
`make sync` / `suite install` so the apps and backups receive them:

```bash
export OWNSUITE_S3_ACCESS_KEY="$(terraform output -raw s3_access_key)"
export OWNSUITE_S3_SECRET_KEY="$(terraform output -raw s3_secret_key)"
```

In **garage** mode (the [recommended](#object-storage-caveat) Infomaniak setup) the
apps use in-cluster Garage with seed-derived keys, so you do **not** need the lines
above or any `OWNSUITE_S3_*` endpoint/bucket — Terraform creates no buckets and the
keys are only useful for the off-site backup store. In **external** S3 mode, also set
the endpoint/region/bucket from `terraform output env_object_storage` (region is
`us-east-1` on Infomaniak, not `eu-west`) and pre-create one bucket per enabled app
(`docs-media-storage`, `drive-media-storage`, `projects-media-storage`,
`messages-media-storage`; Grist uses a PVC, no bucket) — see
[Object storage](../reference/configuration.md#object-storage).

Point your DNS records (`OWNSUITE_DOMAIN`) at the `public_ip` output, then
continue with [Prepare the server](bootstrap.md).

!!! warning "Off-site backup must be a second account"
    The backup bucket (`OWNSUITE_BACKUP_S3_*`) must live in a **different**
    account or provider than the primary (see
    [Backups & restore](../operate/backups.md)). Use the commented second-module
    example in `environments/infomaniak/main.tf` — do not reuse the primary
    bucket.

## Object storage caveat — use `garage` on Infomaniak { #object-storage-caveat }

Set `OWNSUITE_OBJECT_STORAGE_MODE=garage` (in-cluster) on Infomaniak. The reason is
**CORS**: Drive uploads/downloads files straight from the browser, which needs the S3
endpoint to return CORS headers. Infomaniak's object storage is OpenStack **Swift with
an `s3api` compatibility layer**, and that layer does **not** implement bucket CORS
(`PutBucketCors` → `NotImplemented`, [OpenStack bug #2077629](https://bugs.launchpad.net/swift/+bug/2077629));
Swift's own container CORS metadata is honoured only on the Swift endpoint, not the S3
one. So there is no way to give the Infomaniak S3 endpoint CORS, and browser-direct S3
uploads are blocked.

`garage` mode sidesteps this entirely: the media buckets live in-cluster, downloads are
proxied same-origin through the authenticated `/media/` path, and Drive's presigned
uploads are signed against the public Drive host and proxied to Garage by Traefik (no
cross-origin request, so no CORS). It is also the mode the automated tests exercise.

External S3 mode (`external`) stays valid on **CORS-capable RGW providers** (AWS S3,
Scaleway, OVH) — just not on Infomaniak's Swift+s3api. The off-site **backup** store is
unaffected either way: backups are written server-side (CNPG/rclone), never from the
browser, so they have no CORS requirement.

## Adding another cloud provider

Only Infomaniak is implemented, but the layout makes another provider an
isolated change:

1. Create `modules/<provider>/` exposing the **same output contract** as
   `modules/infomaniak/outputs.tf`: `public_ip`, `ssh_target`, `s3_endpoint`,
   `s3_region`, `buckets`, `s3_access_key`, `s3_secret_key`.
2. Create `environments/<provider>/` with that provider's `provider {}` block and
   a `module "suite"` pointing at the new module.

No switch logic, no change to existing providers.

## Validate

```bash
terraform fmt -check -recursive
terraform -chdir=environments/infomaniak init -backend=false
terraform -chdir=environments/infomaniak validate
```

State and `*.tfvars` are gitignored — keep secrets out of the repo.
</content>
