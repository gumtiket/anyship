# anyship-adapters

서비스가 "이 환경에 이 앱을 배포해 줘"라고 요청할 때 부르는 **어댑터 인터페이스**와,
서비스를 먼저 개발할 수 있게 해 주는 **mock 어댑터**입니다.

환경(AWS, 온프레미스)마다 작동 방식이 다르지만, 서비스는 아래 다섯 개 함수만 부릅니다.

```
서비스 ──(Adapter 인터페이스)──▶ 어댑터 ──▶ 환경
```

- 지금 들어 있는 것: 인터페이스, 데이터 구조, 비밀 걸러내기, **mock 어댑터**
- 아직 없는 것: 실제 어댑터(온프레미스, AWS). 같은 인터페이스를 구현해서 따로 추가합니다.

## 설치

서비스(`service/`)에서 설치합니다. 의존성은 `pydantic` 하나이고, 서비스가 이미 고정한 버전
(`pydantic==2.13.5`)과 호환됩니다.

```bash
python -m pip install -e ../infra/adapters
```

사용할 때는 항상 `anyship_adapters`에서 임포트하면 됩니다.

```python
from anyship_adapters import MockAdapter, OnpremEnvironment, AwsEnvironment
```

## 사용 예

```python
from anyship_adapters import MockAdapter, OnpremEnvironment

adapter = MockAdapter()
env = OnpremEnvironment(env_id="demo", host="3.38.88.141")


def log(event):
    print(f"[{event.step}/{event.total}] {event.name}: {event.message}")


check = adapter.check(env, log)
if not check.ok:
    print(check.error.message, check.error.hint)

spec = {"app": "todo-a1b2", "backing_services": []}
result = adapter.deploy(env, spec, "3f2a9c1", {"API_KEY": "..."}, log, set_name="onprem")
if result.ok:
    print(result.url)  # https://todo-a1b2.demo.onprem.anyship.cloud
else:
    print(result.error.code, result.error.message)
```

실행하면 이렇게 출력됩니다.

```
[1/2] 접속 확인: 환경에 접속하는 중
[2/2] 준비 상태 확인: 필요한 구성 요소를 확인하는 중
[1/5] 환경 점검: 환경 점검 중
...
[5/5] 헬스체크: 헬스체크 중
```

## 인터페이스

| 함수 | 하는 일 | 돌려주는 것 |
|---|---|---|
| `check(env, log)` | 이 환경에 접속하고 관리할 수 있는지 확인 | `CheckResult` |
| `deploy(env, spec, image_tag, secrets, log, *, set_name)` | 선택한 세트로 앱을 배포 | `DeployResult` (`url`, `image_tag`) |
| `status(env, app)` | 앱이 지금 실행 중이고 정상인지 | `StatusResult` (`state`, `url`, `image_tag`) |
| `rollback(env, app, image_tag, log)` | 이전 이미지 태그로 다시 실행(DB 스키마는 되돌리지 않음) | `DeployResult` |
| `destroy(env, app, log)` | 배포가 만든 것을 제거(없어도 성공) | `DestroyResult` |

공통 규칙

- **모든 함수는 작업이 끝날 때까지 기다립니다.** 서비스가 백그라운드 작업자에서 실행하고, 그동안 `log`로
  받은 이벤트를 사용자 화면에 흘려보냅니다.
- **실패는 예외가 아니라 `ok=False` 결과로 돌려줍니다.** 서비스는 `result.ok`만 확인하면 됩니다.
  (코드의 예상하지 못한 버그는 그대로 예외가 됩니다.)
- `deploy`의 `set_name`은 키워드 인자입니다. AWS 환경만으로는 `aws-serverless`와
  `aws-always-on` 중 무엇인지 알 수 없어서, 추가했습니다.

## 데이터 구조

### 환경 (`env`)

사용자가 환경 등록 화면에서 입력한 값입니다. **서비스 DB에 저장해도 되는 값만** 담습니다.
모르는 필드는 거부하므로 개인 키나 토큰은 넣을 수 없습니다.

| 종류 | 필드 | 형식 |
|---|---|---|
| `AwsEnvironment` | `env_id` | 소문자로 시작, 소문자·숫자·하이픈, 2~21자 |
| | `role_arn` | `arn:aws:iam::<12자리>:role/...` (역할만 허용) |
| | `external_id` | 16~128자. **서비스(백엔드)가 환경마다 만들어 저장** |
| | `region` | 기본 `ap-northeast-2` |
| `OnpremEnvironment` | `env_id` | 위와 같음 |
| | `host` | IP 또는 호스트 이름(SSH 옵션을 끼워 넣을 수 있는 값은 거부) |
| | `ssh_user` | 기본 `deploy` |
| | `ssh_port` | 기본 22 |

두 종류를 한꺼번에 받을 때는 `kind`(`"aws"` 또는 `"onprem"`)로 구분합니다.

```python
from pydantic import TypeAdapter
from anyship_adapters import Environment

env = TypeAdapter(Environment).validate_python(row_from_db)
```

### 명세 (`spec`)와 비밀 (`secrets`)

- `spec`은 배포 명세를 **딕셔너리**로 넘깁니다. 어댑터는 필드를 다시 검증합니다.
- `secrets`는 `{"이름": "값"}` 딕셔너리입니다. **메모리에만 두고 서비스 DB, 로그에 남기지 마세요.**
  어댑터가 환경의 비밀 저장소(AWS Secrets Manager, 서버의 `.env`)에 쓰고, 결과에는 **이름만** 남깁니다
  (`details["secrets_stored"]`).

### 로그 이벤트 (`LogEvent`)

| 필드 | 설명 |
|---|---|
| `ts` | 시각(UTC) |
| `level` | `info`, `warn`, `error` |
| `step`, `total` | "5단계 중 2번째" 같은 진행 표시. 퍼센트는 제공하지 않습니다 |
| `name` | 단계 이름(예: `이미지 전달`) |
| `message` | 화면에 보여 줄 문장 |
| `data` | 나중에 이력이나 분석에 쓸 부가 정보(비밀은 들어가지 않음) |

### 결과

모든 결과는 **성공이거나, 오류를 담은 실패 중 하나**입니다(둘 다이거나 둘 다 아닌 경우는 만들 수 없습니다).

| 필드 | 설명 |
|---|---|
| `ok` | 성공 여부 |
| `error.code` | 기계가 읽는 코드(소문자와 밑줄). 화면 분기에 사용 |
| `error.message` | 사용자에게 보여 줄 메시지 |
| `error.hint` | 사용자가 할 수 있는 조치 |
| `error.retryable` | 다시 시도하면 될 수 있는 오류인지 |
| `details` | 부가 정보(예: `check`의 `account_id`, `public_ip`) |

## 세트 이름

| 세트 | 쓸 수 있는 환경 |
|---|---|
| `aws-serverless` | `AwsEnvironment` (Lambda) |
| `aws-always-on` | `AwsEnvironment` (EC2 호스트) |
| `onprem` | `OnpremEnvironment` |

환경과 맞지 않는 세트를 넘기면 `set_not_supported`로 거부합니다.

## 오류 코드 (현재)

mock이 내는 코드이고, 실제 어댑터가 생기면 더 늘어납니다

| 코드 | 언제 | `retryable` |
|---|---|---|
| `ssh_unreachable` | 온프레미스 서버에 SSH로 접속할 수 없음 | 예 |
| `assume_role_denied` | 사용자 AWS 계정의 역할을 사용할 수 없음 | 예 |
| `invalid_spec` | 명세의 앱 이름이 올바르지 않음 | 아니요 |
| `invalid_image_tag` | 이미지 태그가 커밋 SHA 형식(16진수 7~40자)이 아님 | 아니요 |
| `set_not_supported` | 환경과 맞지 않는 세트 | 아니요 |
| `unsupported_backing_service` | `object_storage`를 쓰는 앱(아직 미지원) | 아니요 |
| `app_not_found` | 배포되지 않은 앱을 되돌리려 함 | 아니요 |
| `container_start_failed` | 새 컨테이너가 시작되지 않음 | 예 |
| `healthcheck_failed` | 앱이 `/healthz`에 응답하지 않음 | 예 |

## mock 어댑터

실제 환경 없이 서비스를 개발하고 시험하는 용도입니다. 

```python
MockAdapter()                    # 모든 것이 성공
MockAdapter("check_fails")       # check 실패
MockAdapter("deploy_fails")      # 4단계(앱 시작)에서 실패
MockAdapter("unhealthy")         # 5단계(헬스체크)에서 실패
MockAdapter(delay=1.0)           # 단계마다 1초 대기(진행 화면 확인용)
```

- 앱 정보는 **메모리에만** 있어서 프로세스를 다시 시작하면 사라집니다.
- 실패한 배포는 앱을 남기지 않습니다.

## 비밀이 새지 않게 하는 방법

- 어댑터는 로그와 결과가 나가기 전에 비밀을 걸러냅니다. 이번 배포의 비밀 값은 나타나는 모든 곳에서
  `***`로 바뀌고, 클라우드 키·토큰·개인 키·URL 안의 비밀번호 같은 **알려진 모양**도 바뀝니다.
- 서비스도 `secrets`를 DB와 로그에 남기지 않아야 합니다.
- 4자보다 짧은 비밀은 걸러내지 않습니다.

## 테스트

패키지 폴더에서 실행합니다.

```bash
cd infra/adapters
python -m pip install -e ".[test]"
python -m pytest
```

서비스가 실제로 쓰는 버전 조합에서 확인하려면, 서비스의 의존성을 먼저 설치하고 어댑터는 의존성 없이
추가합니다.

```bash
python -m pip install -r service/requirements.txt
python -m pip install --no-deps -e infra/adapters pytest
python -m pytest infra/adapters
```

## 남은 것

- 실제 어댑터(온프레미스, AWS): 같은 인터페이스를 구현하는 별도 작업
- DNS 레코드 생성(`ensure_dns`), 환경별 SSH 키 같은 확장 항목
- 오류 코드 추가
