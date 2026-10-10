#!/bin/bash
# One-time preparation of a deployment target (the on-prem stand-in VM, and the
# same steps a real on-prem server needs): Docker, Docker Compose, and a
# dedicated non-root "deploy" account that only the service server can use.
#
#   sudo DEPLOY_PUBLIC_KEY="ssh-ed25519 AAAA... service-server-deploy" bash setup.sh
#
# Written for Amazon Linux 2023 (dnf). Safe to re-run. Contains no secrets:
# only the service server's PUBLIC key is needed.
set -euo pipefail

# 부른 쪽의 umask에 기대지 않는다. 한 줄 명령이 비공개 임시 파일을 만들려고 umask 077을 걸어 두면 sudo를 거쳐 이 스크립트까지 이어지고,
# 그러면 /usr/local/lib/docker 같은 폴더가 root 전용(700)으로 만들어져 deploy 계정이 Compose 플러그인을 찾지 못한다.
# 비밀 파일(authorized_keys, .env)은 아래에서 모드를 따로 지정하므로 영향이 없다.
umask 022

COMPOSE_VERSION="v2.29.7"
DEPLOY_USER="deploy"

if [ "$(id -u)" -ne 0 ]; then
  echo "run as root (sudo)" >&2
  exit 1
fi

: "${DEPLOY_PUBLIC_KEY:?set DEPLOY_PUBLIC_KEY to the public key of the service server}"
case "$DEPLOY_PUBLIC_KEY" in
  "ssh-ed25519 "*) ;;
  *)
    echo "DEPLOY_PUBLIC_KEY must be an ssh-ed25519 PUBLIC key line" >&2
    exit 1
    ;;
esac

# --- docker ---------------------------------------------------------------------
dnf install -y docker

# Rotate container logs so they cannot fill the disk.
mkdir -p /etc/docker
tmp_conf="$(mktemp)"
cat > "$tmp_conf" <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
EOF
if ! cmp -s "$tmp_conf" /etc/docker/daemon.json; then
  install -m 0644 "$tmp_conf" /etc/docker/daemon.json
  systemctl restart docker 2>/dev/null || true
fi
rm -f "$tmp_conf"
systemctl enable --now docker

# --- docker compose plugin (pinned version, checksum verified) ---------------------
plugin_dir=/usr/local/lib/docker/cli-plugins
mkdir -p "$plugin_dir"
if ! "$plugin_dir/docker-compose" version 2>/dev/null | grep -q "$COMPOSE_VERSION"; then
  work="$(mktemp -d)"
  cd "$work"
  base="https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}"
  curl -fsSLO "${base}/docker-compose-linux-x86_64"
  curl -fsSLO "${base}/docker-compose-linux-x86_64.sha256"
  sha256sum -c docker-compose-linux-x86_64.sha256
  install -m 0755 docker-compose-linux-x86_64 "$plugin_dir/docker-compose"
  cd /
  rm -rf "$work"
fi

# --- deploy account -------------------------------------------------------------
# Membership in the docker group is root-equivalent on this machine; that is why
# only the service server's key may log in as this user.
id "$DEPLOY_USER" >/dev/null 2>&1 || useradd -m -s /bin/bash "$DEPLOY_USER"
usermod -aG docker "$DEPLOY_USER"

install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/${DEPLOY_USER}/.ssh"
printf '%s\n' "$DEPLOY_PUBLIC_KEY" > "/home/${DEPLOY_USER}/.ssh/authorized_keys"
chown "${DEPLOY_USER}:${DEPLOY_USER}" "/home/${DEPLOY_USER}/.ssh/authorized_keys"
chmod 600 "/home/${DEPLOY_USER}/.ssh/authorized_keys"

# Where the adapter keeps one directory per app (compose file, .env).
install -d -m 755 -o "$DEPLOY_USER" -g "$DEPLOY_USER" /opt/apps

# --- ssh: key login only ----------------------------------------------------------
cat > /etc/ssh/sshd_config.d/90-deploy.conf <<'EOF'
PasswordAuthentication no
PermitRootLogin no
EOF
if sshd -t; then
  systemctl reload sshd
else
  rm -f /etc/ssh/sshd_config.d/90-deploy.conf
  echo "sshd config check failed, drop-in removed" >&2
  exit 1
fi

echo "--- done"
docker --version
docker compose version
id "$DEPLOY_USER"
