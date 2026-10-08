variable "region" {
  description = "AWS region for the service account resources."
  type        = string
  default     = "ap-northeast-2"
}

variable "instance_type" {
  description = "Instance type of the service server. Image builds and the verification gate run here."
  type        = string
  default     = "t3.medium"
}

variable "root_volume_size" {
  description = "Root volume size in GiB. Growing it later is easy, shrinking is not."
  type        = number
  default     = 30
}
