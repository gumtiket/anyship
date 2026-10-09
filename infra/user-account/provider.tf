# 사용자 계정에서 실행한다. 자격 증명은 환경변수로 들어온다(versions.tf 참고).
# 이 파일에는 역할 ARN도 External ID도 없다.
provider "aws" {
  region = var.region

  # 자격 증명이 가리키는 계정이 var.account_id가 아니면 provider가 실행을 거부한다.
  # 다른 계정(예: 서비스 계정)에 잘못 적용하는 사고를 막는 안전장치다.
  allowed_account_ids = [var.account_id]

  default_tags {
    tags = {
      Project   = "anyship"
      Component = "foundation"
      EnvId     = var.env_id
      ManagedBy = "terraform"
    }
  }
}
