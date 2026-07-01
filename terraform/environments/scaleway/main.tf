module "suite" {
  source = "../../modules/scaleway"

  name             = var.name
  ssh_public_key   = var.ssh_public_key
  project_id       = var.project_id
  region           = var.region
  type             = var.type
  image            = var.image
  volume_size_gb   = var.volume_size_gb
  root_volume_type = var.root_volume_type
  ssh_allowed_cidr = var.ssh_allowed_cidr
  enable_mailbox   = var.enable_mailbox
  enable_meet      = var.enable_meet
  mail_domain      = var.domain
  bucket_names     = var.bucket_names

  # Allow the apps' subdomains to talk to S3 directly (Drive/Docs browser uploads).
  cors_allowed_origins = var.domain != "" ? ["https://*.${var.domain}"] : []
}

# Off-site backup bucket (ADR-006): MUST be a different account/provider than the
# primary above. Uncomment, add a second provider with aliased credentials (a
# different Scaleway project or org, or another provider entirely), and point
# OWNSUITE_BACKUP_S3_* at its outputs.
#
# provider "scaleway" {
#   alias      = "backup"
#   project_id = var.backup_project_id
# }
# module "backup_store" {
#   source       = "../../modules/scaleway"
#   providers    = { scaleway = scaleway.backup }
#   name         = "${var.name}-backup"
#   ...
#   bucket_names = ["ownsuite-backups"]
# }
