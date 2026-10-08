data "aws_caller_identity" "current" {}

# The role was created by hand while testing the onboarding template (#2).
# Its ARN is referenced by the trust policy in every user account, so it must
# never be recreated: import it and keep it protected.
import {
  to = aws_iam_role.service_server
  id = "service-server"
}

import {
  to = aws_iam_role_policy.assume_deploy_role
  id = "service-server:assume-deploy-role"
}

resource "aws_iam_role" "service_server" {
  name = "service-server"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Used by the service server EC2 instance (instance profile, step 4).
        Sid       = "Ec2"
        Effect    = "Allow"
        Principal = { Service = "ec2.amazonaws.com" }
        Action    = "sts:AssumeRole"
      },
      {
        # Kept from the manual test setup so CloudShell can still assume this
        # role. TODO: remove once the service server is up.
        Sid       = "TestFromThisAccount"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "sts:AssumeRole"
      },
    ]
  })

  lifecycle {
    prevent_destroy = true
  }
}

# Lets the service server assume the deploy role in user accounts. The user
# account's trust policy (External ID) is the real gate.
# TODO: narrow Resource to registered user account IDs.
resource "aws_iam_role_policy" "assume_deploy_role" {
  name = "assume-deploy-role"
  role = aws_iam_role.service_server.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "sts:AssumeRole"
      Resource = "arn:aws:iam::*:role/deploy-service-role"
    }]
  })
}
