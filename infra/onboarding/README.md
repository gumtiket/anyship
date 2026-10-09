# 사용자 계정 온보딩

`user-account-role.yaml`은 사용자 AWS 계정에 CloudFormation 스택으로 만든다. 서비스(A)가 퀵 생성 링크를 발급하고,
사용자가 콘솔에서 IAM 생성에 동의한 뒤 스택을 만든다. 스택이 만드는 것은 아래와 같다.

| 리소스 | 용도 |
|---|---|
| `DeployRole` | 서비스 서버 역할이 External ID로 AssumeRole 하는 배포 역할 |
| `StateBucket` | 공용 기반 Terraform의 state 보관(`anyship-tfstate-<계정ID>-<리전>-<스택ID 8자>`) |
| `StateBucketPolicy` | TLS가 아닌 접근 거부 |

## state 버킷

state에는 리소스 ID와 네트워크 구성이 들어 있어 민감하다. 그래서 서비스 계정이 아니라 **사용자 계정**에 두고,
우리 쪽에는 사용자 state를 저장하지 않는다. 버킷 이름에는 스택 ID의 일부가 들어가 계산할 수 없으므로,
서비스는 스택 출력 `StateBucketName`에서 읽는다.

버킷은 공개 접근이 차단되고, 암호화와 버전 관리가 켜져 있다. 사용자 계정 관리자는 직접 열어 볼 수 있다.

## 확인

```bash
ROLE_ARN=arn:aws:iam::<계정ID>:role/deploy-service-role \
EXTERNAL_ID=<External ID> ./check-assume-role.sh
```

## 환경을 정리할 때

1. 먼저 공용 기반을 지운다(`terraform destroy`). 서비스가 하는 일이며, 이 단계가 빠지면 EC2, RDS 등이 남아 비용이 계속 발생한다.
2. 온보딩 스택을 삭제한다. **`StateBucket`은 `Retain`이라 스택을 지워도 남는다**(비어 있지 않은 버킷은
   삭제가 실패해서 스택 삭제까지 막기 때문이다).
3. state가 더는 필요 없으면 버킷을 직접 비우고 지운다. 버전 관리가 켜져 있어 모든 버전을 지워야 한다.

```bash
BUCKET=<스택 출력 StateBucketName 값>
aws s3 rm "s3://$BUCKET" --recursive
# 버전 관리 때문에 이전 버전과 삭제 표시도 남아 있다. 콘솔의 "비우기"가 가장 쉽다.
aws s3 rb "s3://$BUCKET"
```

## 같은 계정에 다시 온보딩할 때

역할 이름(`deploy-service-role`)이 계정에서 하나만 가능하므로, 기존 스택을 먼저 삭제한다. 버킷 이름에 스택 ID가
들어가서 새 스택은 항상 새 버킷을 만든다(이름 충돌 없음). 이전 버킷은 고아로 남으므로 위 3번으로 정리한다.
이전 버킷에 아직 쓰는 state가 있으면(공용 기반이 남아 있으면) 지우지 말고 먼저 `destroy`한다.
