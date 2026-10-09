terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # state는 서비스 계정의 버킷에 두고(사용자가 역할을 지워도 destroy할 수 있게),
  # 환경마다 key를 달리한다. key는 환경마다 다르므로 여기에 쓰지 않고 init할 때 넘긴다.
  #
  #   terraform init -backend-config="key=users/<계정ID>/<환경ID>/foundation.tfstate"
  #
  # 이 backend는 서비스 서버의 인스턴스 역할로 접근한다(사용자 계정 역할이 아니다).
  # 버킷은 서비스 계정 기반에서 만든 것을 그대로 쓰고, use_lockfile은 S3 자체 잠금이다.
  backend "s3" {
    bucket       = "tmb-tfstate"
    region       = "ap-northeast-2"
    encrypt      = true
    use_lockfile = true
  }
}
