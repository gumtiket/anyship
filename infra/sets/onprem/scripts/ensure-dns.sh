#!/bin/bash
# Prototype of the adapter's "ensure_dns" step (to be reimplemented in the
# on-prem adapter). Runs on the service server.
#
#   ensure-dns.sh <env_id> <server_host>            create/update the record
#   ensure-dns.sh <env_id> --delete                  remove the record
#
# What it does for a registered on-prem environment:
#   1. SSH into the server (as the "deploy" account) and ask it for its public IP
#   2. refuse anything that is not a public IPv4 address
#   3. UPSERT  *.<env_id>.onprem.<BASE_DOMAIN>  ->  that IP   (Route 53, TTL 60)
#
# The user only supplies the server address; nobody types an IP into DNS.
# AWS credentials come from the service server's instance role. No secrets here.
set -euo pipefail

BASE_DOMAIN="${BASE_DOMAIN:-anyship.cloud}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/onprem_deploy}"
SSH_USER="${SSH_USER:-deploy}"
RECORD_TTL=60
DRY_RUN="${DRY_RUN:-0}"

die() {
  echo "error: $*" >&2
  exit 1
}

# env id becomes part of a DNS label and of resource names.
valid_env_id() {
  [[ "$1" =~ ^[a-z][a-z0-9-]{1,20}$ ]]
}

# Host the user typed: a hostname or an IPv4 address, nothing else (it ends up
# on an ssh command line).
valid_host() {
  [[ "$1" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$ ]]
}

# True only for globally routable IPv4 (rejects private, loopback, link-local,
# 169.254.169.254 and friends).
is_public_ipv4() {
  python3 -I -c '
import ipaddress, sys
try:
    ip = ipaddress.ip_address(sys.argv[1])
except ValueError:
    sys.exit(1)
sys.exit(0 if ip.version == 4 and ip.is_global else 1)' "$1"
}

resolve_ipv4() {
  python3 -I -c '
import socket, sys
try:
    print(socket.getaddrinfo(sys.argv[1], None, socket.AF_INET)[0][4][0])
except OSError:
    sys.exit(1)' "$1"
}

zone_id() {
  aws route53 list-hosted-zones-by-name --dns-name "${BASE_DOMAIN}." \
    --query "HostedZones[?Name=='${BASE_DOMAIN}.' && Config.PrivateZone==\`false\`].Id | [0]" \
    --output text | sed 's#/hostedzone/##'
}

change_record() { # <action UPSERT|DELETE> <name> <ip>
  local action="$1" name="$2" ip="$3" zone batch change_id
  zone="$(zone_id)"
  [ -n "$zone" ] && [ "$zone" != "None" ] || die "hosted zone for ${BASE_DOMAIN} not found"

  batch="$(mktemp)"
  cat > "$batch" <<EOF
{
  "Comment": "managed by ensure-dns.sh",
  "Changes": [{
    "Action": "${action}",
    "ResourceRecordSet": {
      "Name": "${name}",
      "Type": "A",
      "TTL": ${RECORD_TTL},
      "ResourceRecords": [{ "Value": "${ip}" }]
    }
  }]
}
EOF
  if [ "$DRY_RUN" = "1" ]; then
    echo "[dry-run] zone ${zone}"
    cat "$batch"
    rm -f "$batch"
    return 0
  fi
  change_id="$(aws route53 change-resource-record-sets --hosted-zone-id "$zone" \
    --change-batch "file://${batch}" --query 'ChangeInfo.Id' --output text)"
  rm -f "$batch"
  aws route53 wait resource-record-sets-changed --id "$change_id"
}

main() {
  [ "$#" -ge 2 ] || die "usage: $0 <env_id> <server_host> | $0 <env_id> --delete"
  local env_id="$1" target="$2"
  valid_env_id "$env_id" || die "env_id must match ^[a-z][a-z0-9-]{1,20}\$"
  local name="*.${env_id}.onprem.${BASE_DOMAIN}"

  if [ "$target" = "--delete" ]; then
    local zone current
    zone="$(zone_id)"
    current="$(aws route53 list-resource-record-sets --hosted-zone-id "$zone" \
      --query "ResourceRecordSets[?Name=='\\052.${env_id}.onprem.${BASE_DOMAIN}.' && Type=='A'].ResourceRecords[0].Value | [0]" \
      --output text)"
    if [ -z "$current" ] || [ "$current" = "None" ]; then
      echo "no record for ${name}, nothing to delete"
      return 0
    fi
    change_record DELETE "$name" "$current"
    echo "deleted ${name} -> ${current}"
    return 0
  fi

  local host="$target"
  valid_host "$host" || die "server host looks invalid"

  # The address the user typed must itself be public (no SSRF to internal hosts).
  local ssh_ip
  ssh_ip="$(resolve_ipv4 "$host")" || die "cannot resolve ${host}"
  is_public_ipv4 "$ssh_ip" || die "${host} resolves to a non-public address (${ssh_ip})"

  [ -r "$SSH_KEY" ] || die "ssh key not readable: ${SSH_KEY}"

  # Ask the server itself for its public IP, through the SSH connection that
  # proves we are allowed to manage it.
  local public_ip
  public_ip="$(ssh -i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=10 \
    -o StrictHostKeyChecking=accept-new "${SSH_USER}@${ssh_ip}" \
    'curl -fsS --max-time 10 https://checkip.amazonaws.com' | tr -d '[:space:]')" \
    || die "ssh to ${host} failed"
  is_public_ipv4 "$public_ip" || die "server reported a non-public IP: '${public_ip}'"

  change_record UPSERT "$name" "$public_ip"
  echo "ok: ${name} -> ${public_ip}"
  echo "public_ip=${public_ip}"
}

# Allow `source ensure-dns.sh` in tests without running main.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
