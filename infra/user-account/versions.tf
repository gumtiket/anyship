terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # state는 사용자 계정의 버킷(온보딩 스택이 만든 것)에 둔다. 버킷 이름, 리전, key는
  # 사용자와 환경마다 다르므로 여기에 쓰지 않고 init할 때 넘긴다.
  #
  #   terraform init \
  #     -backend-config="bucket=<스택 출력 StateBucketName>" \
  #     -backend-config="region=<버킷의 리전>" \
  #     -backend-config="key=<환경ID>/foundation.tfstate"
  #
  # backend와 provider는 같은 자격 증명을 쓴다. 서비스가 사용자 계정 역할을 AssumeRole해서
  # 받은 임시 자격 증명을 AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN
  # 환경변수로만 넘긴다. Terraform은 External ID를 알 필요가 없다.
  backend "s3" {
    encrypt      = true
    use_lockfile = true # S3 자체 잠금. 같은 환경의 동시 apply를 막는다
  }
}
