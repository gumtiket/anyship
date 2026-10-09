# Same x86_64 Amazon Linux 2023 as the service server, so one image runs on
# every target.
data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

data "aws_subnet" "default" {
  vpc_id            = data.aws_vpc.default.id
  availability_zone = "${var.region}a"
  default_for_az    = true
}

# First-boot setup: scripts/setup.sh runs once through cloud-init and registers
# the service server's PUBLIC key for the "deploy" account. A public key is not
# a secret, so it is fine that user_data is readable from the metadata service.
locals {
  user_data = <<-EOT
    #!/bin/bash
    export DEPLOY_PUBLIC_KEY='${trimspace(var.ssh_public_key)}'
    ${file("${path.module}/scripts/setup.sh")}
  EOT
}

# Stand-in for an on-prem server. It deliberately has NO instance profile:
# no IAM role, so no AWS credentials exist on this machine. The adapter only
# needs SSH and Docker, exactly as it would for a real on-prem server.
resource "aws_instance" "onprem_vm" {
  ami                    = data.aws_ssm_parameter.al2023.value
  instance_type          = var.instance_type
  subnet_id              = data.aws_subnet.default.id
  vpc_security_group_ids = [aws_security_group.onprem_vm.id]

  # Runs once on first boot, so a change must replace the VM.
  user_data                   = local.user_data
  user_data_replace_on_change = true

  # IMDSv2 only. The metadata service stays enabled because cloud-init reads
  # user_data from it; with no instance profile it has no credentials to give.
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_size
    encrypted             = true
    delete_on_termination = true
  }

  tags = {
    Name = "onprem-vm"
  }

  lifecycle {
    # A newer "latest" AMI must not replace the running VM.
    ignore_changes = [ami]
  }
}

resource "aws_eip" "onprem_vm" {
  domain   = "vpc"
  instance = aws_instance.onprem_vm.id

  tags = {
    Name = "onprem-vm"
  }
}
