module "suite" {
  source = "../../modules/infomaniak"

  name                  = var.name
  ssh_public_key        = var.ssh_public_key
  flavor_name           = var.flavor_name
  image_name            = var.image_name
  volume_size_gb        = var.volume_size_gb
  external_network_name = var.external_network_name
  ssh_allowed_cidr      = var.ssh_allowed_cidr
  enable_mailbox        = var.enable_mailbox
  bucket_names          = var.bucket_names
}

# Off-site backup bucket (ADR-006): MUST be a different account/provider than the
# primary above. Uncomment, add a second provider with aliased credentials, and
# point OWNSUITE_BACKUP_S3_* at its outputs.
#
# provider "openstack" {
#   alias = "backup"
#   cloud = var.backup_openstack_cloud
# }
# module "backup_store" {
#   source       = "../../modules/infomaniak"
#   providers    = { openstack = openstack.backup }
#   name         = "${var.name}-backup"
#   ...
#   bucket_names = ["ownsuite-backups"]
# }
