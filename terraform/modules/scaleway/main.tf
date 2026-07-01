# Scaleway — bare server + object storage for one OwnSuite instance. Terraform
# only provisions: a Debian server reachable by SSH, its firewall, a public IP,
# and the object-storage buckets + an IAM key the apps use. `suite bootstrap`
# (Ansible) then turns the server into K3s; Helmfile deploys the apps.

locals {
  # 80/443 must be public (web + ACME http-01). SSH is scoped separately.
  web_ports = var.enable_mailbox ? [80, 443, 25] : [80, 443]

  # Scaleway Object Storage S3 endpoint for the chosen region.
  s3_endpoint = "https://s3.${var.region}.scw.cloud"

  # API-key expiry. Orgs may enforce a key expiration AND cap it (~1 year). When
  # the caller doesn't pin a date, default to apply-time + ~11 months — safely
  # under a 1-year cap. ignore_changes (below) keeps timestamp() from churning it.
  s3_key_expires_at = coalesce(var.s3_key_expires_at, timeadd(timestamp(), "8000h"))

  # The workload identity needs object storage always, plus transactional email
  # (the mailbox's outbound relay through TEM) when the mailbox is enabled.
  workload_permission_sets = var.enable_mailbox ? [
    "ObjectStorageFullAccess", "TransactionalEmailFullAccess",
  ] : ["ObjectStorageFullAccess"]
}

# --- SSH key ----------------------------------------------------------------
# Project-scoped key; Scaleway injects all project SSH keys into the instance at
# boot via cloud-init, so the server is created depending on this existing.
resource "scaleway_iam_ssh_key" "this" {
  name       = "${var.name}-key"
  public_key = var.ssh_public_key
}

# --- Public IP + firewall ---------------------------------------------------
# ponytail: rDNS/PTR (mail.<domain>) for mailbox reputation is NOT set here —
# `reverse` is computed on scaleway_instance_ip in provider v2.77. Set it via the
# console or the dedicated reverse-DNS resource once the mail.* A record resolves
# (ADR-027). Not a blocker for install/ACME.
resource "scaleway_instance_ip" "this" {}

resource "scaleway_instance_security_group" "this" {
  name                    = "${var.name}-sg"
  description             = "OwnSuite: SSH (scoped) + HTTP/HTTPS (+SMTP if Mailbox)."
  inbound_default_policy  = "drop"
  outbound_default_policy = "accept"

  # ponytail: SSH open to ssh_allowed_cidr (default world); narrow it per deploy.
  inbound_rule {
    action   = "accept"
    protocol = "TCP"
    port     = 22
    ip_range = var.ssh_allowed_cidr
  }

  # Web (+SMTP) open to the world. ip_range omitted defaults to 0.0.0.0/0.
  dynamic "inbound_rule" {
    for_each = toset(local.web_ports)
    content {
      action   = "accept"
      protocol = "TCP"
      port     = inbound_rule.value
    }
  }

  # Meet (LiveKit) media, open only when enable_meet: one muxed UDP port (7882) plus
  # a TCP fallback (7881) — the ADR-027 non-HTTP-port precedent extended to UDP.
  dynamic "inbound_rule" {
    for_each = var.enable_meet ? {
      meet-tcp = { port = 7881, protocol = "TCP" }
      meet-udp = { port = 7882, protocol = "UDP" }
    } : {}
    content {
      action   = "accept"
      protocol = inbound_rule.value.protocol
      port     = inbound_rule.value.port
    }
  }
}

# --- Server -----------------------------------------------------------------
resource "scaleway_instance_server" "this" {
  name              = var.name
  type              = var.type
  image             = var.image
  ip_id             = scaleway_instance_ip.this.id
  security_group_id = scaleway_instance_security_group.this.id

  root_volume {
    size_in_gb            = var.volume_size_gb
    volume_type           = var.root_volume_type
    delete_on_termination = true
  }

  # The SSH key must be in the project before cloud-init runs on first boot.
  depends_on = [scaleway_iam_ssh_key.this]
}

# --- Object storage ---------------------------------------------------------
# A dedicated IAM application + API key gives the apps (rclone, CNPG Barman,
# app media clients) S3 credentials. The key is useless without a policy
# granting object-storage access in this project — Scaleway authorizes S3 by
# IAM, so an unscoped key gets 403 on every call.
resource "scaleway_iam_application" "s3" {
  name        = "${var.name}-s3"
  description = "OwnSuite object-storage access for ${var.name}."
}

resource "scaleway_iam_policy" "s3" {
  name           = "${var.name}-s3"
  description    = "Object-storage access for ${var.name}, scoped to this project."
  application_id = scaleway_iam_application.s3.id

  rule {
    project_ids          = [var.project_id]
    permission_set_names = local.workload_permission_sets
  }
}

resource "scaleway_iam_api_key" "s3" {
  application_id = scaleway_iam_application.s3.id
  description    = "OwnSuite S3 key for ${var.name}."
  # CRITICAL for Object Storage: the S3 endpoint resolves buckets in the key's
  # default project. Without this it defaults to the org's default project (!=
  # where the buckets live), so every object op 403s "AccessDenied".
  default_project_id = var.project_id
  expires_at         = local.s3_key_expires_at

  # Set once at creation; don't diff when timestamp() moves on later plans.
  # Rotate the key + re-apply before it lapses (see local.s3_key_expires_at).
  lifecycle {
    ignore_changes = [expires_at]
  }
}

resource "scaleway_object_bucket" "this" {
  for_each = toset(var.bucket_names)
  name     = each.value
  region   = var.region

  # Browser-direct (presigned) uploads/downloads need CORS in external-S3 mode.
  # Scaleway RGW honours PutBucketCors (unlike Infomaniak's Swift+s3api), so the
  # preflight OPTIONS succeeds once the app origin is allowed.
  dynamic "cors_rule" {
    for_each = length(var.cors_allowed_origins) > 0 ? [1] : []
    content {
      allowed_origins = var.cors_allowed_origins
      allowed_methods = ["GET", "PUT", "POST", "DELETE", "HEAD"]
      allowed_headers = ["*"]
      expose_headers  = ["ETag"]
      max_age_seconds = 3000
    }
  }
}

# --- Mailbox outbound relay: Scaleway TEM ------------------------------------
# Registers the sending domain in TEM (ADR-021/026). Its SPF/DKIM/DMARC records
# (outputs) must be published in DNS, after which Scaleway validates the domain
# and outbound sending works. The relay SMTP creds are smtps_auth_user (output)
# + the workload IAM key's secret (which carries TransactionalEmailFullAccess
# when enable_mailbox is set). Validation is deliberately NOT a resource here —
# scaleway_tem_domain_validation blocks until the DNS records exist, which can't
# be true within this same apply.
resource "scaleway_tem_domain" "mail" {
  count      = var.enable_mailbox ? 1 : 0
  name       = var.mail_domain
  accept_tos = true

  lifecycle {
    precondition {
      condition     = var.mail_domain != ""
      error_message = "mail_domain is required when enable_mailbox = true."
    }
  }
}
