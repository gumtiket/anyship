# The public hosted zone was created by hand in the console (the domain is
# registered at Gabia and delegated to these Route 53 name servers).
data "aws_route53_zone" "main" {
  name         = "anyship.cloud."
  private_zone = false
}

# The service creates one wildcard record per registered environment and removes
# it when the environment is deleted. No human adds records per server:
#   *.<env-id>.onprem.anyship.cloud -> the user's own server (onprem set)
#   *.<env-id>.aws.anyship.cloud    -> the host of the user's AWS foundation (aws sets)
#
# Scope: this one zone, A records, UPSERT/DELETE only, and only record names of
# the two forms above, so the service server cannot touch records like
# www.anyship.cloud. The scopes must match SCOPES in
# infra/adapters/anyship_adapters/dns.py.
#
# Route 53 normalizes names before checking this condition: lowercase, and the
# wildcard "*" becomes "\052" (the same form the API returns). Whether the
# normalized name ends with a dot is not certain from the docs, so both forms
# are allowed; both stay under onprem.anyship.cloud or aws.anyship.cloud. Verify
# with infra/adapters/scripts/check_dns_policy.py after every apply.
locals {
  env_record_name_patterns = [
    "\\052.*.onprem.anyship.cloud",
    "\\052.*.onprem.anyship.cloud.",
    "\\052.*.aws.anyship.cloud",
    "\\052.*.aws.anyship.cloud.",
  ]
}

resource "aws_iam_role_policy" "route53_env_records" {
  name = "route53-env-records"
  role = aws_iam_role.service_server.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ChangeEnvRecords"
        Effect   = "Allow"
        Action   = ["route53:ChangeResourceRecordSets"]
        Resource = "arn:aws:route53:::hostedzone/${data.aws_route53_zone.main.zone_id}"
        Condition = {
          "ForAllValues:StringEquals" = {
            "route53:ChangeResourceRecordSetsRecordTypes" = ["A"]
            "route53:ChangeResourceRecordSetsActions"     = ["UPSERT", "DELETE"]
          }
          "ForAllValues:StringLike" = {
            "route53:ChangeResourceRecordSetsNormalizedRecordNames" = local.env_record_name_patterns
          }
        }
      },
      {
        Sid    = "ReadZone"
        Effect = "Allow"
        Action = [
          "route53:ListResourceRecordSets",
          "route53:GetHostedZone",
        ]
        Resource = "arn:aws:route53:::hostedzone/${data.aws_route53_zone.main.zone_id}"
      },
      {
        Sid      = "WaitForChange"
        Effect   = "Allow"
        Action   = ["route53:GetChange"]
        Resource = "arn:aws:route53:::change/*"
      },
      {
        Sid      = "FindZoneByName"
        Effect   = "Allow"
        Action   = ["route53:ListHostedZonesByName"]
        Resource = "*"
      },
    ]
  })
}
