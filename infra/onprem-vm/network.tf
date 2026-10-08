data "aws_vpc" "default" {
  default = true
}

# Elastic IP of the service server (created in infra/service-account, tagged
# Name=service-server). It is the only address allowed to SSH into this VM.
data "aws_eip" "service_server" {
  tags = {
    Name = "service-server"
  }
}

resource "aws_security_group" "onprem_vm" {
  name        = "onprem-vm"
  description = "On-prem stand-in VM: SSH from the service server only, HTTP/HTTPS public."
  vpc_id      = data.aws_vpc.default.id

  tags = {
    Name = "onprem-vm"
  }
}

# The service server's adapter connects here to run docker compose.
resource "aws_vpc_security_group_ingress_rule" "ssh_from_service_server" {
  security_group_id = aws_security_group.onprem_vm.id
  description       = "SSH from the service server"
  ip_protocol       = "tcp"
  from_port         = 22
  to_port           = 22
  cidr_ipv4         = "${data.aws_eip.service_server.public_ip}/32"
}

# 80: Let's Encrypt HTTP-01 challenge and redirect to HTTPS. 443: deployed apps.
resource "aws_vpc_security_group_ingress_rule" "http" {
  security_group_id = aws_security_group.onprem_vm.id
  description       = "HTTP"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_ingress_rule" "https" {
  security_group_id = aws_security_group.onprem_vm.id
  description       = "HTTPS"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

# Image pulls (base images, Traefik), package installs and certificate issuance.
resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.onprem_vm.id
  description       = "All outbound"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}
