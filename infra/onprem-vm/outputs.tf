output "onprem_vm_instance_id" {
  description = "Instance ID of the on-prem stand-in VM."
  value       = aws_instance.onprem_vm.id
}

output "onprem_vm_public_ip" {
  description = "Elastic IP of the VM. Target of the *.onprem DNS record and the adapter's SSH host."
  value       = aws_eip.onprem_vm.public_ip
}
