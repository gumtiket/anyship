# 사용자 계정 공용 기반 (Terraform)

사용자 AWS 계정에 한 번 만들어 두는 기반이다. 느린 자원(VPC, RDS, 호스트)을 온보딩 때 미리 만들어, 앱 배포 때마다 기다리지 않게 한다. 이슈 #30.

| 자원 | 내용 |
|---|---|
| 네트워크 | 새 VPC, 퍼블릭 서브넷 2개(호스트), 프라이빗 서브넷 2개(RDS), 서로 다른 AZ. NAT 없음 |
| 앱 호스트 | EC2 1대 + 탄력적 IP. Docker, Compose, `deploy` 계정, Traefik이 첫 부팅에 자동 설치·시작. 인스턴스 프로파일 없음, IMDSv2 필수, 홉 제한 1 |
| 데이터베이스 | RDS PostgreSQL 16(비공개). 마스터 비밀번호는 Secrets Manager가 관리 |
| 보안 그룹 | 호스트: 80/443 공개, 22는 서비스 서버 IP만. RDS: 호스트에서 오는 5432만 |

파일: `versions.tf`(backend), `provider.tf`, `variables.tf`, `network.tf`, `compute.tf`, `database.tf`, `outputs.tf`, `tf.sh`(실행 래퍼), `terraform.tfvars.example`.

## 자격 증명이 흐르는 방식

Terraform은 External ID를 모른다. 서비스 서버가 사용자 계정의 `deploy-service-role`을 AssumeRole해서 받은 임시 자격 증명(1시간)을 **그 한 명령의 환경변수로만** 넘긴다. `tf.sh`가 이 일을 한다(서비스가 만들 실행기의 시험판).
`provider.tf`의 `allowed_account_ids`가 계정을 고정하므로, 자격 증명이 잘못 들어가도 다른 계정(서비스 계정)에는 만들어지지 않는다.

## 준비

1. 사용자 계정에 온보딩 스택이 있어야 한다. 스택 출력에서 `RoleArn`(또는 `deploy-service-role`의 ARN)과 `StateBucketName`을 확인한다.
2. 서비스 서버에서 AssumeRole이 되는지 먼저 확인한다: `infra/onboarding/check-assume-role.sh`. 역할 ARN의 **계정 ID는 서비스 계정이 아니라 사용자 계정**이어야 한다.
3. state 버킷의 리전을 확인한다(버킷 이름에 들어 있다).
4. 서비스 서버의 배포 키(공개 키)를 준비한다. 온프레미스 VM에 쓴 것과 같은 키다.
5. 저장소 전체를 서비스 서버에 둔다. `compute.tf`가 `../onprem-vm/scripts/setup.sh`와 `../sets/onprem/compose/traefik/compose.yaml`을 읽으므로 `infra/user-account/`만 복사하면 안 된다.

## 실행

서비스 서버의 `infra/user-account/`에서 한다. `<...>`는 값으로 바꾼다. **External ID와 임시 자격 증명을 파일, 문서, 채팅에 남기지 않는다.**

변수 파일을 만든다(`*.tfvars`는 `.gitignore` 대상이다).

```bash
cp terraform.tfvars.example test.tfvars
# account_id, service_server_ip, ssh_public_key, acme_email 을 채운다
chmod +x tf.sh
```

`env_id`는 `test.tfvars`와 아래 state key에 **같은 값**을 쓴다(소문자·숫자·하이픈 2~21자).

```bash
R=arn:aws:iam::<사용자 계정 ID>:role/deploy-service-role; E=<External ID>

# 1. init (처음 한 번, 또는 backend 값을 바꿀 때)
ROLE_ARN=$R EXTERNAL_ID=$E ./tf.sh init -reconfigure \
  -backend-config="bucket=<StateBucketName>" \
  -backend-config="region=<버킷 리전>" \
  -backend-config="key=<env_id>/foundation.tfstate"

# 2. 계획 확인
ROLE_ARN=$R EXTERNAL_ID=$E ./tf.sh plan -var-file=test.tfvars

# 3. 적용 (RDS 때문에 오래 걸린다. 중간에 Ctrl+C 하지 않는다)
ROLE_ARN=$R EXTERNAL_ID=$E ./tf.sh apply -var-file=test.tfvars

# 4. 정리 (시험 후 반드시. RDS는 켜 두면 요금이 계속 나온다)
ROLE_ARN=$R EXTERNAL_ID=$E ./tf.sh destroy -var-file=test.tfvars
```

`apply`를 한 번 더 실행했을 때 `no change`가 나와야 한다(멱등성).

## 확인

출력값은 `./tf.sh output`(값 하나는 `output -raw <이름>`)으로 본다. 변수로 받아 두면 아래 확인에 쓴다.

```bash
DB=$(ROLE_ARN=$R EXTERNAL_ID=$E ./tf.sh output -raw db_address)
SECRET=$(ROLE_ARN=$R EXTERNAL_ID=$E ./tf.sh output -raw db_master_secret_arn)
HOST=$(ROLE_ARN=$R EXTERNAL_ID=$E ./tf.sh output -raw host_public_ip)
echo "R=${#R} E=${#E} SECRET=${#SECRET} HOST=${#HOST} DB=${#DB}"   # 길이만 본다. 0이면 비어 있다
```

- **호스트와 Traefik**: `ssh -i <개인 키> -o IdentitiesOnly=yes deploy@"$HOST" 'docker ps --format "{{.Names}} {{.Status}}"'` 에 Traefik이 `Up`으로 나온다.
- **80/443**: `curl -sI http://$HOST`는 `308`(HTTPS로 리디렉션), `curl -skI https://$HOST`는 `404`(앱이 없을 때의 정상 응답).
- **호스트 → RDS**: 호스트에는 AWS 자격 증명이 없으므로, 서비스 서버가 비밀번호를 읽어 SSH 표준입력으로 넘기고 호스트에서 `psql` 컨테이너로 접속한다. 비밀번호는 화면·명령줄·디스크에 남지 않는다.

```bash
read -r ak sk st < <(aws sts assume-role --role-arn "$R" --role-session-name db-check --external-id "$E" --duration-seconds 900 --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' --output text); AWS_ACCESS_KEY_ID="$ak" AWS_SECRET_ACCESS_KEY="$sk" AWS_SESSION_TOKEN="$st" aws secretsmanager get-secret-value --region <리전> --secret-id "$SECRET" --query SecretString --output text | python3 -c 'import sys,json; print(json.load(sys.stdin)["password"])' | ssh -i <개인 키> -o IdentitiesOnly=yes deploy@"$HOST" "IFS= read -r PGPASSWORD; export PGPASSWORD; docker run --rm -e PGPASSWORD postgres:16-alpine psql 'host=$DB port=5432 user=anyship_admin dbname=postgres sslmode=require connect_timeout=10' -c 'select version(), current_user'"
```

`PostgreSQL 16.x`와 `anyship_admin`이 나오면 호스트 → RDS 전 구간이 통과한 것이다. 끝나면 `history -c`로 히스토리를 정리한다.

## 막혔을 때

| 증상 | 원인과 해결 |
|---|---|
| `AccessDenied` + `assumed-role/service-server` | 임시 자격 증명이 적용되지 않았다. `terraform`을 직접 실행하지 말고 `tf.sh`로 실행한다 |
| AssumeRole `AccessDenied` | `ROLE_ARN`의 계정 ID가 서비스 계정이다. 사용자 계정 ID로 바꾼다 |
| `init`이 `Missing region value` | `-backend-config="region=..."` 누락. 값은 버킷의 실제 리전과 같아야 한다 |
| `init`이 버킷·key를 묻는다 | backend 값은 대화형이 아니라 `-backend-config`로 넘긴다 |
| `./tf.sh: Permission denied` | `chmod +x tf.sh` (저장소에 남기려면 `git update-index --chmod=+x`) |
| 위 확인 명령에서 `Could not resolve hostname` | 셸 변수가 비어 있다(세션이 바뀌면 사라진다). 위 변수 설정을 다시 한다 |
| SSH `Permission denied (publickey)`이고 `Offering public key` 줄이 없음 | 개인 키를 못 찾았다. `-i <개인 키>`를 준다. `-i`에는 **개인 키**(`.pub`이 아닌 것)를 준다 |
| SSH 키 오류가 계속됨 | `test.tfvars`의 공개 키와 서버의 개인 키가 짝인지 지문(`ssh-keygen -lf`)으로 비교한다 |
| `plan`이 `file(...)` 오류 | 저장소 전체가 아니라 `user-account/`만 복사했다 |

## 주의

- **비용**: RDS와 호스트는 켜 두면 요금이 나온다. 시험 후 `destroy`하고 콘솔에서 RDS·EC2·탄력적 IP가 남지 않았는지 본다.
- **시험용 설정**: `database.tf`의 `skip_final_snapshot = true`, `deletion_protection = false`는 `destroy`가 막히지 않게 한 것이다. 실제 사용자 환경에 쓰기 전에 반대로 바꾼다.
- **호스트 교체**: `user_data`(공개 키, 이메일, 스크립트)가 바뀌면 호스트가 교체된다(`user_data_replace_on_change`). 탄력적 IP는 유지되지만 호스트 디스크의 Traefik 인증서는 사라진다. 운영 CA로 전환한 뒤에는 Let's Encrypt 발급 한도에 주의한다.
- **인증서**: Traefik은 staging CA로 시작한다. 운영 전환은 데모 앱 이름을 정한 뒤에 한다.
- **온보딩 역할 권한**: 아직 `AdministratorAccess`다. 좁히기는 후속이다.
- **SSH 키**: 서비스 서버의 배포 키 하나를 모든 대상이 공유한다. 환경별 키 분리는 후속이다.
