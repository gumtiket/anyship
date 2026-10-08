#!/bin/bash
# Service server bootstrap. Runs once as root on first boot (cloud-init user_data).
# Log: /var/log/cloud-init-output.log. Idempotent, so it can be re-run by hand.
set -euxo pipefail

TERRAFORM_VERSION="1.15.9"

# --- core tools ---------------------------------------------------------------
dnf install -y git unzip docker

# Rotate container logs so they cannot fill the disk.
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
EOF
systemctl enable --now docker
usermod -aG docker ec2-user

# --- terraform (pinned version, checksum verified) ----------------------------
tmp="$(mktemp -d)"
cd "$tmp"
base="https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}"
curl -fsSLO "${base}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip"
curl -fsSLO "${base}/terraform_${TERRAFORM_VERSION}_SHA256SUMS"
grep "linux_amd64.zip" "terraform_${TERRAFORM_VERSION}_SHA256SUMS" | sha256sum -c -
unzip -o "terraform_${TERRAFORM_VERSION}_linux_amd64.zip" terraform
install -m 0755 terraform /usr/local/bin/terraform
cd /
rm -rf "$tmp"

# --- python (final runtime version is decided with the service team) ----------
dnf install -y python3.12 python3.12-pip || echo "python3.12 not available, skipped"
