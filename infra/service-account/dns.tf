# The public hosted zone was created by hand in the console (the domain is
# registered at Gabia and delegated to these Route 53 name servers).
data "aws_route53_zone" "main" {
  name         = "anyship.cloud."
  private_zone = false
}

# The service creates one wildcard record per registered environment
# (*.<env-id>.onprem.anyship.cloud -> that server's public IP) and removes it
# when the environment is deleted. No human adds records per server.
#
# Scope: this one zone, A records, UPSERT/DELETE only.
# TODO: also restrict record names with the condition key
# route53:ChangeResourceRecordSetsNormalizedRecordNames so the service server
# cannot touch records like app.anyship.cloud.
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
