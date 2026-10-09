locals {
  name = "anyship-${var.env_id}"

  # 서로 다른 AZ 2개. 이름은 리전에서 조회하므로 리전이 바뀌어도 코드를 고치지 않는다.
  azs = slice(data.aws_availability_zones.available.names, 0, 2)

  # VPC를 16등분해 앞쪽 2개는 퍼블릭(호스트), 뒤쪽 2개는 프라이빗(RDS)으로 쓴다.
  public_cidrs  = [for i in range(2) : cidrsubnet(var.vpc_cidr, 4, i)]
  private_cidrs = [for i in range(2) : cidrsubnet(var.vpc_cidr, 4, i + 2)]
}

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true # RDS 엔드포인트 이름 확인에 필요하다

  tags = { Name = local.name }
}

# 기본 보안 그룹은 모든 규칙을 비워 둔다. 실수로 붙은 리소스가 열려 있지 않게 하는 안전장치다.
resource "aws_default_security_group" "default" {
  vpc_id = aws_vpc.main.id
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = { Name = local.name }
}

# --- 서브넷 ---

# 퍼블릭: 앱 호스트. 공인 IP는 탄력적 IP로 붙이므로 자동 할당은 끈다.
resource "aws_subnet" "public" {
  count = 2

  vpc_id                  = aws_vpc.main.id
  cidr_block              = local.public_cidrs[count.index]
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = false

  tags = { Name = "${local.name}-public-${count.index}" }
}

# 프라이빗: RDS. NAT가 없으므로 인터넷으로 나가는 경로 자체가 없다.
resource "aws_subnet" "private" {
  count = 2

  vpc_id            = aws_vpc.main.id
  cidr_block        = local.private_cidrs[count.index]
  availability_zone = local.azs[count.index]

  tags = { Name = "${local.name}-private-${count.index}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "${local.name}-public" }
}

# 프라이빗 라우트 테이블은 VPC 내부 경로(local)만 갖는다.
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  tags = { Name = "${local.name}-private" }
}

resource "aws_route_table_association" "public" {
  count = 2

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "private" {
  count = 2

  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# --- 보안 그룹 ---

resource "aws_security_group" "host" {
  name        = "${local.name}-host"
  description = "App host: web from anywhere, SSH from the service server only"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name}-host" }
}

resource "aws_vpc_security_group_ingress_rule" "host_http" {
  security_group_id = aws_security_group.host.id
  description       = "HTTP (Traefik, HTTP-01 challenge)"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_ingress_rule" "host_https" {
  security_group_id = aws_security_group.host.id
  description       = "HTTPS (Traefik)"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_ingress_rule" "host_ssh" {
  security_group_id = aws_security_group.host.id
  description       = "SSH from the service server only"
  ip_protocol       = "tcp"
  from_port         = 22
  to_port           = 22
  cidr_ipv4         = "${var.service_server_ip}/32"
}

# 이미지 pull, 인증서 발급, OS 업데이트가 필요하므로 나가는 쪽은 모두 허용한다.
resource "aws_vpc_security_group_egress_rule" "host_all" {
  security_group_id = aws_security_group.host.id
  description       = "All outbound"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

# RDS는 호스트 보안 그룹에서 오는 5432만 받는다. 나가는 규칙은 두지 않는다.
resource "aws_security_group" "db" {
  name        = "${local.name}-db"
  description = "RDS PostgreSQL: reachable from the app host only"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name}-db" }
}

resource "aws_vpc_security_group_ingress_rule" "db_from_host" {
  security_group_id            = aws_security_group.db.id
  description                  = "PostgreSQL from the app host"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  referenced_security_group_id = aws_security_group.host.id
}
