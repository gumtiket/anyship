data "aws_vpc" "default" {
  default = true
}

resource "aws_security_group" "service_server" {
  name        = "service-server"
  description = "Service server: public HTTP/HTTPS only. No SSH, admin access is via SSM Session Manager."
  vpc_id      = data.aws_vpc.default.id

  tags = {
    Name = "service-server"
  }
}

# 80: Let's Encrypt HTTP-01 challenge and redirect to HTTPS. 443: service UI.
resource "aws_vpc_security_group_ingress_rule" "http" {
  security_group_id = aws_security_group.service_server.id
  description       = "HTTP"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_ingress_rule" "https" {
  security_group_id = aws_security_group.service_server.id
  description       = "HTTPS"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

# The server must reach package mirrors, Docker registries, GitHub, STS/ECR/
# Bedrock endpoints and SSH (22) on deploy targets.
resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.service_server.id
  description       = "All outbound"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}
