terraform {
  # Works with Terraform >= 1.9 and OpenTofu >= 1.9.
  required_version = ">= 1.9"

  required_providers {
    # Scaleway has first-class compute + object-storage + IAM resources, so
    # a single provider covers the host and S3 — no second (aws) provider.
    scaleway = {
      source  = "scaleway/scaleway"
      version = "~> 2.77"
    }
  }
}
