terraform {
  # Works with Terraform >= 1.9 and OpenTofu >= 1.9.
  required_version = ">= 1.9"

  required_providers {
    openstack = {
      source  = "terraform-provider-openstack/openstack"
      version = "~> 3.0"
    }
    # Used only to create S3 buckets through the S3 API (see main.tf): Swift
    # containers are a separate namespace on Infomaniak and are NOT visible to
    # the S3 endpoint the apps and backups use.
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}
