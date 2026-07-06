output "public_ip" {
  description = "Server public IP — point your DNS (and OWNSUITE_DOMAIN records) at this."
  value       = module.suite.public_ip
}

output "ssh_target" {
  description = "Set ansible_host / OWNSUITE_SERVER_SSH from this (Scaleway Debian logs in as root)."
  value       = module.suite.ssh_target
}

# Convenience: the object-storage lines to paste into .env. Read the secrets with
# `terraform output -raw s3_secret_key` (they are sensitive).
output "env_object_storage" {
  description = ".env snippet for object storage (Scaleway-native S3 primary)."
  value       = <<-EOT
    OWNSUITE_S3_ENDPOINT=${module.suite.s3_endpoint}
    OWNSUITE_S3_REGION=${module.suite.s3_region}
    OWNSUITE_S3_BUCKET=${try(module.suite.buckets[0], "<no bucket: set bucket_names>")}
  EOT
}

# Convenience: the off-site backup lines to paste into .env (empty when no backup
# bucket). Mirrors env_object_storage; `suite provision` parses it the same way.
output "env_backup" {
  description = ".env snippet for the off-site backup store (empty when backup_bucket_name unset)."
  value       = var.backup_bucket_name == "" ? "" : <<-EOT
    OWNSUITE_BACKUP_S3_ENDPOINT=https://s3.${var.backup_region}.scw.cloud
    OWNSUITE_BACKUP_S3_REGION=${var.backup_region}
    OWNSUITE_BACKUP_S3_BUCKET=${var.backup_bucket_name}
  EOT
}

# Backup S3 creds reuse the workload key (see main.tf). null when no backup bucket,
# so `suite provision` writes OWNSUITE_BACKUP_S3_* keys only when backups are set up.
output "backup_s3_access_key" {
  description = "Off-site backup S3 access key (reuses the workload key for the test suite)."
  value       = var.backup_bucket_name == "" ? null : module.suite.s3_access_key
  sensitive   = true
}

output "backup_s3_secret_key" {
  description = "Off-site backup S3 secret key (reuses the workload key for the test suite)."
  value       = var.backup_bucket_name == "" ? null : module.suite.s3_secret_key
  sensitive   = true
}

output "s3_endpoint" {
  value = module.suite.s3_endpoint
}

output "s3_region" {
  value = module.suite.s3_region
}

output "s3_access_key" {
  value     = module.suite.s3_access_key
  sensitive = true
}

output "s3_secret_key" {
  value     = module.suite.s3_secret_key
  sensitive = true
}

# Mailbox / TEM relay (null unless enable_mailbox). Export the relay creds before
# `helmfile sync`; publish tem_dns alongside OwnSuite's own mail records.
output "mta_relay_username" {
  value = module.suite.mta_relay_username
}

output "mta_relay_password" {
  value     = module.suite.mta_relay_password
  sensitive = true
}

output "tem_dns" {
  value = module.suite.tem_dns
}
