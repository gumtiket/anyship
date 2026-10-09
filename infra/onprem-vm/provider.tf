provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = "tmb"
      Component = "onprem-vm"
      ManagedBy = "terraform"
    }
  }
}
