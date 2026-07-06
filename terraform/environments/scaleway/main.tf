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
  enable_meet_turn = var.enable_meet_turn
  mail_domain      = var.domain
  bucket_names     = var.bucket_names

  # Allow the apps' subdomains to talk to S3 directly (Drive/Docs browser uploads).
  cors_allowed_origins = var.domain != "" ? ["https://*.${var.domain}"] : []
}

# Off-site backup bucket (ADR-006). For this test suite it lives in a DIFFERENT
# region than the primary (backup_region, default nl-ams vs fr-par) and reuses the
# workload IAM key (module.suite.s3_*) — the key is project-scoped, so it reaches
# buckets in any region of the same project. That survives losing the server, which
# is what `suite restore` exercises. TRUE prod DR wants a separate account/provider
# (a second provider alias + its own key); see docs/operate/backups.md.
resource "scaleway_object_bucket" "backup" {
  count  = var.backup_bucket_name != "" ? 1 : 0
  name   = var.backup_bucket_name
  region = var.backup_region
}
