variable "project_id" {
  description = "Scaleway project ID (`scw config get default-project-id` or the console). Used by the provider and to scope the object-storage IAM policy."
  type        = string
}

variable "organization_id" {
  description = "Scaleway organization ID. Required to create the IAM application/policy/key (IAM is organization-scoped, not project-scoped). Find it under Organization settings or `scw config get default-organization-id`."
  type        = string
}

variable "region" {
  description = "Scaleway region for object storage / S3 endpoint (fr-par, nl-ams, pl-waw)."
  type        = string
  default     = "fr-par"
}

variable "zone" {
  description = "Scaleway zone for the server (e.g. fr-par-1). Must sit inside `region`."
  type        = string
  default     = "fr-par-1"
}

variable "name" {
  description = "Deployment name / association slug (prefixes server, network and IAM resources)."
  type        = string
}

variable "domain" {
  description = "Base domain (= OWNSUITE_DOMAIN). Used as the TEM sending domain when enable_mailbox = true."
  type        = string
  default     = ""
}

variable "ssh_public_key" {
  description = "SSH public key authorized on the server (OpenSSH format)."
  type        = string
}

variable "type" {
  description = "Scaleway instance type (see modules/scaleway/variables.tf). PRO2-XXS core, PRO2-XS for Mailbox."
  type        = string
  default     = "PRO2-XXS"
}

variable "image" {
  description = "Marketplace image label — Debian 12/13 (`scw marketplace image list`)."
  type        = string
  default     = "debian_bookworm"
}

variable "volume_size_gb" {
  description = "Root volume size in GB (>=40)."
  type        = number
  default     = 50
}

variable "root_volume_type" {
  description = "Root volume type (`sbs_volume` for PRO2 types)."
  type        = string
  default     = "sbs_volume"
}

variable "ssh_allowed_cidr" {
  description = "Source CIDR allowed on SSH (22). Narrow to your admin IP in production."
  type        = string
  default     = "0.0.0.0/0"
}

variable "enable_mailbox" {
  description = "Open SMTP (25) for the Mailbox app."
  type        = bool
  default     = false
}

variable "enable_meet" {
  description = "Open LiveKit media ports (7881/tcp + 7882/udp) for the Meet app."
  type        = bool
  default     = false
}

variable "bucket_names" {
  description = "Object-storage buckets to create. Set the media bucket(s) here in Scaleway-native-S3 primary mode. The off-site backup store must live in a different account/provider."
  type        = list(string)
  default     = []
}
