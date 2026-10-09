# 서비스와 이후 세트(EC2, Lambda)가 읽는 값이다. 비밀은 하나도 없다.
# 마스터 비밀번호 자체가 아니라, 그것이 든 Secrets Manager 비밀의 ARN만 내보낸다.

# --- 앱 호스트 ---

output "host_public_ip" {
  description = "앱 호스트의 탄력적 IP. DNS(*.aws.<도메인>)가 가리키고, 서비스 서버가 SSH로 접속한다."
  value       = aws_eip.host.public_ip
}

output "host_instance_id" {
  description = "앱 호스트 인스턴스 ID."
  value       = aws_instance.host.id
}

# --- 데이터베이스 ---

output "db_address" {
  description = "RDS 엔드포인트 호스트 이름(포트 제외). 프라이빗이라 VPC 안에서만 닿는다."
  value       = aws_db_instance.main.address
}

output "db_port" {
  description = "RDS 포트."
  value       = aws_db_instance.main.port
}

output "db_master_secret_arn" {
  description = "RDS가 관리하는 마스터 계정 비밀의 ARN. 앱 DB와 전용 계정을 만들 때 읽는다."
  value       = aws_db_instance.main.master_user_secret[0].secret_arn
}

# --- 네트워크 (Lambda 세트가 VPC 연결에 쓴다) ---

output "vpc_id" {
  description = "새로 만든 VPC의 ID."
  value       = aws_vpc.main.id
}

output "public_subnet_ids" {
  description = "퍼블릭 서브넷 ID. 앱 호스트가 첫 번째에 있다."
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "프라이빗 서브넷 ID. RDS가 있고, Lambda를 VPC에 붙일 때 쓴다."
  value       = aws_subnet.private[*].id
}

output "host_security_group_id" {
  description = "앱 호스트 보안 그룹. RDS는 이 그룹에서 오는 5432만 받는다."
  value       = aws_security_group.host.id
}

output "db_security_group_id" {
  description = "RDS 보안 그룹. Lambda 세트는 이 그룹에 자신의 보안 그룹을 허용하는 규칙을 더해야 한다."
  value       = aws_security_group.db.id
}
