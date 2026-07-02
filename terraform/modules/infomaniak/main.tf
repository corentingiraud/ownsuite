# Infomaniak Public Cloud (OpenStack) — bare server + object storage for one
# OwnSuite instance. Terraform only provisions: a Debian server reachable by SSH,
# its firewall, a floating IP, and the S3 buckets + keys. `suite bootstrap`
# (Ansible) then turns the server into K3s; Helmfile deploys the apps.

locals {
  # 80/443 must be public (web + ACME http-01). SSH is scoped separately.
  web_ports = var.enable_mailbox ? [80, 443, 25] : [80, 443]

  # Infomaniak S3 endpoint + region (the EC2 credential below authenticates here).
  # `us-east-1` is the compatibility region Infomaniak's S3 reports; data is in CH.
  s3_endpoint = "https://s3.pub1.infomaniak.cloud"
  s3_region   = "us-east-1"
}

# --- Network ----------------------------------------------------------------
resource "openstack_networking_network_v2" "this" {
  name = "${var.name}-net"
}

resource "openstack_networking_subnet_v2" "this" {
  name            = "${var.name}-subnet"
  network_id      = openstack_networking_network_v2.this.id
  cidr            = var.subnet_cidr
  ip_version      = 4
  dns_nameservers = var.dns_nameservers
}

resource "openstack_networking_router_v2" "this" {
  name                = "${var.name}-router"
  external_network_id = data.openstack_networking_network_v2.external.id
}

resource "openstack_networking_router_interface_v2" "this" {
  router_id = openstack_networking_router_v2.this.id
  subnet_id = openstack_networking_subnet_v2.this.id
}

data "openstack_networking_network_v2" "external" {
  name     = var.external_network_name
  external = true
}

# --- Firewall (security group) ----------------------------------------------
resource "openstack_networking_secgroup_v2" "this" {
  name        = "${var.name}-sg"
  description = "OwnSuite: SSH (scoped) + HTTP/HTTPS (+SMTP if Mailbox)."
}

resource "openstack_networking_secgroup_rule_v2" "ssh" {
  # SSH open to ssh_allowed_cidr (default world); narrow it per deploy.
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 22
  port_range_max    = 22
  remote_ip_prefix  = var.ssh_allowed_cidr
  security_group_id = openstack_networking_secgroup_v2.this.id
}

resource "openstack_networking_secgroup_rule_v2" "web" {
  for_each          = toset([for p in local.web_ports : tostring(p)])
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = tonumber(each.value)
  port_range_max    = tonumber(each.value)
  remote_ip_prefix  = "0.0.0.0/0"
  security_group_id = openstack_networking_secgroup_v2.this.id
}

# Meet (LiveKit) media, open only when enable_meet: one muxed UDP port (7882) plus a
# TCP fallback (7881) — the ADR-027 non-HTTP-port precedent extended to UDP.
resource "openstack_networking_secgroup_rule_v2" "meet" {
  for_each = var.enable_meet ? {
    meet-tcp = { port = 7881, protocol = "tcp" }
    meet-udp = { port = 7882, protocol = "udp" }
  } : {}
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = each.value.protocol
  port_range_min    = each.value.port
  port_range_max    = each.value.port
  remote_ip_prefix  = "0.0.0.0/0"
  security_group_id = openstack_networking_secgroup_v2.this.id
}

# Optional embedded TURN/TLS (enable_meet_turn, issue #55): 5349/tcp for Meet clients
# behind firewalls blocking both 7881 and 7882. Off by default (extra port + a cert);
# set alongside OWNSUITE_MEET_TURN=true on the app side.
resource "openstack_networking_secgroup_rule_v2" "meet_turn" {
  for_each = var.enable_meet_turn ? {
    meet-turn = { port = 5349, protocol = "tcp" }
  } : {}
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = each.value.protocol
  port_range_min    = each.value.port
  port_range_max    = each.value.port
  remote_ip_prefix  = "0.0.0.0/0"
  security_group_id = openstack_networking_secgroup_v2.this.id
}

# Egress is left to Neutron's defaults: creating a security group auto-adds
# allow-all egress rules (IPv4 + IPv6), so re-declaring them here 409s on
# Infomaniak ("SecurityGroupRuleExists"). The node can pull images, reach S3,
# and serve ACME out of the box.

# --- Server -----------------------------------------------------------------
resource "openstack_compute_keypair_v2" "this" {
  name       = "${var.name}-key"
  public_key = var.ssh_public_key
}

data "openstack_images_image_v2" "debian" {
  name        = var.image_name
  most_recent = true
}

# Explicit port so the security group attaches at the network layer and the
# floating IP can target it (the compute-side floatingip helpers were removed in
# the openstack provider v3).
resource "openstack_networking_port_v2" "this" {
  name               = "${var.name}-port"
  network_id         = openstack_networking_network_v2.this.id
  admin_state_up     = true
  security_group_ids = [openstack_networking_secgroup_v2.this.id]

  fixed_ip {
    subnet_id = openstack_networking_subnet_v2.this.id
  }
}

resource "openstack_compute_instance_v2" "this" {
  name        = var.name
  flavor_name = var.flavor_name
  key_pair    = openstack_compute_keypair_v2.this.name

  # Diskless flavor → boot from a sized volume built from the image.
  block_device {
    uuid                  = data.openstack_images_image_v2.debian.id
    source_type           = "image"
    destination_type      = "volume"
    volume_size           = var.volume_size_gb
    boot_index            = 0
    delete_on_termination = true
  }

  network {
    port = openstack_networking_port_v2.this.id
  }
}

resource "openstack_networking_floatingip_v2" "this" {
  pool = var.external_network_name
}

resource "openstack_networking_floatingip_associate_v2" "this" {
  floating_ip = openstack_networking_floatingip_v2.this.address
  port_id     = openstack_networking_port_v2.this.id

  # Outbound routing needs the subnet attached to the router first.
  depends_on = [openstack_networking_router_interface_v2.this]
}

# --- Object storage ---------------------------------------------------------
# S3 access/secret keys for the apps (rclone, CNPG Barman, app media clients).
resource "openstack_identity_ec2_credential_v3" "s3" {}

# Buckets are created through the S3 API, NOT as Swift containers: on Infomaniak
# the two are separate namespaces and a Swift container is invisible to the S3
# endpoint (list_buckets returns [], GetObject 404s). The aws provider below
# authenticates to the Infomaniak S3 endpoint with the EC2 credential just minted.
#
# `bucket_names` defaults to [] because the recommended Infomaniak mode is `garage`
# (in-cluster), where Garage creates the media buckets itself. Set it only for an
# external-S3 primary or for the off-site backup store (a second module instance).
provider "aws" {
  access_key = openstack_identity_ec2_credential_v3.s3.access
  secret_key = openstack_identity_ec2_credential_v3.s3.secret
  region     = local.s3_region

  # Talk to Infomaniak's S3, not AWS, and skip every AWS-account/STS preflight.
  s3_use_path_style           = true
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
  skip_region_validation      = true

  endpoints {
    s3 = local.s3_endpoint
  }
}

resource "aws_s3_bucket" "this" {
  for_each = toset(var.bucket_names)
  bucket   = each.value
}
