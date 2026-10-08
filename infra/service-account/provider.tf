provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = "tmb"
      Component = "service-account"
      ManagedBy = "terraform"
    }
  }
}
