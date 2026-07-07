# Inputs for the Scaleway host + object storage, consumed by environments/scaleway
# (instance `type`, marketplace image label, region).

variable "name" {
  description = "Name prefix for the server and its network/IAM/storage resources (e.g. the association slug). Bucket names derive from var.bucket_names, not this."
  type        = string
}

variable "ssh_public_key" {
  description = "SSH public key authorized on the server (OpenSSH format). Added to the project as an IAM SSH key; Scaleway injects it at boot via cloud-init."
  type        = string
}

variable "project_id" {
  description = "Scaleway project ID the resources live in. Needed to scope the object-storage IAM policy. Find it in the console or with `scw config get default-project-id`."
  type        = string
}

variable "region" {
  description = "Scaleway region for object storage and the S3 endpoint (fr-par, nl-ams, pl-waw). Zonal compute placement comes from the provider's `zone`."
  type        = string
  default     = "fr-par"
}

variable "type" {
  description = "Scaleway instance commercial type. Core (Docs+Drive): PRO2-XXS (2 vCPU / 8 GB). All-in (+Mailbox): PRO2-XS (4 vCPU / 16 GB). See docs/operate/sizing.md and `scw instance server-type list`."
  type        = string
  default     = "PRO2-XXS"
}

variable "image" {
  description = "Marketplace image label. The bootstrap playbook asserts Debian 12 (bookworm) or 13 (trixie). Confirm the exact label with `scw marketplace image list`."
  type        = string
  default     = "debian_bookworm"
}

variable "volume_size_gb" {
  description = "Root (block) volume size in GB. sizing.md: 40 GB core, 50 GB all-in."
  type        = number
  default     = 50

  validation {
    condition     = var.volume_size_gb >= 40
    error_message = "OwnSuite needs at least 40 GB of disk (docs/operate/sizing.md)."
  }
}

variable "root_volume_type" {
  description = "Root volume type. `sbs_volume` (block storage) is required for PRO2 types (no local SSD) and lets the size be arbitrary. Use `l_ssd` only for types that ship local storage."
  type        = string
  default     = "sbs_volume"
}

variable "ssh_allowed_cidr" {
  description = "Source CIDR allowed to reach SSH (22). Defaults to the whole internet; restrict to your admin IP for a smaller attack surface. SSH is also key-only and root-hardened by the bootstrap role."
  type        = string
  default     = "0.0.0.0/0"
}

variable "enable_mailbox" {
  description = "Open inbound SMTP (port 25) for the optional Mailbox app AND register the TEM sending domain for the outbound relay. Leave false unless you deploy Messages."
  type        = bool
  default     = false
}

variable "mail_domain" {
  description = "Email/sending domain to register in Scaleway TEM (the mailbox's domain, = OWNSUITE_DOMAIN, e.g. mail.example.org). Required when enable_mailbox = true."
  type        = string
  default     = ""
}

variable "enable_meet" {
  description = "Open LiveKit media ports (7881/tcp fallback + 7882/udp mux) for the optional Meet app. Leave false unless you deploy Meet."
  type        = bool
  default     = false
}

variable "enable_meet_turn" {
  description = "Open the LiveKit embedded TURN/TLS port (5349/tcp) for Meet clients behind firewalls that block both 7881 and 7882. Requires enable_meet and OWNSUITE_MEET_TURN=true. Leave false unless you need TURN."
  type        = bool
  default     = false
}

variable "s3_key_expires_at" {
  description = "RFC3339 expiry for the apps' S3 API key. null (default) = apply-time + ~11 months, safely under orgs that cap key lifetime at 1 year. Pin a date to control it. Rotate the key + re-apply before it lapses."
  type        = string
  default     = null
}

variable "cors_allowed_origins" {
  description = "Browser origins allowed to make direct (presigned) requests to the buckets. Empty = no CORS rule. In external-S3 mode Drive/Docs/Projects/Messages upload+download straight from the browser, so on a CORS-capable provider (Scaleway RGW) set e.g. [\"https://*.example.org\"] — otherwise the upload preflight (OPTIONS) 403s. (Garage mode proxies same-origin and needs none.)"
  type        = list(string)
  default     = []
}

variable "bucket_names" {
  description = "Object-storage buckets to create in THIS project/region. In the Scaleway-native-S3 primary mode, set the media bucket(s) here. The off-site BACKUP store must live in a DIFFERENT account/provider (ADR-006) — created from a second module instance, not here."
  type        = list(string)
  default     = []
}
