# Infomaniak Public Cloud (OpenStack) — bare server + object storage for one
# OwnSuite instance. Terraform only provisions: a Debian server reachable by SSH,
# its firewall, a floating IP, and the S3 buckets + keys. `suite bootstrap`
# (Ansible) then turns the server into K3s; Helmfile deploys the apps.

locals {
  # 80/443 must be public (web + ACME http-01). SSH is scoped separately.
  web_ports = var.enable_mailbox ? [80, 443, 25] : [80, 443]
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
  # ponytail: SSH open to ssh_allowed_cidr (default world); narrow it per deploy.
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

# A fresh security group has no egress rules — re-add allow-all so the node can
# pull images, reach S3, and serve ACME.
resource "openstack_networking_secgroup_rule_v2" "egress_v4" {
  direction         = "egress"
  ethertype         = "IPv4"
  security_group_id = openstack_networking_secgroup_v2.this.id
}

resource "openstack_networking_secgroup_rule_v2" "egress_v6" {
  direction         = "egress"
  ethertype         = "IPv6"
  security_group_id = openstack_networking_secgroup_v2.this.id
}

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

# --- Object storage (Swift containers = S3 buckets) -------------------------
resource "openstack_objectstorage_container_v1" "this" {
  for_each = toset(var.bucket_names)
  name     = each.value
}

# S3 access/secret keys for the apps (rclone, CNPG Barman, app media clients).
resource "openstack_identity_ec2_credential_v3" "s3" {}
