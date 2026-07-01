terraform {
  # Works with Terraform >= 1.9 and OpenTofu >= 1.9.
  required_version = ">= 1.9"

  required_providers {
    # Scaleway has first-class compute + object-storage + IAM resources, so
    # unlike the Infomaniak module there is no second (aws) provider for S3.
    scaleway = {
      source  = "scaleway/scaleway"
      version = "~> 2.77"
    }
  }
}
