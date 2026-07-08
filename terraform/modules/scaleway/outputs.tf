# Output contract consumed by environments/scaleway, the bootstrap + Helmfile flow.

output "public_ip" {
  description = "Public IP of the server."
  value       = scaleway_instance_ip.this.address
}

output "ssh_target" {
  description = "SSH target for the inventory / OWNSUITE_SERVER_SSH. Scaleway Debian images log in as 'root'; the bootstrap then hardens root."
  value       = "root@${scaleway_instance_ip.this.address}"
}

output "s3_endpoint" {
  description = "S3 endpoint for OWNSUITE_S3_ENDPOINT."
  value       = local.s3_endpoint
}

output "s3_region" {
  description = "S3 region."
  value       = var.region
}

output "buckets" {
  description = "Names of the object-storage buckets created in this project/region."
  value       = [for b in scaleway_object_bucket.this : b.name]
}

output "s3_access_key" {
  description = "S3 access key for the apps."
  value       = scaleway_iam_api_key.s3.access_key
  sensitive   = true
}

output "s3_secret_key" {
  description = "S3 secret key for the apps."
  value       = scaleway_iam_api_key.s3.secret_key
  sensitive   = true
}

# --- Mailbox / TEM relay (null unless enable_mailbox) ------------------------
output "mta_relay_username" {
  description = "OWNSUITE_MTA_RELAY_USERNAME — TEM SMTP auth user (the project ID)."
  value       = var.enable_mailbox ? scaleway_tem_domain.mail[0].smtps_auth_user : null
}

output "mta_relay_password" {
  description = "OWNSUITE_MTA_RELAY_PASSWORD — the workload IAM key secret (carries TEM send rights). Same value as s3_secret_key."
  value       = scaleway_iam_api_key.s3.secret_key
  sensitive   = true
}

output "tem_dns" {
  description = "TEM DNS records to publish so Scaleway validates the sending domain (in addition to OwnSuite's own SPF/DKIM). null when mailbox is off."
  value = var.enable_mailbox ? {
    spf_value    = scaleway_tem_domain.mail[0].spf_value
    dkim_name    = scaleway_tem_domain.mail[0].dkim_name
    dkim_config  = scaleway_tem_domain.mail[0].dkim_config
    dmarc_name   = scaleway_tem_domain.mail[0].dmarc_name
    dmarc_config = scaleway_tem_domain.mail[0].dmarc_config
  } : null
}
