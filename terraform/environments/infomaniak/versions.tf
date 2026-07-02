terraform {
  required_version = ">= 1.9"

  required_providers {
    openstack = {
      source  = "terraform-provider-openstack/openstack"
      version = "~> 3.0"
    }
  }

  # local state for a single-instance personal deploy. Switch to the
  # OpenStack Swift backend (an object-storage container) for team/remote state:
  #   backend "swift" { container = "ownsuite-tfstate" ... }
}

# Auth comes from the environment — never put OpenStack credentials in tfvars.
# Set up an application credential and reference its clouds.yaml entry by name,
# or export OS_* env vars. See terraform.tfvars.example.
provider "openstack" {
  cloud = var.openstack_cloud
}
