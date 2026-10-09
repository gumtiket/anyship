#!/usr/bin/env bash
# 서비스 서버에서 사용자 계정의 역할을 AssumeRole한 뒤, 그 임시 자격 증명으로만 terraform을 실행한다.
# 서비스가 만들 Terraform 실행기의 시험판이다. 자격 증명을 export하거나 파일·출력에 남기지 않는다.
#
#   ROLE_ARN=arn:aws:iam::<사용자 계정 ID>:role/deploy-service-role \
#   EXTERNAL_ID=<External ID> \
#   ./tf.sh init -reconfigure -backend-config="bucket=..." -backend-config="region=..." -backend-config="key=<환경ID>/foundation.tfstate"
#
#   ./tf.sh plan -var-file=test.tfvars    # 같은 ROLE_ARN, EXTERNAL_ID를 줘야 한다
set -euo pipefail

: "${ROLE_ARN:?ROLE_ARN을 지정하세요}"
: "${EXTERNAL_ID:?EXTERNAL_ID를 지정하세요}"

if [ "$#" -eq 0 ]; then
  echo "사용법: ./tf.sh <terraform 하위 명령과 인자>" >&2
  exit 2
fi

# 세션 이름은 CloudTrail에 남는다. 값은 한 번만 쓰고 이 셸 변수에만 둔다.
read -r ak sk st < <(aws sts assume-role \
  --role-arn "$ROLE_ARN" \
  --role-session-name "terraform-$(date +%s)" \
  --external-id "$EXTERNAL_ID" \
  --duration-seconds 3600 \
  --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' \
  --output text)

# 이 한 명령에만 환경변수로 전달한다. 서비스 서버의 기본 자격 증명으로 되돌아가지 않도록,
# 프로세스 환경에 남아 있을 수 있는 다른 자격 증명 설정은 비운다.
AWS_ACCESS_KEY_ID="$ak" AWS_SECRET_ACCESS_KEY="$sk" AWS_SESSION_TOKEN="$st" \
  AWS_PROFILE="" AWS_SHARED_CREDENTIALS_FILE=/dev/null \
  terraform "$@"
