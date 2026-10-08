# Latest Amazon Linux 2023 (x86_64). x86_64 everywhere so one image runs on
# every target (EC2 host, on-prem VM, Lambda).
data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

# Fixed AZ so the chosen subnet is deterministic between runs.
data "aws_subnet" "default" {
  vpc_id            = data.aws_vpc.default.id
  availability_zone = "${var.region}a"
  default_for_az    = true
}

# Admin access goes through SSM Session Manager, no SSH port is opened.
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.service_server.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "service_server" {
  name = "service-server"
  role = aws_iam_role.service_server.name
}

resource "aws_instance" "service_server" {
  ami                    = data.aws_ssm_parameter.al2023.value
  instance_type          = var.instance_type
  subnet_id              = data.aws_subnet.default.id
  vpc_security_group_ids = [aws_security_group.service_server.id]
  iam_instance_profile   = aws_iam_instance_profile.service_server.name

  # Runs once on first boot, so a change must replace the instance.
  user_data                   = file("${path.module}/scripts/user_data.sh")
  user_data_replace_on_change = true

  # IMDSv2 only, hop limit 1: containers (image builds, verification gate)
  # cannot reach the instance role credentials through the metadata service.
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
    Name = "service-server"
  }

  lifecycle {
    # A newer "latest" AMI must not replace the running server.
    ignore_changes = [ami]
  }
}

resource "aws_eip" "service_server" {
  domain   = "vpc"
  instance = aws_instance.service_server.id

  tags = {
    Name = "service-server"
  }
}
