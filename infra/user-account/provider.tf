# 서비스 서버가 사용자 계정의 온보딩 역할(AssumeRole)로 이 모듈을 실행한다.
# 사용자의 액세스 키는 어디에도 없다. external_id는 서비스가 환경마다 만든 값이고,
# 환경변수 TF_VAR_external_id로 넘긴다(명령줄 인자나 .tfvars 파일에 쓰지 않는다).
locals {
  # role_arn의 계정 ID. 다른 계정에 잘못 적용하는 사고를 막는 데 쓴다.
  account_id = regex("^arn:aws:iam::([0-9]{12}):role/", var.role_arn)[0]
}

provider "aws" {
  region = var.region

  # 역할을 AssumeRole한 결과가 이 계정이 아니면 provider가 실행을 거부한다.
  allowed_account_ids = [local.account_id]

  assume_role {
    role_arn     = var.role_arn
    external_id  = var.external_id
    session_name = "anyship-foundation-${var.env_id}"
    duration     = "1h" # apply가 길어져도 한 번의 임시 자격 증명 안에서 끝나야 한다
  }

  default_tags {
    tags = {
      Project   = "anyship"
      Component = "foundation"
      EnvId     = var.env_id
      ManagedBy = "terraform"
    }
  }
}
