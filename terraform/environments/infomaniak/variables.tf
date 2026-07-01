variable "openstack_cloud" {
  description = "Name of the clouds.yaml entry to authenticate with (application credential). Keep credentials out of Terraform — use clouds.yaml or OS_* env vars."
  type        = string
}

variable "name" {
  description = "Deployment name / association slug (prefixes server and network resources)."
  type        = string
}

variable "ssh_public_key" {
  description = "SSH public key authorized on the server (OpenSSH format)."
  type        = string
}

variable "flavor_name" {
  description = "OpenStack flavor (see modules/infomaniak/variables.tf)."
  type        = string
  default     = "a4-ram8-disk0"
}

variable "image_name" {
  description = "Exact Debian 12/13 image name (`openstack image list`)."
  type        = string
  default     = "Debian 13 trixie"
}

variable "volume_size_gb" {
  description = "Root volume size in GB (>=40)."
  type        = number
  default     = 50
}

variable "external_network_name" {
  description = "External network for the floating IP (`openstack network list --external`)."
  type        = string
  default     = "ext-floating1"
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
  description = "S3 buckets to create via the S3 API. Leave empty (default) in `garage` mode — Garage creates the media buckets in-cluster. Set it for an external-S3 primary or the off-site backup store."
  type        = list(string)
  default     = []
}
