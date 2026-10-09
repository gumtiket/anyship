# 서비스 서버, 온프레미스 VM과 같은 x86_64 Amazon Linux 2023. 어떤 대상이든 같은 이미지가 돈다.
# AMI ID를 쓰지 않고 SSM 공개 파라미터를 읽으므로 리전이 바뀌어도 코드를 고치지 않는다.
data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

# 첫 부팅 때 cloud-init이 한 번 실행한다.
#   1. setup.sh: Docker, Compose, 서비스 서버만 로그인할 수 있는 deploy 계정 (온프레미스와 같은 스크립트)
#   2. Traefik 시작: 어댑터가 /opt/apps/traefik 의 Compose 프로젝트 "traefik"을 기대한다
# 둘 다 비밀이 없다. 공개 키와 이메일 주소뿐이라 user_data가 메타데이터에 보여도 괜찮다.
locals {
  setup_script    = file("${path.module}/../onprem-vm/scripts/setup.sh")
  traefik_compose = file("${path.module}/../sets/onprem/compose/traefik/compose.yaml")

  user_data = <<-EOT
    #!/bin/bash
    export DEPLOY_PUBLIC_KEY='${trimspace(var.ssh_public_key)}'
    ${local.setup_script}

    # --- Traefik 자동 시작 (인증서는 staging CA가 기본값) ---
    install -d -m 755 -o deploy -g deploy /opt/apps/traefik
    echo '${base64encode(local.traefik_compose)}' | base64 -d > /opt/apps/traefik/compose.yaml
    printf 'ACME_EMAIL=%s\n' '${var.acme_email}' > /opt/apps/traefik/.env
    chown deploy:deploy /opt/apps/traefik/compose.yaml /opt/apps/traefik/.env
    runuser -u deploy -- bash -c 'cd /opt/apps/traefik && docker compose up -d'
  EOT
}

# 인스턴스 프로파일이 없다. 호스트에는 AWS 자격 증명이 없고, 이미지는 서비스 서버가 SSH로 보낸다.
# 앱 컨테이너가 침해되어도 가져갈 수 있는 AWS 권한이 없다.
resource "aws_instance" "host" {
  ami                    = data.aws_ssm_parameter.al2023.value
  instance_type          = var.host_instance_type
  subnet_id              = aws_subnet.public[0].id
  vpc_security_group_ids = [aws_security_group.host.id]

  # 첫 부팅에 한 번만 실행되므로 내용이 바뀌면 호스트를 교체해야 한다.
  user_data                   = local.user_data
  user_data_replace_on_change = true

  # IMDSv2 필수 + 홉 제한 1: 컨테이너 안에서는 메타데이터 서비스에 닿지 못한다.
  # cloud-init이 user_data를 읽어야 하므로 메타데이터 서비스 자체는 켜 둔다.
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.host_volume_size
    encrypted             = true
    delete_on_termination = true
  }

  tags = { Name = "${local.name}-host" }

  lifecycle {
    # 더 새로운 "latest" AMI가 나와도 실행 중인 호스트를 교체하지 않는다.
    ignore_changes = [ami]
  }
}

# DNS(*.aws.anyship.cloud)가 가리킬 고정 주소. 호스트를 교체해도 이 주소는 유지된다.
resource "aws_eip" "host" {
  domain   = "vpc"
  instance = aws_instance.host.id

  tags = { Name = "${local.name}-host" }

  # IGW가 붙어 있어야 퍼블릭 서브넷의 인스턴스에 탄력적 IP를 연결할 수 있다.
  depends_on = [aws_internet_gateway.main]
}
