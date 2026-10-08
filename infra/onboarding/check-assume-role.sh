#!/usr/bin/env bash
# Verifies the cross-account role from the service server (or any principal the
# trust policy allows).
#   ROLE_ARN=arn:aws:iam::<user-account>:role/deploy-service-role \
#   EXTERNAL_ID=<external id> ./check-assume-role.sh
# Credentials are only passed to the sub-commands below, never exported.
set -euo pipefail

: "${ROLE_ARN:?set ROLE_ARN}"
: "${EXTERNAL_ID:?set EXTERNAL_ID}"

echo "caller: $(aws sts get-caller-identity --query Arn --output text)"

echo "[1/2] assume with External ID (expect success)"
read -r ak sk st < <(aws sts assume-role \
  --role-arn "$ROLE_ARN" \
  --role-session-name "onboarding-check-$(date +%s)" \
  --external-id "$EXTERNAL_ID" \
  --duration-seconds 900 \
  --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' \
  --output text)
AWS_ACCESS_KEY_ID="$ak" AWS_SECRET_ACCESS_KEY="$sk" AWS_SESSION_TOKEN="$st" \
  aws sts get-caller-identity --query '[Account,Arn]' --output text

echo "[2/2] assume without External ID (expect AccessDenied)"
if aws sts assume-role --role-arn "$ROLE_ARN" \
     --role-session-name "onboarding-negative-$(date +%s)" \
     --duration-seconds 900 >/dev/null 2>&1; then
  echo "FAIL: role can be assumed without External ID; check the trust policy condition" >&2
  exit 1
fi
echo "OK: denied as expected"
