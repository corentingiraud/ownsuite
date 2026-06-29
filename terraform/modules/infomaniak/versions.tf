terraform {
  # Works with Terraform >= 1.9 and OpenTofu >= 1.9.
  required_version = ">= 1.9"

  required_providers {
    openstack = {
      source  = "terraform-provider-openstack/openstack"
      version = "~> 3.0"
    }
  }
}
