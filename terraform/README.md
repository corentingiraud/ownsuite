# Terraform — provision the server + object storage

Terraform here does the *infrastructure* half only: it provisions a bare Debian
server (reachable by SSH, with a floating IP and firewall) and the S3 object
storage (buckets + keys). It stops there. `suite bootstrap` (Ansible) turns the
server into K3s and Helmfile deploys the apps — see `docs/get-started`.

```
terraform/
  modules/
    infomaniak/        # OpenStack: host + Swift/S3 buckets + S3 keys
  environments/
    infomaniak/        # provider config + your values; run terraform here
```

## Use

```bash
cd terraform/environments/infomaniak
cp terraform.tfvars.example terraform.tfvars   # fill in (auth via clouds.yaml)
terraform init
terraform plan
terraform apply
```

Then wire the outputs into your OwnSuite config:

```bash
terraform output ssh_target              # -> OWNSUITE_SERVER_SSH + ansible_host
terraform output env_object_storage      # -> OWNSUITE_S3_* lines for .env
terraform output -raw s3_access_key       # secret (S3 access key id)
terraform output -raw s3_secret_key       # secret (S3 secret key)
```

The **off-site backup** bucket (`OWNSUITE_BACKUP_S3_*`) must live in a *different*
account/provider than the primary (ADR-006). See the commented second-module
example in `environments/infomaniak/main.tf`.

## Adding another cloud provider (the "evolutive" part)

Only Infomaniak is implemented. To add e.g. Scaleway or OVH:

1. Create `modules/<provider>/` that provisions the same things and exposes the
   **exact same output contract** as `modules/infomaniak/outputs.tf`:
   `public_ip`, `ssh_target`, `s3_endpoint`, `s3_region`, `buckets`,
   `s3_access_key`, `s3_secret_key`.
2. Create `environments/<provider>/` with that provider's `provider {}` block and
   a `module "suite"` pointing at the new module.

That's the whole PR — no switch logic, no change to existing providers. Each
provider is an isolated directory honoring one output contract.

## Validate

```bash
terraform fmt -check -recursive
terraform -chdir=environments/infomaniak init -backend=false
terraform -chdir=environments/infomaniak validate
```

State and `*.tfvars` are gitignored — keep secrets out of the repo.
