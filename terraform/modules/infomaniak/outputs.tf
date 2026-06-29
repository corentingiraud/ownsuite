# Output contract. A module for a future provider (modules/<provider>) MUST
# expose this same set so environments/<provider> stays a drop-in.

output "public_ip" {
  description = "Floating IP of the server."
  value       = openstack_networking_floatingip_v2.this.address
}

output "ssh_target" {
  description = "SSH target for the inventory / OWNSUITE_SERVER_SSH. Debian cloud images log in as 'debian' (use ansible_become: true); the bootstrap then hardens root."
  value       = "debian@${openstack_networking_floatingip_v2.this.address}"
}

output "s3_endpoint" {
  description = "S3 endpoint for OWNSUITE_S3_ENDPOINT."
  value       = "https://s3.pub1.infomaniak.cloud"
}

output "s3_region" {
  description = "S3 region (compatibility value; data is in Switzerland)."
  value       = "us-east-1"
}

output "buckets" {
  description = "Names of the created buckets."
  value       = [for c in openstack_objectstorage_container_v1.this : c.name]
}

output "s3_access_key" {
  description = "S3 access key for the apps."
  value       = openstack_identity_ec2_credential_v3.s3.access
  sensitive   = true
}

output "s3_secret_key" {
  description = "S3 secret key for the apps."
  value       = openstack_identity_ec2_credential_v3.s3.secret
  sensitive   = true
}
