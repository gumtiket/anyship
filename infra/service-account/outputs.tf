output "service_role_arn" {
  description = "ARN of the service server role. Goes into the onboarding link (ServiceRoleArn)."
  value       = aws_iam_role.service_server.arn
}
