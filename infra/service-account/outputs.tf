output "service_role_arn" {
  description = "ARN of the service server role. Goes into the onboarding link (ServiceRoleArn)."
  value       = aws_iam_role.service_server.arn
}

output "service_server_instance_id" {
  description = "Instance ID. Connect with SSM Session Manager (no SSH)."
  value       = aws_instance.service_server.id
}

output "service_server_public_ip" {
  description = "Elastic IP of the service server. Target of the app.<domain> DNS record."
  value       = aws_eip.service_server.public_ip
}
