terraform {
  required_version = ">= 1.9"

  required_providers {
    scaleway = {
      source  = "scaleway/scaleway"
      version = "~> 2.77"
    }
  }

  # ponytail: local state for a single-instance personal deploy. Switch to the
  # Scaleway Object Storage (S3) backend for team/remote state:
  #   backend "s3" { bucket = "ownsuite-tfstate" endpoints = { s3 = "https://s3.fr-par.scw.cloud" } ... }
}

# Credentials come from the environment — never put the secret key in tfvars.
# Export SCW_ACCESS_KEY / SCW_SECRET_KEY (an IAM API key), or use
# ~/.config/scw/config.yaml. region/zone/project_id are set here from vars.
provider "scaleway" {
  region          = var.region
  zone            = var.zone
  project_id      = var.project_id
  organization_id = var.organization_id
}
