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

!!! note "Why a single provider"
    Infomaniak object storage is OpenStack Swift with S3 compatibility, so one
    `openstack` provider does everything: Swift containers double as S3 buckets,
    and `openstack_identity_ec2_credential_v3` mints the S3 keys. No `aws`
    provider, no two-phase credential bootstrap.

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
- An **application credential** for the project, referenced from a
  `clouds.yaml` entry so no secrets land in the repo:

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
| `image_name` (Debian 12/13) | `openstack image list` |
| `external_network_name` | `openstack network list --external` |
| `flavor_name` | `openstack flavor list` — see [Server sizing](../operate/sizing.md) |

## Wire the outputs into your config

```bash
terraform output ssh_target           # -> OWNSUITE_SERVER_SSH + ansible_host
terraform output env_object_storage   # -> OWNSUITE_S3_* lines for .env
terraform output -raw s3_access_key    # secret
terraform output -raw s3_secret_key    # secret
```

Point your DNS records (`OWNSUITE_DOMAIN`) at the `public_ip` output, then
continue with [Prepare the server](bootstrap.md).

!!! warning "Off-site backup must be a second account"
    The backup bucket (`OWNSUITE_BACKUP_S3_*`) must live in a **different**
    account or provider than the primary (see
    [Backups & restore](../operate/backups.md)). Use the commented second-module
    example in `environments/infomaniak/main.tf` — do not reuse the primary
    bucket.

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
