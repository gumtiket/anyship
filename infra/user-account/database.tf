# RDS는 프라이빗 서브넷 2개(서로 다른 AZ)에 걸친 서브넷 그룹에 둔다.
# 인터넷으로 나가는 경로가 없고, 보안 그룹은 앱 호스트의 5432만 받는다(network.tf).
resource "aws_db_subnet_group" "main" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id

  tags = { Name = local.name }
}

# 모든 앱이 공유하는 PostgreSQL. 앱별 DB와 전용 계정은 배포 때 호스트에서 만든다.
# 여기서는 인스턴스만 만들고, 앱 DB는 만들지 않는다(db_name 생략).
resource "aws_db_instance" "main" {
  identifier     = "${local.name}-db"
  engine         = "postgres"
  engine_version = "16" # 마이너 버전은 AWS가 고른다
  instance_class = var.db_instance_class

  allocated_storage = var.db_allocated_storage
  storage_type      = "gp3"
  storage_encrypted = true

  # 마스터 계정만 둔다. 비밀번호는 코드, 변수, state에 평문으로 들어가지 않고
  # Secrets Manager가 만들고 관리한다(secret ARN은 outputs.tf에서 내보낸다).
  username                    = "anyship_admin"
  manage_master_user_password = true

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false
  multi_az               = false # MVP는 단일 AZ. 운영 수준이 필요하면 후속에서 켠다

  backup_retention_period    = 1 # 하루치 자동 백업
  auto_minor_version_upgrade = true
  copy_tags_to_snapshot      = true

  # 시험 환경이라 destroy가 막히지 않게 한다. 실제 사용자 환경으로 쓰기 전에
  # deletion_protection = true, skip_final_snapshot = false로 바꾼다.
  deletion_protection = false
  skip_final_snapshot = true

  tags = { Name = "${local.name}-db" }

  lifecycle {
    # AWS가 올린 마이너 버전을 "변경"으로 보고 되돌리려 하지 않게 한다.
    ignore_changes = [engine_version]
  }
}
