# 온프레미스 서버 준비 (사용자용)

AnyShip은 **서비스 서버가 SSH로 사용자의 서버에 접속**해서 앱을 배포합니다. 서버를 한 번 준비해 두면 이후 배포는 자동입니다.

```
사용자 브라우저 ──▶ AnyShip(서비스 서버) ──SSH(키 로그인)──▶ 사용자의 서버
                    개인 키를 가짐                          AnyShip의 "공개 키"만 허용
```

이 폴더는 같은 구성의 시험용 서버(AWS의 작은 EC2)를 만드는 Terraform과, 서버 준비 스크립트(`scripts/setup.sh`)를 담고 있습니다.

## 서버가 갖춰야 할 것

| 항목 | 내용 |
|---|---|
| 운영체제 | **Amazon Linux 2023(x86_64)** 에서만 준비 스크립트를 시험했습니다(`dnf`를 씁니다). 다른 배포판은 같은 구성을 직접 맞춰야 합니다 |
| 공인 IPv4 | 서버가 인터넷에서 보이는 공인 IPv4 주소가 있어야 합니다. 앱 주소(`*.<환경ID>.onprem.<도메인>`)가 이 IP로 만들어집니다. 사설망 안의 서버는 지원하지 않습니다 |
| 포트 | **22(SSH)**: AnyShip 서비스 서버의 IP에서만 허용을 권장 · **80, 443**: 인터넷에서 허용(인증서 발급과 앱 접속) |
| 권한 | 준비 스크립트를 `root`(sudo)로 실행할 수 있어야 합니다 |
| 인터넷 | 서버가 인터넷으로 나갈 수 있어야 합니다(Docker 이미지, 인증서 발급, 공인 IP 확인) |

## 준비 순서

### 1. 준비 스크립트 받기

AnyShip 화면의 서버 등록 단계에서 **준비 스크립트**를 복사합니다. 이 스크립트에는 비밀이 없고, AnyShip의 **공개 키**와 인증서 안내를 받을 **이메일 주소**만 들어 있습니다.
(운영자는 `anyship_adapters.onprem_setup.render_setup_script(공개 키, 이메일)`로 같은 스크립트를 만들 수 있습니다. 이 폴더의 `scripts/setup.sh`는 그 스크립트의 앞부분인 Docker, `deploy` 계정, SSH 설정만 담고 있고, Traefik 시작은 `render_setup_script`가 덧붙입니다.)

### 2. 서버에서 실행

서버에 접속해 받은 스크립트를 파일(`setup.sh`)로 저장하고 **root로 한 번** 실행합니다. 여러 번 실행해도 안전합니다.

```bash
sudo bash setup.sh
```

스크립트가 하는 일:

1. **Docker와 Compose**를 설치합니다(Compose는 버전을 고정하고 체크섬을 검증). 컨테이너 로그는 회전시켜 디스크가 차지 않게 합니다.
2. **`deploy` 계정**을 만들고 AnyShip의 공개 키만 로그인할 수 있게 등록합니다. `deploy` 계정은 `docker` 그룹이라 **이 서버에서 root와 같은 권한**을 가집니다. 그래서 AnyShip의 키 외에는 이 계정으로 로그인할 수 없게 둡니다.
3. 앱을 두는 `/opt/apps` 폴더를 만듭니다.
4. **Traefik**(앱 앞에서 HTTPS를 처리하는 프록시)을 `/opt/apps/traefik`에서 시작합니다. 인증서는 처음에는 Let's Encrypt **staging** CA가 발급하므로 브라우저가 경고를 보여 줍니다(아래 "인증서" 참고).

### 3. 방화벽 확인

서버의 방화벽(보안 그룹 등)에서 위 표의 포트를 엽니다. 22번은 AnyShip 서비스 서버의 IP만 허용하세요.

### 4. AnyShip에서 연결 확인

화면에서 서버 주소(IP 또는 호스트 이름), SSH 사용자(기본 `deploy`), 포트(기본 22)를 입력하고 **연결 확인**을 합니다. 확인하는 것은 네 가지입니다: SSH 접속, Docker와 Compose, Traefik 실행, 서버의 공인 IP.

## ⚠ 준비 스크립트가 서버 설정을 바꿉니다

- **SSH 비밀번호 로그인을 끄고 root 로그인을 막습니다**(`/etc/ssh/sshd_config.d/90-deploy.conf`: `PasswordAuthentication no`, `PermitRootLogin no`). 서버 **전체**에 적용됩니다. 이미 비밀번호로 접속하는 서버라면 **다른 키 로그인을 먼저 확인한 뒤** 실행하세요. 안 그러면 서버에 들어갈 수 없게 될 수 있습니다.
- `deploy` 계정의 `authorized_keys`는 AnyShip의 공개 키 한 줄로 **덮어씁니다**(다른 계정은 건드리지 않습니다).

## 연결 확인이 실패할 때

| 오류 코드 | 뜻 | 해결 |
|---|---|---|
| `ssh_unreachable` | 서버에 SSH로 접속하지 못함 | 서버 주소와 포트가 맞는지, 22번 포트에서 AnyShip 서비스 서버 IP를 허용했는지, 준비 스크립트를 실행했는지 확인 |
| `ssh_command_failed` | 접속은 되지만 명령 실행이 실패 | `deploy` 계정으로 `docker ps`가 되는지(docker 그룹) 확인 |
| `docker_missing` | Docker 또는 Compose가 없음 | 준비 스크립트를 다시 실행 |
| `proxy_not_ready` | Traefik이 실행 중이지 않음 | `/opt/apps/traefik`에서 `docker compose up -d`, `docker compose logs`로 시작 오류 확인(80/443 포트를 다른 프로그램이 쓰고 있을 수 있음) |
| `public_ip_unknown` | 서버의 공인 IP를 알 수 없음 | 서버가 인터넷으로 나갈 수 있는지, 공인 IP가 있는지 확인 |

## 인증서

처음에는 Let's Encrypt **staging** 인증서가 발급되어 브라우저가 "신뢰할 수 없음" 경고를 보여 줍니다(시험용이고 발급 한도가 넉넉합니다). 브라우저가 신뢰하는 인증서로 바꾸려면 staging에서 정상 동작을 확인한 뒤 `sets/onprem/compose/README.md`의 5단계(production CA 전환)를 따릅니다. production은 발급 한도가 엄격하니 실패를 반복하지 마세요.

## 한계

- **서비스의 모든 환경이 같은 SSH 키 하나를 씁니다.** 그 개인 키가 유출되면 등록된 모든 서버가 노출됩니다. 환경별 키는 후속 과제입니다.
- 서버 하나는 환경 하나입니다. 앱이 여러 개여도 같은 서버와 같은 Traefik을 공유하고 앱 이름으로 구분됩니다.
- Traefik은 Docker 소켓을 읽기 전용으로 씁니다. 컨테이너 메타데이터를 볼 수 있으므로 더 강하게 하려면 소켓 프록시를 앞에 두는 것이 다음 단계입니다.

## 시험용 서버 만들기 (운영자용)

이 폴더의 Terraform은 서비스 서버와 같은 OS(Amazon Linux 2023)의 작은 EC2에 준비 스크립트를 첫 부팅에 실행시켜 "온프레미스 서버 대역"을 만듭니다. 인스턴스 프로파일을 일부러 붙이지 않아 이 서버에는 AWS 자격 증명이 없습니다. 어댑터는 SSH와 Docker만 필요로 하므로 실제 온프레미스 서버와 같은 조건입니다. 사용법은 변수 `ssh_public_key`(서비스 서버 배포 키의 공개 키 한 줄, 개인 키는 넣지 않습니다)를 정하고 `terraform apply`입니다. 인스턴스 종류(`instance_type`, 기본 `t3.small`), 리전, 루트 볼륨 크기는 `variables.tf`에서 바꿀 수 있습니다. 이 시험용 서버는 Traefik을 따로 시작하지 않으므로, 어댑터 `check`를 통과하려면 `sets/onprem/compose/README.md`의 2단계로 Traefik을 올리거나 `render_setup_script`의 결과로 준비하세요.
