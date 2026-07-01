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
