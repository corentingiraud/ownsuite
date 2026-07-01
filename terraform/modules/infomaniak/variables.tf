# Inputs for the Infomaniak (OpenStack) host + object storage.
# Account/region-specific names (image, external network) are variables, not
# hardcoded: discover yours with `openstack image list` and
# `openstack network list --external`. Defaults match Infomaniak pub1 docs.

variable "name" {
  description = "Name prefix for the instance and its network resources (e.g. the association slug)."
  type        = string
}

variable "ssh_public_key" {
  description = "SSH public key authorized on the server (OpenSSH format). The matching private key is what `suite bootstrap` / SSH will use."
  type        = string
}

variable "flavor_name" {
  description = "OpenStack flavor. Core (Docs+Drive): a4-ram8-disk0. All-in (+Mailbox): a flavor with >=12-16 GB RAM. See docs/operate/sizing.md and `openstack flavor list`."
  type        = string
  default     = "a4-ram8-disk0"
}

variable "image_name" {
  description = "Exact OS image name. The bootstrap playbook asserts Debian 12 (bookworm) or 13 (trixie). Find the exact name with `openstack image list` — Infomaniak names it lowercase, no minor."
  type        = string
  default     = "Debian 13 trixie"
}

variable "volume_size_gb" {
  description = "Root (boot) volume size in GB. Diskless flavors boot from this volume. sizing.md: 40 GB core, 50 GB all-in."
  type        = number
  default     = 50

  validation {
    condition     = var.volume_size_gb >= 40
    error_message = "OwnSuite needs at least 40 GB of disk (docs/operate/sizing.md)."
  }
}

variable "external_network_name" {
  description = "Name of the external/public network the floating IP is drawn from. Find it with `openstack network list --external`."
  type        = string
  default     = "ext-floating1"
}

variable "subnet_cidr" {
  description = "CIDR of the instance's private subnet. Must not overlap the K3s pod/service CIDRs (10.42.0.0/16, 10.43.0.0/16)."
  type        = string
  default     = "192.168.42.0/24"
}

variable "dns_nameservers" {
  description = "Resolvers for the private subnet."
  type        = list(string)
  default     = ["9.9.9.9", "149.112.112.112"] # Quad9
}

variable "ssh_allowed_cidr" {
  description = "Source CIDR allowed to reach SSH (22). Defaults to the whole internet; restrict to your admin IP for a smaller attack surface. SSH is also key-only and root-hardened by the bootstrap role."
  type        = string
  default     = "0.0.0.0/0"
}

variable "enable_mailbox" {
  description = "Open inbound SMTP (port 25) for the optional Mailbox app. Leave false unless you deploy Messages."
  type        = bool
  default     = false
}

variable "enable_meet" {
  description = "Open LiveKit media ports (7881/tcp fallback + 7882/udp mux) for the optional Meet app. Leave false unless you deploy Meet."
  type        = bool
  default     = false
}

variable "bucket_names" {
  description = "S3 buckets to create via the S3 API on THIS account. Leave empty (the default) in the recommended `garage` object-storage mode — Garage creates the media buckets in-cluster. Set it only for an external-S3 primary, or for the off-site BACKUP store, which must live in a DIFFERENT account/provider (ADR-006) — created from a second module instance, not here."
  type        = list(string)
  default     = []
}
