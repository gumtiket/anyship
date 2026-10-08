terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # The bucket is created by hand (it must exist before `terraform init`).
  # use_lockfile = S3 native locking, no DynamoDB table needed.
  backend "s3" {
    bucket       = "tmb-tfstate"
    key          = "service-account/terraform.tfstate"
    region       = "ap-northeast-2"
    encrypt      = true
    use_lockfile = true
  }
}
