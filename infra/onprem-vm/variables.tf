variable "region" {
  description = "AWS region. The VM stands in for an on-prem server but lives in the service account."
  type        = string
  default     = "ap-northeast-2"
}

variable "instance_type" {
  description = "Instance type of the on-prem stand-in VM."
  type        = string
  default     = "t3.small"
}

variable "ssh_public_key" {
  description = "Public key of the service server's deploy key (ssh-ed25519 ...). Public keys are not secret, but never put a private key here."
  type        = string

  validation {
    # Strict on purpose: the value is placed inside single quotes in a shell script.
    condition     = can(regex("^ssh-ed25519 [A-Za-z0-9+/=]+( [A-Za-z0-9._@-]+)?$", trimspace(var.ssh_public_key)))
    error_message = "ssh_public_key must be a single ssh-ed25519 PUBLIC key line: \"ssh-ed25519 <key> [comment]\"."
  }
}

variable "root_volume_size" {
  description = "Root volume size in GiB."
  type        = number
  default     = 20
}
