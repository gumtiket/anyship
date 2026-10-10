# AnyShip GitHub 모듈 사용 및 테스트 가이드

AnyShip 웹 서비스 실행과 실제 GitHub App 설정은 [로컬 실행 안내](../docs/LOCAL_DEVELOPMENT.md)를 참고하세요. 아래는 AWS 환경 등록 API와 독립적으로 사용할 수 있는 GitHub 모듈의 안내입니다.

AI 분석·다중 파일 변경안 검토·Draft PR 흐름은 `APP_AI_MODE=bronze`로 활성화합니다. Python 3.12 이상에서 `requirements-dev.txt`를 설치하고 `alembic upgrade head`로 `0009`를 적용하세요. 제공자 설정과 검증 범위는 [AI 통합 안내](../docs/AI_INTEGRATION.md)를 참고하세요.

## Mock 어댑터로 배포 흐름 시험하기

Infra의 `MockAdapter`를 사용하는 개발 전용 기능입니다. 실제 AWS·SSH·GitHub 배포 요청이나 이미지 빌드를 하지 않으며, 기존 AWS의 검증된 연결 상태도 바꾸지 않습니다.

1. `service/`에서 `python -m pip install -r requirements-dev.txt`를 실행합니다. 같은 저장소의 `infra/adapters`를 설치하므로 두 폴더가 함께 있어야 합니다.
2. `service/.env.github.local`에 `APP_DEPLOYMENT_MODE=mock`을 설정합니다. 기본값은 `unavailable`이며 운영 설정에서는 mock을 거부합니다. `APP_MOCK_STEP_DELAY=0.3`으로 단계별 지연을 조절할 수 있습니다(0~2초).
3. `python -m alembic upgrade head`로 `0007` 마이그레이션을 적용하고 프론트엔드를 빌드한 뒤 서버를 재시작합니다. 새 테이블 `mock_deployments`, `mock_jobs`가 추가됩니다.
4. 프로젝트 상세의 **모의 배포**에서 샘플 AWS 또는 샘플 온프레미스를 선택하고 환경을 저장합니다. ARN을 저장한 자신의 기존 AWS 등록도 모의 입력으로 사용할 수 있습니다. AWS 키와 실제 CloudFormation 생성은 필요하지 않습니다.
5. **모의 연결 확인 → 모의 배포**를 실행합니다. 테스트 버전 `aaaaaaa`를 배포한 뒤 `bbbbbbb`를 배포하면 이전 버전 롤백도 시험할 수 있습니다. 성공·연결 실패·앱 시작 실패·헬스체크 실패를 화면에서 선택합니다.
6. **상태 새로고침**, **모의 롤백**, **모의 배포 제거**로 나머지 흐름을 확인합니다. 반환 주소는 형식 예시이며 실제로 열 수 있는 주소가 아닙니다.

모의 실행 상태는 메모리에만 있고 작업 기록은 DB에 저장됩니다. 재시작 후에는 연결 확인·현재 배포·롤백 가능한 버전이 초기화되며, 중단된 작업은 `interrupted`로 표시합니다. 과거 성공 기록을 현재 실행 상태로 취급하지 않습니다. 같은 DB를 사용하는 mock 서버는 로컬에서 한 프로세스만 실행할 수 있습니다. 여러 Uvicorn worker나 여러 호스트에 분산한 실행은 지원하지 않습니다.

프로젝트와 환경은 소유자의 현재 워크스페이스에서만 사용할 수 있습니다. 모의 작업 중에는 프로젝트·환경 등록 삭제를 차단합니다. 작업 완료 후 환경 등록을 삭제하면 해당 모의 선택이 해제되고 작업 기록은 남습니다. 프로젝트 연결 삭제 시에는 모의 선택과 작업 기록도 함께 삭제됩니다.

| API | 역할 |
| --- | --- |
| `GET /api/projects/{id}/mock-deployment` | 선택 가능한 환경, 저장된 선택, 현재 모의 상태·버전 |
| `PUT /api/projects/{id}/mock-deployment` | `{source, set_name}` 저장. 배포 중인 환경 변경은 모의 배포 제거 후 가능 |
| `POST /api/projects/{id}/mock-deployment/jobs` | `{request_id, action, scenario, image_tag}`로 작업 생성, `202`와 작업 ID 반환 |
| `GET /api/projects/{id}/mock-deployment/jobs?limit=50&offset=0` | 작업 이력과 진행 로그 |
| `GET /api/projects/{id}/mock-deployment/jobs/{job_id}` | 개별 작업 조회 |

`source`는 `sample-aws`, `sample-onprem` 또는 자신이 등록한 AWS 환경 UUID입니다. `set_name`은 환경에 맞는 `aws-serverless`, `aws-always-on`, `onprem`입니다. Service UUID를 그대로 넘기지 않고 별도로 저장한 21자 식별자를 Infra에 전달합니다.

`action`은 `check`, `deploy`, `rollback`, `destroy`, `scenario`는 `success`, `check_fails`, `deploy_fails`, `unhealthy`입니다. 배포·롤백에는 7~40자리 소문자 16진수 `image_tag`가 필요하고 나머지 작업에는 빈 문자열을 사용합니다. 테스트 명세는 서버의 고정 샘플이며 비밀 값이나 임의 명세 입력은 받지 않습니다. 변경 API에는 로그인 쿠키, `Origin`, `X-CSRF-Token`이 필요합니다.

같은 작업의 응답이 유실되면 같은 UUID `request_id`와 본문으로 재시도합니다. 기존 작업은 `200`으로 반환하고 내용이 다르면 `409`입니다. 실패한 작업을 새로 실행하려면 새 UUID를 사용합니다. 상태는 `queued → running → succeeded/failed`이며 중단 시 `interrupted`입니다. `mock: true`와 결과의 `ok`, `error.message/hint/retryable`을 확인합니다. 실제 AWS 검증 API와 상태는 이 경로와 분리되어 있습니다.

작업은 두 개의 백그라운드 스레드에서 처리하고 같은 프로젝트의 동시 작업을 막습니다. 작업 시각은 UTC Unix 밀리초입니다. 로그에서 임의 진단 데이터와 알려진 비밀 패턴을 걸러내며, 예상하지 못한 예외의 원문은 저장하지 않습니다. 실제 어댑터 연결은 `MockRunner`를 자동 대체하는 방식이 아닌 별도 후속 작업입니다.

검증: `python -m pytest tests/test_mock_deployments.py -q`. PostgreSQL은 기존 `ANYSHIP_TEST_DATABASE_URL`의 독립 테스트 DB 규칙을 따릅니다. 브라우저 테스트는 `python -m tests.browser_fixture --mock` 후 `http://127.0.0.1:8001/_test_only/login`을 열어 진행합니다. 이 도우미는 별도 임시 DB와 가짜 GitHub만 사용하며 운영 앱에는 포함되지 않습니다.

## AWS 환경 등록 API

Service가 CloudFormation 링크를 반환하면 프론트엔드는 `target="_blank"`, `rel="noopener noreferrer"`로 엽니다. 이용자는 AWS 콘솔에서 IAM 생성에 동의하고 스택의 `CREATE_COMPLETE`를 확인한 뒤 Outputs의 `RoleArn`을 서비스에 입력합니다. 입력한 ARN은 검증과 별도로 DB에 저장합니다. Service는 연결된 AWS 어댑터의 `check`에 저장한 External ID를 전달하고, 성공한 경우에만 연결 완료로 처리합니다. 기본 실행은 어댑터 연결 대기 상태이며 AWS를 호출하지 않습니다. 기존 프론트엔드의 **AWS 환경** 메뉴에서 이 흐름을 실행합니다. AWS 콘솔의 자동 콜백은 사용하지 않습니다.

### 브라우저에서 직접 테스트

프론트엔드 변경 후 `frontend`에서 `pnpm build`를 실행합니다. 저장소 루트에서 기존 실행 도우미 `./scripts/start-local.ps1`을 실행하고 [AWS 환경](http://localhost:8000/#aws)을 엽니다. 도우미는 기존 로컬 PostgreSQL을 시작하고 마이그레이션을 적용합니다. 기존 로그인·프로젝트 데이터는 유지합니다. 이전 `/dev/aws` 주소도 같은 화면으로 이동합니다.

1. 기존 Service에서 GitHub로 로그인하고 사이드바의 **AWS 환경**을 선택합니다. AWS 주소에서 로그인하면 인증 후 해당 화면으로 돌아옵니다.
2. AWS 설정이 준비되면 이름과 리전을 선택하고 **등록 시작**을 누릅니다.
3. **AWS에서 역할 생성**을 눌러 본인의 AWS 계정에서 스택을 생성합니다. 현재 Infra 템플릿은 `AdministratorAccess`를 부여합니다.
4. `CREATE_COMPLETE`를 확인하고 Outputs의 `RoleArn`을 복사해 이전 탭에 붙여넣은 뒤 **Role ARN 저장**을 누릅니다. 서버의 AWS 인증 없이 저장할 수 있고, 새로고침이나 재로그인 후에도 DB에서 조회됩니다.
5. 어댑터 연결 전에는 **연결 확인 준비 중**으로 표시되며 ARN 저장까지 테스트할 수 있습니다. 어댑터가 연결되면 **연결 확인**이 활성화되고 입력한 ARN을 저장한 뒤 검증합니다. 검증 실패 시에도 ARN은 유지됩니다. 성공하면 연결 완료 상태와 검증된 계정 ID가 표시됩니다.

이 화면은 기존 로그인 세션과 실제 DB를 사용합니다. 기본 실행에서 실제 AWS 연결 성공을 모의 처리하지 않으며 AWS 키도 요구하지 않습니다. AWS 링크 설정이 비어 있으면 연결 준비 안내와 함께 등록을 비활성화합니다. 아래 설정을 `.env.github.local`에 입력한 뒤 서버를 재시작하고 브라우저를 새로고침하세요. Service의 성공·실패 처리는 자동 테스트의 가짜 어댑터로 검증하고, 실제 AssumeRole 통합 테스트는 AWS 어댑터가 준비된 후 진행합니다.

### 설정과 DB 준비

Service 가상환경에 `python -m pip install -r requirements-dev.txt`로 AWS SDK를 포함한 의존성을 설치합니다. 실제 서버에 적용할 때 기존 실행 설정 파일(`.env.github.local`) 또는 환경변수에 아래 값을 설정하고, 대상 DB를 확인한 후 Service 디렉터리에서 `python -m alembic upgrade head`를 실행합니다. 마이그레이션 `0005`는 `aws_environments` 테이블을 추가하고, `0006`은 검증 전 입력값을 위한 `submitted_role_arn`을 추가합니다. 기존 연결과 데이터를 보존하며, 이미 검증된 ARN은 입력값에도 복사합니다. 실행 중인 서비스의 DB에 자동 적용하지는 않습니다.

| 설정 | 내용 |
| --- | --- |
| `APP_AWS_TEMPLATE_URL` | 인프라 담당자가 제공한 HTTPS S3 템플릿 URL. 버전이 고정되고 이용자가 읽을 수 있는 URL 권장 |
| `APP_AWS_SERVICE_ROLE_ARN` | 사용자 역할의 신뢰 정책에 들어갈 서비스 서버 IAM 역할 ARN |
| `APP_AWS_REGIONS` | 지원할 리전 목록. 예: `ap-northeast-2,us-east-1` |
| `APP_AWS_ROLE_NAME` | 기본 `deploy-service-role`. 선택적으로 `{id}`를 넣으면 환경별 UUID를 사용 |

앞의 세 값이 모두 있어야 새 등록이 활성화됩니다. 검증에는 AWS 어댑터 연결도 필요합니다. 링크 설정이 없으면 등록·검증 API는 `503 aws_not_configured`를 반환하며 기존 GitHub 기능은 계속 사용할 수 있습니다. 데모 모드에서는 AWS 등록이 비활성화됩니다. `/api/config`의 `aws_available`은 링크 발급 가능 여부, `aws_verification_available`은 설정과 어댑터 연결 여부, `aws_regions`는 리전 선택지입니다. 이 값들은 실제 AWS 인증 성공을 보장하지 않습니다. 지원 파티션은 우선 `aws`이며 중국·GovCloud 파티션은 제외합니다.

AWS 인증과 AssumeRole은 실제 AWS 어댑터 실행 환경의 책임입니다. 운영에서는 인프라 #4의 서비스 서버 인스턴스 역할 등을 사용하며, 해당 역할과 사용자 역할 양쪽에서 AssumeRole을 허용해야 합니다. 고객의 Access Key/Secret Key를 입력받거나 저장하지 않습니다. Service의 링크 발급·ARN 저장·가짜 어댑터 자동 테스트에는 AWS 인증정보가 필요하지 않습니다.

**현재 인프라 이름 제약:** 기존 정책은 `arn:aws:iam::*:role/deploy-service-role`만 허용하므로 기본값을 이에 맞췄습니다. 이 구성에서는 AWS 계정마다 온보딩 역할 하나를 사용합니다. 동일 AWS 계정에 여러 독립 역할이 필요하면 인프라 담당자가 허용할 역할 이름 패턴을 먼저 정해야 합니다. 예를 들어 그에 맞는 권한이 준비된 후 `APP_AWS_ROLE_NAME=deploy-service-role-{id}`를 사용할 수 있습니다. Service가 인프라 정책을 변경하지 않습니다. 기존 템플릿은 `AdministratorAccess`를 부여하며, 아래 연결 검증은 최소 권한 검증이나 실제 배포 성공을 보장하지 않습니다.

### 요청과 응답

모든 환경 API는 로그인 세션 쿠키가 필요합니다. POST에는 기존 API와 동일한 `Origin` 및 `/api/me`에서 받은 `X-CSRF-Token` 헤더를 보냅니다. 환경은 현재 워크스페이스에 속하며 생성한 사용자만 조회·검증할 수 있습니다. 프로젝트와의 연결은 후속 범위입니다.

1. `POST /api/aws/environments`

   ```json
   {"request_id":"f0850611-4d63-4b29-9929-1fd39a353fe8","name":"운영 AWS","region":"ap-northeast-2"}
   ```

   프론트엔드는 등록 시작 시 UUID `request_id`를 한 번 만들고, 중복 클릭·응답 유실 시 동일한 ID와 본문으로 재시도합니다. 신규 요청은 `201`, 동일 요청의 재전송은 기존 레코드를 `200`으로 반환합니다. 같은 ID에 다른 이름·리전을 보내면 `409 request_conflict`입니다. 환경명은 표시용이며 중복될 수 있습니다. 새 등록에는 새 UUID를 사용합니다.

   반환 필드: `id`, `request_id`, `name`, `region`, `status`, `cloudformation_url`, `stack_name`, `role_name`, `submitted_role_arn`, `role_arn`, `aws_account_id`, `created_at`, `expires_at`, `verified_at`, `error_code`, `retryable`, `retry_after`. 시각은 UTC Unix 초입니다. 처음에는 `status=PENDING`, `submitted_role_arn/ role_arn/ aws_account_id/ verified_at=null`입니다. 링크는 저장한 템플릿 URL·서비스 역할 ARN·External ID·역할/스택 이름으로 조립합니다. External ID는 별도 응답 필드로 반환하지 않지만 온보딩 URL의 파라미터에 포함됩니다.

2. `POST /api/aws/environments/{id}/role`

   ```json
   {"role_arn":"arn:aws:iam::123456789012:role/deploy-service-role"}
   ```

   ARN 형식을 검사하고 `submitted_role_arn`에 저장합니다. AWS를 호출하지 않으며 AWS 설정이나 인증이 없어도 저장할 수 있습니다. 미연결 환경은 `PENDING`으로 전환하고 이전 검증 오류를 초기화합니다. `role_arn`, `aws_account_id`, `verified_at`은 검증 전에는 채우지 않습니다. 검증 중인 환경이나 만료된 환경은 수정할 수 없고, 연결 완료된 환경의 ARN 변경도 거부합니다. 검증 전 입력값에는 역할 중복 연결 제약을 적용하지 않습니다.

3. `POST /api/aws/environments/{id}/verify`

   ```json
   {"role_arn":"arn:aws:iam::123456789012:role/deploy-service-role"}
   ```

   External ID는 요청에 보내지 않습니다. Service가 DB의 값을 사용합니다. 사용자 ARN이나 STS 세션 ARN은 거부합니다. 검증을 시작할 때 입력값을 `submitted_role_arn`에 먼저 커밋하므로 AWS 호출 실패나 서버 중단 후에도 입력값이 남습니다. 성공 시 `200`으로 위와 같은 환경 정보를 반환하며, `status=CONNECTED`, 검증된 `role_arn`·계정 ID·검증 시각이 채워집니다. 연결된 역할로 같은 요청을 반복하면 저장된 결과를 반환하고 AWS 검증은 재실행하지 않습니다. 이미 연결된 환경의 Role ARN 변경은 `409 already_connected`입니다. `CONNECTED`는 마지막 온보딩 검증 결과이며 지속적인 권한 유효성 점검을 뜻하지 않습니다. 배포 등에서 사용할 때는 `CONNECTED`와 검증된 `role_arn`을 확인해야 하며 입력값만으로 연결됐다고 판단하면 안 됩니다.

4. `GET /api/aws/environments/{id}`로 개별 상태, `GET /api/aws/environments?limit=50&offset=0`으로 자신의 환경 목록을 조회합니다. 목록은 최신 생성 순이며 `limit`은 1~100입니다. 새로고침이나 재로그인 후 이 API로 저장한 ARN과 진행 상태를 복구할 수 있습니다.

5. `DELETE /api/aws/environments/{id}`는 자신이 등록한 환경 레코드를 삭제하고 `204`를 반환합니다. AWS 화면의 **현재 연결 상태 → 환경 삭제**에서 대상 이름과 삭제 범위를 확인한 뒤 실행합니다. 링크 설정이나 AWS 인증은 필요하지 않으며 만료·실패·연결 완료 환경도 삭제할 수 있습니다. 검증 진행 중에는 `409 verification_in_progress`를 반환하고, 검증 임대가 만료된 경우에는 삭제할 수 있습니다. 늦게 도착한 검증 응답은 삭제된 환경을 복구하지 않습니다. IAM 역할·CloudFormation 스택과 AWS 권한은 변경하지 않으며, 삭제 후 조회·재삭제는 `404`입니다.

어댑터 미연결 상태에서 미완료 환경의 `/verify`를 직접 호출하면 기존 인증·소유권·만료·검증 중 여부를 확인한 뒤 ARN을 저장하고 `503 aws_adapter_unavailable`을 반환합니다. 상태는 `PENDING`으로 유지하며 검증된 ARN·계정 ID·검증 시각을 채우지 않습니다. 이미 연결된 동일 ARN 요청은 저장된 결과를 그대로 반환합니다.

### 상태·오류·재시도

| 상태 | 의미와 다음 행동 |
| --- | --- |
| `PENDING` | 링크 발급 완료. ARN이 없으면 역할 생성·입력 대기, 저장한 ARN이 있으면 검증 대기 |
| `VERIFYING` | 역할 검증 진행 중. `retry_after`초 이내 중복 검증 요청은 409 |
| `FAILED` | 입력한 ARN과 External ID 유지. 원인을 해결한 후 같은 환경에서 재검증 |
| `EXPIRED` | 등록 후 24시간 경과. 새 `request_id`로 등록 시작 |
| `CONNECTED` | 검증된 연결 저장 완료. 등록 요청의 만료 시각이 지나도 유지 |

서버 중단으로 `VERIFYING` 상태가 남으면 120초 후 조회 응답은 `FAILED`와 `verification_interrupted`를 표시하고 검증을 다시 시도할 수 있습니다. 만료/중단 상태는 조회 시 저장된 시각을 기준으로 계산하므로 별도 스케줄러가 필요하지 않습니다. AWS 호출 중에는 DB 잠금을 유지하지 않으며, 이전 검증의 늦은 응답이 새 검증 결과를 덮어쓰지 못하도록 요청 토큰을 대조합니다.

도메인 오류는 `{"detail":{"code":"access_denied","message":"...","retryable":true}}` 형식입니다. 기존 로그인·CSRF 오류와 입력 형식 오류는 기존 FastAPI 형식을 유지합니다.

| HTTP / 코드 | 처리 |
| --- | --- |
| 403 `access_denied` | Role ARN·External ID·양쪽 역할 정책 확인. IAM 반영 지연이면 잠시 후 재시도 |
| 422 `external_id_not_required` | External ID 누락/오입력으로도 AssumeRole이 가능한 신뢰 정책 수정 |
| 422 `account_mismatch` | 반환 계정 ID와 Role ARN 계정 불일치. ARN 확인 |
| 503 `aws_adapter_unavailable` | ARN 저장 완료, AWS 어댑터 연결 대기. 준비된 후 같은 환경에서 검증 |
| 503 `service_credentials_unavailable` | 서비스 실행 역할의 인증 설정 확인 |
| 503 `aws_unavailable`, 502 `invalid_aws_response` | AWS 일시 오류 등으로 검증 미완료. 재시도 |
| 410 `request_expired` | 새로운 등록 요청 필요 |
| 409 `configuration_changed` | 서비스 역할 ARN 또는 지원 리전 정책 변경. 새 등록 요청 필요 |
| 409 `role_already_registered` | 동일 워크스페이스에 이미 연결된 Role ARN. 기존 환경 확인 |
| 409 `verification_in_progress` / `verification_superseded` | 상태를 다시 조회한 뒤 필요할 때 재시도 |

등록 만료는 AWS 링크나 생성된 IAM 역할·스택을 삭제하지 않습니다. 고정된 역할 이름으로 이미 스택을 만든 뒤 요청이 만료되면 새 요청의 External ID와 기존 신뢰 정책이 달라집니다. 기존 스택을 사용하지 않는지 확인한 뒤 AWS 콘솔에서 기존 스택 파라미터를 새 External ID에 맞게 갱신하거나 미사용 스택을 정리하고 다시 생성해야 합니다. Service는 스택을 수정·삭제하지 않습니다. 미리 서명된 S3 URL은 Service 요청보다 먼저 만료될 수 있으므로 템플릿 접근 방법은 인프라 담당자와 확인해야 합니다.

### 어댑터와 테스트

`app/aws_adapter.py`는 AWS SDK를 불러오지 않는 Service 측 계약입니다. 현재 접점은 `check(role_arn=..., external_id=..., region=...) -> AwsIdentity(account_id=...)`이며 실패 시 `AwsCheckError(code)`를 받습니다. AWS 어댑터 담당자와 계약을 확정한 뒤 이 접점에 맞춰 연결합니다. 실제 어댑터는 역할 접근 성공, External ID 필수 여부, 검증한 계정 일치를 확인해야 합니다. STS 임시 자격 증명은 어댑터 밖으로 반환하거나 DB·API 응답·로그에 기록하지 않습니다.

`create_app(settings, gateway=None, aws_adapter=None)`에 같은 계약의 어댑터를 주입할 수 있습니다. 기본 `None`은 검증 대기를 뜻하며 실제 STS 또는 성공을 반환하는 가짜 어댑터로 자동 대체하지 않습니다. 완성된 어댑터는 서버 생성 시 `aws_adapter` 인자로 연결합니다. 기존 STS 구현은 `app/aws_sts_adapter.py`에 참고 구현으로 분리해 두었고 기본 서버에서는 불러오지 않습니다. Service는 인증·소유권·상태 전이·DB 저장을, 어댑터는 AWS 검증을 담당합니다. 자동 테스트의 `FakeAWS`는 격리된 테스트 DB에서만 사용합니다.

`python -m pytest tests/test_aws_onboarding.py tests/test_aws_adapter.py tests/test_aws_config_migration.py -q`로 API·동시 요청·실패/만료·SDK 모의 응답·DB 업그레이드/다운그레이드를 확인합니다. 실제 AWS 리소스 생성이나 호출은 하지 않습니다. PostgreSQL 테스트는 기존 `ANYSHIP_TEST_DATABASE_URL` 계약(이름이 `_test`로 끝나는 DB, 테스트별 독립 스키마)을 따릅니다.

참고: [CloudFormation quick-create](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/cfn-console-create-stacks-quick-create-links.html), [타사 역할 접근과 External ID 검증](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_common-scenarios_third-party.html), [Boto3 STS](https://docs.aws.amazon.com/boto3/latest/reference/services/sts/client/assume_role.html).

## 실제 배포

`APP_DEPLOYMENT_MODE=real`이면 사용자가 연결한 저장소를 **사용자의 AWS 계정**에 배포합니다(`anyship_adapters.Deployer`). 위 Mock 배포와는 코드, 테이블, API가 모두 별개이고, 서로 자동으로 대체하지 않습니다. 기본값은 `unavailable`이라 켜지 않으면 동작이 바뀌지 않습니다.

### 흐름

```
저장소 연결 → AWS 환경 연결(CONNECTED) → 환경 선택 → 배포 → (처음이면 공용 기반 생성) → 앱 주소
```

한 번의 배포는 `소스 받기 → 이미지 빌드 → 공용 기반 확인(+DNS) → 연결 확인 → 배포 → 정리`입니다. 소스 받기는 요청 안에서(빠르게 실패를 알리려고), 나머지는 백그라운드 스레드에서 합니다. 진행 로그는 단계별로 DB에 쌓이고 화면이 1~2초마다 읽습니다. 공용 기반(호스트, RDS)을 처음 만들 때만 약 20분이 걸립니다.

### 설정 (`.env.github.local`, 값은 `.env.web.example` 참고)

| 변수 | 설명 |
|---|---|
| `APP_DEPLOYMENT_MODE=real` | 필수. 빠진 값은 서버가 뜰 때 **변수 이름만** 알리고 멈춥니다 |
| `APP_DEPLOY_SOURCE` | `github`(기본): 연결한 저장소의 브랜치를 사용자 토큰으로 GitHub에서 받음. `local`: 서버 폴더에 받아 둔 소스(시험용) |
| `APP_DEPLOY_SOURCE_DIR` | `local`일 때만 필수. 저장소 이름과 같은 하위 폴더를 배포 |
| `APP_DEPLOY_WORKSPACE` | `github`일 때 받은 소스를 잠시 두는 곳(기본 `service/workspaces/deploy-src`) |
| `APP_DEPLOY_SSH_KEY`, `APP_DEPLOY_SERVICE_IP`, `APP_DEPLOY_ACME_EMAIL`, `APP_DEPLOY_BASE_DOMAIN` | 필수 |
| `APP_DEPLOY_DNS` | `on`(기본): 앱 주소의 DNS 레코드(`*.<환경ID>.aws.<도메인>`)를 서비스가 Route 53에서 맞춤. `off`: 수동 관리 |
| `APP_DEPLOY_VERIFY_TLS` | 기본 `true`. Let's Encrypt staging 인증서를 시험할 때만 `false` |
| `APP_DEPLOY_TERRAFORM_DIR`, `APP_DEPLOY_PLUGIN_CACHE` | 선택 |

### 소스를 GitHub에서 받기

- 서비스에 저장된 사용자의 GitHub 토큰으로 연결한 브랜치를 **얕게 복제**(`--depth 1`)합니다. 토큰은 `git`의 인증 헤더로만 넘기고 주소나 로그, DB, 응답에 남기지 않으며, 스레드로도 넘기지 않습니다(소스는 요청 안에서 받아 두고 스레드에는 폴더만 넘깁니다).
- 이미지 태그는 받은 커밋의 앞 12자리입니다. 저장소 루트에 `Dockerfile`과 `deploy-spec.yaml`이 **있어야** 합니다(AI 연결 전의 전제). 서브모듈과 Git LFS는 받지 않습니다.
- 받은 임시 폴더는 배포가 끝나거나 실패하거나 요청이 중복이어도 **반드시 지웁니다**. 서버가 비정상으로 멈춰 남은 것은 다음 시작 때 지웁니다.
- 저장소 이름과 브랜치 이름은 형식을 엄격히 검사하고(옵션 주입, `..`, 줄바꿈 거절), 오류에는 git의 출력을 싣지 않습니다.

### API (`/api/projects/{id}/deployment`)

| 요청 | 설명 |
|---|---|
| `GET` | 현재 대상과 상태, 선택 가능한 환경(연결이 확인된 것만 `available`) |
| `PUT` | `{environment_id, set_name}` 저장. 한 번도 배포한 적이 없고 진행 중인 작업이 없을 때만 바꿀 수 있음 |
| `POST /jobs` | `{request_id, secrets}`로 배포. 새 작업은 `202`, 같은 `request_id`는 `200`으로 기존 작업을 돌려줌 |
| `POST /jobs` | `{request_id, action: "destroy"}`로 **배포 제거**. 비밀을 받지 않음 |
| `GET /jobs`, `GET /jobs/{id}` | 이력과 단계별 로그 |

- 사용자 비밀(`secrets`)은 요청 본문으로만 받고 DB, 로그, 응답 어디에도 남기지 않습니다. 이 경로의 검증 오류(422)는 입력값을 싣지 않는 고정 문구입니다.
- 실패한 작업은 `stage`로 단계를 알립니다: `source`(요청 안에서 즉시 오류), `spec`, `build`, `foundation`(DNS 포함), `check`, `deploy`, `destroy`, `environment`, `runner`.
- 같은 프로젝트에서는 한 번에 한 작업만 합니다(선점 유효 30분, 실행 중 연장). 서버를 다시 시작하면 진행 중이던 작업은 `interrupted`가 됩니다. 20분짜리 `terraform apply` 도중에 서버가 멈추면 Terraform 잠금이 남을 수 있고, 다음 배포가 `terraform_locked`로 실패하면 잠금을 풀어야 합니다.

### 배포 제거

앱의 컨테이너와 볼륨, 서버의 앱 폴더만 지웁니다. **앱 DB와 공용 기반(호스트, RDS), DNS 레코드는 남아** 요금이 계속 나옵니다. 지운 뒤에는 "아직 배포하지 않음"으로 돌아와 환경을 다시 고르거나 다시 배포할 수 있습니다. 공용 기반을 지우는 기능은 아직 없습니다.

### 시험

```bash
python -m pytest tests/test_source.py tests/test_deploy_runner.py tests/test_deploy_api.py tests/test_deployments_state.py   # AWS와 GitHub를 부르지 않는다
python -m tests.browser_fixture --deploy   # 가짜 배포자로 화면을 확인하는 도우미(http://127.0.0.1:8001/_test_only/login)
```

서버에서 진짜 AWS로 확인하려면 `scripts/seed_test_environment.py`와 `scripts/smoke_deploy_api.py`(로컬 폴더 소스 고정), 또는 웹 화면에서 직접 배포합니다.

### 데이터 모델

`python -m alembic upgrade head`로 `0008`을 적용하면 다음이 추가됩니다. 기존 데이터는 그대로이고 새 컬럼은 비어 있습니다.

| 대상 | 내용 |
|---|---|
| `aws_environments` 컬럼 | `env_id`, `host`, `db_address`, `db_port`, `db_secret_arn`, `state_bucket` (모두 NULL 허용) |
| `deployments` | 프로젝트당 하나의 실제 배포 대상: AWS 환경, 세트 이름, 앱 이름, 현재 이미지 태그, URL, 진행 중 작업과 `lease_until` |
| `deploy_jobs` | 작업 이력: `(프로젝트, 요청 ID)`가 유일, 동작, 상태, 실패한 `stage`, 로그, 결과 |

- `env_id`는 DNS 이름과 Terraform state의 키에 쓰는 **바뀌지 않는 값**(최대 21자, 유일)입니다. 정해지지 않았으면 환경 레코드 ID에서 `e` + 20자로 정합니다. 이미 기반을 만들어 둔 계정은 만들 때 쓴 값(예: `test`)을 직접 넣어야 기반을 찾습니다.
- `host`, `db_address`, `db_port`, `db_secret_arn`은 공용 기반의 출력이고 `state_bucket`은 Terraform state를 두는 사용자 계정의 S3 버킷입니다. **모두 비밀이 아닙니다.** DB 비밀번호는 사용자 계정의 Secrets Manager에만 있고, 사용자가 배포 때 입력하는 비밀은 어느 컬럼에도 저장하지 않습니다.
- `deployments.lease_until`은 작업 선점의 만료 시각(초)입니다. 첫 배포에서 공용 기반을 만드는 데 약 20분이 걸리므로 TTL은 그보다 길어야 합니다(25~30분 이상).

`app/deploy_state.py`가 환경 레코드와 어댑터 사이를 잇습니다. 값을 바꾸면 곧바로 커밋합니다.

| 함수 | 하는 일 |
|---|---|
| `assign_env_id(session, row)` | `env_id`가 없으면 정하고, 있으면 바꾸지 않습니다 |
| `adapter_environment(row)` | 어댑터의 `AwsEnvironment`로 변환합니다. **`CONNECTED`이고 검증된 `role_arn`이 있는 환경만** 허용하며, 저장만 해 둔 `submitted_role_arn`으로 대신하지 않습니다 |
| `ensure_state_bucket(session, row, access)` | `state_bucket`이 비어 있으면 `stack_name`의 온보딩 스택 출력(`StateBucketName`)에서 읽어 저장합니다 |
| `save_foundation(session, row, fields)` | 배포가 성공하면 결과의 `details["foundation"]` 4개 값을 저장합니다. 어댑터 모델의 규칙(RDS 도메인, 같은 계정의 비밀 ARN 등)을 통과해야 합니다 |

오류는 `DeployStateError(code, message)`이고 문구에 저장된 값을 싣지 않습니다. 스택 이름은 사용자가 콘솔에서 바꿀 수 있어서 `ensure_state_bucket`은 `stack_not_found`로 실패할 수 있습니다(어댑터의 `AwsAccess.read_state_bucket`이 내는 오류 코드: `stack_not_found`, `stack_not_ready`, `stack_output_invalid`, `invalid_stack_name`).

**시험**

```bash
python -m pytest tests/test_real_deployment_migration.py tests/test_deploy_state.py -q   # SQLite. AWS를 부르지 않는다
```

실제 계정으로 확인하려면 서버에서 시험용 SQLite DB에 환경 한 건을 만들고(서비스 운영 DB는 건드리지 않음) 스크립트를 돌립니다.

```bash
cd service
python ../scripts/seed_test_environment.py --database ~/anyship-test.db --role-arn <역할 ARN> --stack-name <온보딩 스택 이름>   # External ID는 입력창으로
APP_DATABASE_URL=sqlite:////home/<사용자>/anyship-test.db python ../scripts/smoke_deploy_state.py --environment-id <출력된 ID> --env-id test
```

`smoke_deploy_state.py`는 진짜 `describe_stacks`로 `StateBucketName`을 읽고, `ensure_state_bucket`과 `TerraformRunner.read_foundation` 결과의 `save_foundation`까지 확인합니다(테스트 계정에서 11/11).
PostgreSQL 마이그레이션은 서버에서 `alembic upgrade head`가 성공했고 테이블과 컬럼이 만들어진 것까지 확인했습니다. 다운그레이드는 SQLite 테스트로만 확인했습니다.

## 등록한 저장소 연결 삭제

프로젝트 상세 화면 아래의 **저장소 연결 삭제**에서 대상을 확인하면 `DELETE /api/projects/{id}`를 호출합니다. 로그인·Origin·CSRF와 현재 워크스페이스 소속을 확인하고, 프로젝트 및 서비스 DB의 분석·검토 기록(`CodeChange`, `DemoChange`)을 한 트랜잭션으로 삭제해 `204`를 반환합니다. 진행 중인 작업이 있으면 정리를 취소하고 `409`를 반환합니다. 삭제 후 목록에서 사라지고 상세 조회·재삭제는 `404`이며, 같은 저장소를 다시 연결할 수 있습니다.

삭제는 GitHub API를 호출하지 않으므로 GitHub 접근 권한을 잃은 뒤에도 사용할 수 있습니다. 원본 저장소·브랜치·PR·GitHub App 설치와 로컬 데모 작업 폴더는 변경하지 않습니다. 실제 사용자 데이터의 삭제 테스트는 하지 않으며 `tests/test_registration_deletion.py`에서 격리된 DB와 외부 API 대역으로 소유권, 작업 중 삭제 차단, 관련 데이터 정리 및 외부 리소스 보존을 검증합니다.

## GitHub 모듈

`github/`는 저장소 복제, 브랜치 생성, 변경 확인, 커밋·푸시, PR 생성을 담당하는 모듈입니다. `tests/github_manual.py`는 이 기능들을 연결해 실제 GitHub 저장소에서 실행하는 수동 테스트입니다.

자동 테스트부터 실행한 뒤, 수동 테스트의 `prepare`로 작업 폴더를 준비하고 직접 파일을 수정합니다. 마지막으로 `publish`를 실행하면 변경 사항을 커밋·푸시합니다. HTTP 서버를 실행할 필요는 없습니다.

## 다른 프로젝트에서 모듈 사용

공개 인터페이스는 `from github import ...`입니다. 하위 파일의 함수는 내부 구현이며, 호출 코드는 `GitHubRepository`를 사용하세요.

다른 프로젝트의 Python 환경에서 이 저장소의 `service` 경로를 지정해 설치합니다. 예시 경로는 자신의 체크아웃 위치로 바꿉니다.

```powershell
python -m pip install "C:\path\to\project\service"
```

모듈 개발 환경에서는 `service` 안에서 편집 가능 설치를 사용할 수 있습니다.

```powershell
python -m pip install -r requirements-dev.txt
```

설정과 코드 수정은 호출자가 담당합니다. 객체를 생성하는 것만으로 파일이나 네트워크 작업을 수행하지 않습니다. 다음 코드는 각 메서드를 호출할 때 실제 복제·커밋·푸시·PR 생성을 수행하는 예시입니다. `repo.clone()`에는 아직 존재하지 않는 대상 경로를 사용하세요.

```python
import os

from github import GitHubRepository

repo = GitHubRepository(
    url="https://github.com/owner/repo",
    path="./workspaces/repo",
    token=os.environ["GITHUB_TOKEN"],
)

repo.clone()
repo.create_branch("work/update-docs")

readme = repo.path / "README.md"
text = readme.read_text(encoding="utf-8")
readme.write_text(text + "\nUpdated documentation.\n", encoding="utf-8")
(repo.path / "hello.py").write_text('print("hello")\n', encoding="utf-8")

print(repo.get_changes())
commit = repo.commit(
    "docs: update documentation and example",
    author_name="Example Developer",
    author_email="developer@example.com",
)
print(commit.created, commit.sha)
repo.push()

pr = repo.create_pull_request(
    title="Update documentation and example",
    body="Add usage details and a Python example.",
    draft=True,
)
print(pr.number, pr.url)
```

이미 복제된 저장소는 같은 경로로 객체를 만든 뒤 `inspect()`로 확인하면 됩니다. 다시 `clone()`하지 않습니다. 라이브러리는 `.env`를 자동 로드하지 않으며 `GITHUB_ALLOWED_REPO`도 읽지 않습니다. 호출자가 접근 범위를 결정해야 합니다.

| 메서드 | 반환값과 동작 |
| --- | --- |
| `clone(branch=None)` | `Path`. 기본 브랜치 또는 지정 브랜치를 새 경로에 복제 |
| `get_default_branch()` | `str`. GitHub 기본 브랜치 조회 |
| `inspect(base_branch=None)` | `Workspace(repository, path, branch)`. 루트 경로·원격 URL·현재 브랜치 확인. `base_branch`를 전달하면 해당 브랜치도 거부 |
| `create_branch(name)` | `Workspace`. 새 브랜치 생성·전환 |
| `get_changes()` | `str`. 새 파일을 포함한 변경 상태 |
| `get_diff()` | `str`. HEAD 대비 추적 파일 변경 내용. 미추적 파일 내용은 제외 |
| `commit(message, author_name=None, author_email=None)` | `CommitResult(created, sha, summary)`. 전체 변경 스테이징·커밋. 변경이 없으면 `created=False`, `sha=None` |
| `push()` | `PushResult(repository, branch)`. 현재 작업 브랜치 푸시. 기본 브랜치·detached HEAD는 거부 |
| `create_pull_request(title, body="", base=None, draft=True)` | `PullRequest(number, url)`. 푸시된 현재 브랜치의 PR 생성. 자체 커밋·푸시는 하지 않음 |

결과 객체는 변경 불가능한 dataclass입니다. `.url`, `.sha`처럼 속성으로 접근할 수 있습니다. 기본 브랜치 푸시 제한은 `push()`에 적용되며, `commit()`은 현재 브랜치의 로컬 커밋을 수행합니다. 커밋 전에도 기본 브랜치를 제한하려면 `inspect(base_branch=repo.get_default_branch())`로 확인하세요.

### 오류 처리

```python
from github import AuthenticationError, GitCommandError, GitHubError

try:
    repo.push()
except AuthenticationError:
    print("GitHub 토큰, 권한 또는 접근 정책을 확인하세요.")
except GitCommandError:
    print("Git 실행 환경, 인증 또는 브랜치 상태를 확인하세요.")
except GitHubError as error:
    print(str(error))
```

| 예외 | 의미 |
| --- | --- |
| `GitHubError` | 공개 모듈 예외의 공통 부모 |
| `ValidationError` | 빈 커밋 메시지·PR 제목 등 잘못된 입력 |
| `InvalidRepositoryError` | 잘못된 URL, 기존 복제 경로, 원격 불일치 등. `ValidationError`의 하위 타입 |
| `AuthenticationError` | 빈 토큰 또는 HTTP 401·403 접근 거부. 권한 외에 GitHub 정책·제한도 확인 |
| `GitCommandError` | Git 실행·시간 초과·로컬 파일 작업 실패. Git을 통한 인증 실패도 이 타입으로 반환 |
| `GitHubAPIError` | GitHub 네트워크·응답 오류. HTTP 오류는 `status_code`로 확인 가능 |

공개 예외 메시지에는 원본 Git 출력이나 HTTP 인증 데이터를 포함하지 않습니다. 실패 후 자동 삭제·강제 푸시·재시도는 하지 않으며, 호출자가 남은 작업 상태를 확인해 후속 조치를 결정합니다.

## 패키지 파일 만들기

`service`에서 실행하면 `dist`에 wheel 파일이 생성됩니다. 테스트 코드, `.env`, 작업 저장소는 패키지에 포함되지 않습니다.

```powershell
python -m pip wheel --no-deps . --wheel-dir dist
```

생성한 `github-0.1.0-py3-none-any.whl`을 다른 환경에서 `python -m pip install <wheel 경로>`로 설치할 수 있습니다. 외부 패키지 저장소에는 자동 게시하지 않습니다.

## 1. 실행 환경 준비

Python 3.12와 Git을 사용할 수 있는 환경을 기준으로 합니다. 아래 명령은 Windows PowerShell용이며, 프로젝트를 받은 위치에서 `service` 디렉터리로 이동해 실행합니다.

```powershell
cd .\service
python --version
git --version
```

가상환경이 없는 경우에만 생성합니다. `python`은 설치한 Python 3.12 실행 파일을 가리켜야 합니다.

```powershell
python -m venv .venv
```

새 환경에는 개발·테스트 의존성을 설치합니다. 이미 설치된 환경이면 생략할 수 있습니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

가상환경에 `pip`가 없으면 다음을 먼저 실행합니다. `ensurepip`도 지원하지 않는 배포판이라면 표준 Python 설치로 별도 가상환경을 준비하세요.

```powershell
.\.venv\Scripts\python.exe -m ensurepip --upgrade
```

`requirements.txt`는 모듈 실행 의존성이고, `requirements-dev.txt`는 자동·수동 테스트 의존성을 포함합니다. 아래에서는 가상환경 활성화 없이 Python 경로를 직접 지정합니다.

## 2. 자동 테스트

자동 테스트에는 GitHub 토큰이나 `.env`가 필요하지 않습니다. GitHub 호출과 원격 푸시는 모의 처리하고, 일부 테스트는 임시 로컬 Git 저장소에서 실제 커밋을 검증합니다.

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

전체 테스트에는 web 의존성이 필요합니다. 기존 GitHub 모듈과 웹 인증·권한·실제 GitHub API 게시 흐름을 함께 검증합니다. 특정 기능만 확인하려면 파일을 지정합니다.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_repository.py -v
.\.venv\Scripts\python.exe -m pytest tests/test_changes.py -v
.\.venv\Scripts\python.exe -m pytest tests/test_pull_request.py -v
```

`test_manual_*.py`도 모의 호출을 사용하는 자동 테스트입니다. `github_manual.py`는 일반 `pytest` 실행으로 실제 GitHub 작업을 시작하지 않습니다.

## 3. 수동 테스트용 GitHub 토큰 발급

본인에게 쓰기 권한이 있는 테스트 저장소를 준비합니다.

1. [GitHub Fine-grained tokens](https://github.com/settings/personal-access-tokens)에서 **Generate new token**을 선택합니다.
2. 이름과 만료 기간을 설정합니다.
3. **Resource owner**에서 저장소 소유 계정 또는 조직을 선택합니다.
4. **Repository access → Only select repositories**에서 테스트 저장소를 선택합니다.
5. **Repository permissions**에 아래 권한을 추가합니다.
6. **Generate token**을 누르고 발급된 값을 복사합니다. 기존 토큰의 권한을 수정하는 경우에는 **Update**로 저장합니다.

| 저장소 권한 | 설정 | 용도 |
| --- | --- | --- |
| Contents | Read and write | 복제·코드 푸시 |
| Pull requests | Read and write | Draft PR 생성 |
| Metadata | Read-only | 저장소 정보 조회 |

**Account permissions** 메뉴가 열렸다면 닫고 저장소 선택과 **Repository permissions**를 확인하세요. 이 테스트에 계정 권한을 추가할 필요는 없습니다. 조직 정책에 따라 토큰 사용 승인이 필요할 수 있습니다.

발급 절차와 조직 정책은 [GitHub 공식 토큰 안내](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)를 참고하세요. 위 권한은 일반 파일 수정 기준이며, Actions 워크플로 파일 수정 등은 추가 권한이 필요할 수 있습니다.

## 4. 로컬 토큰 설정

기존 설정을 덮어쓰지 않도록 `.env`가 없을 때만 복사합니다.

```powershell
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
}
notepad .env
```

다음 값을 실제 토큰과 저장소명으로 바꾸고 저장합니다.

```dotenv
GITHUB_TOKEN=발급받은_실제_토큰
GITHUB_ALLOWED_REPO=owner/repo
```

`GITHUB_ALLOWED_REPO`에는 URL 대신 `소유자/저장소명`을 입력합니다. 토큰은 `.env`에만 저장하고 `.env.example`, 코드, 커밋, 채팅에 넣지 않습니다. `.env`는 Git 추적에서 제외됩니다.

수동 테스트는 `service/.env`를 읽습니다. 같은 이름의 환경변수가 이미 설정되어 있으면 환경변수가 우선합니다. 이 허용 저장소 제한과 설정 로드는 테스트 실행 로직에 속하며, 개별 `github/` 함수는 호출자가 전달한 값을 사용합니다.

## 5. 작업 폴더 준비

아래 예시의 `owner/repo`를 설정한 저장소명으로 바꿉니다.

```powershell
$repoUrl = "https://github.com/owner/repo"
$repoDirectory = ".\workspaces\repo"
$workBranch = "work/manual-test"

.\.venv\Scripts\python.exe -m tests.github_manual prepare $repoUrl $repoDirectory --branch $workBranch
```

새 경로이면 기본 브랜치를 복제하고 작업 브랜치를 생성합니다. 처음 실행할 때 대상 폴더를 미리 만들 필요는 없습니다. 성공하면 `prepared`, 작업 폴더, 브랜치가 출력됩니다. 이 단계에서는 푸시하지 않습니다.

- 상대 경로는 현재 디렉터리를 기준으로 해석합니다. 절대 경로도 지정할 수 있습니다.
- `--branch`를 생략하면 `ai/manual-...` 이름을 생성합니다.
- 기존 경로는 Git 저장소 최상위 경로, 원격 URL, 작업 브랜치를 확인한 후 재사용합니다.
- 기존의 빈 폴더나 다른 저장소를 덮어쓰지 않습니다. 다른 브랜치를 요청해도 자동 전환하지 않습니다.
- 기존 저장소를 재사용할 때 자동으로 fetch·pull하여 최신화하지 않습니다.

`service/workspaces/`는 Git 추적에서 제외됩니다. 작업 폴더는 실행 후에도 유지됩니다.

## 6. 텍스트 수정과 코드 추가

복제한 작업 폴더 안에서 편집기로 파일을 수정합니다. 예를 들어 `README.md` 문구를 변경하고 `src/`에 코드 파일을 추가할 수 있습니다. 수동 테스트는 데모 파일을 자동 작성하지 않습니다.

변경 사항을 검토합니다.

```powershell
git -C $repoDirectory status --short
git -C $repoDirectory diff
git -C $repoDirectory diff --cached
```

새 미추적 파일의 내용은 `diff`에 나오지 않으므로 편집기에서도 확인합니다. 대상 프로젝트의 테스트가 있다면 수정한 코드에 맞게 별도로 실행합니다.

## 7. 커밋과 푸시

브랜치만 푸시하려면 다음 명령을 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m tests.github_manual publish $repoUrl $repoDirectory
```

Draft PR도 만들려면 위 명령 대신 다음을 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m tests.github_manual publish $repoUrl $repoDirectory --pr
```

**이 단계는 실제 GitHub를 변경합니다.** Git이 무시하지 않는 수정·추가·삭제 사항 전체를 스테이징하고, 변경이 있으면 커밋한 뒤 작업 브랜치를 푸시합니다. 변경이 없어도 기존 커밋을 푸시하므로 푸시 실패 후 재시도할 수 있습니다.

수동 테스트는 커밋 작성자 `Automation Bot`, 이메일 `automation-bot@example.com`, 메시지 `chore: apply automated code changes`를 전달합니다. 공개 모듈에서는 호출자가 값을 지정할 수 있으며, 작성자를 생략하면 기존 Git 설정을 사용합니다. 전달한 작성자 정보는 해당 커밋 명령에만 적용하고 저장소 설정을 덮어쓰지 않습니다.

| 결과 상태 | 의미 |
| --- | --- |
| prepared | 작업 폴더·브랜치 준비 완료 |
| pushed | 브랜치 푸시 완료 |
| created | 푸시 및 Draft PR 생성 완료 |

PR은 기본 브랜치를 대상으로 생성되며 자동 병합하지 않습니다. 출력된 URL에서 수정 내용과 새 코드가 포함되었는지 확인합니다.

## 8. 이어서 수정하기

같은 작업 폴더를 다시 수정하고 `publish`를 실행합니다. 이미 PR이 있다면 `--pr` 없이 실행하세요. 같은 브랜치의 기존 PR에 변경이 반영됩니다.

```powershell
.\.venv\Scripts\python.exe -m tests.github_manual publish $repoUrl $repoDirectory
```

`--pr`은 새 PR 생성 요청이며, 기존 PR을 조회해서 재사용하는 기능은 없습니다. 새로운 작업을 시작하려면 다른 작업 폴더와 새 브랜치로 `prepare`를 실행할 수 있습니다.

## 9. JSON 출력과 도움말

실행할 명령 뒤에 `--json`을 붙이면 정상 결과는 표준 출력으로, 오류는 표준 오류로 JSON을 출력합니다. 인자 파싱 오류와 도움말은 일반 텍스트로 출력됩니다.

```powershell
.\.venv\Scripts\python.exe -m tests.github_manual prepare $repoUrl $repoDirectory --json
.\.venv\Scripts\python.exe -m tests.github_manual prepare --help
.\.venv\Scripts\python.exe -m tests.github_manual publish --help
```

`publish`에도 `--json`을 사용할 수 있으며 실제 푸시 동작은 동일합니다.

## 10. 실패 시 확인 사항

명령 실행 직후 종료 코드를 확인합니다.

```powershell
$LASTEXITCODE
```

| 코드 | 의미 | 확인할 사항 |
| --- | --- | --- |
| 0 | 정상 완료 | 출력된 상태·브랜치·PR URL 확인 |
| 1 | Git·네트워크·파일 작업 실패 | Git 설치, 토큰 만료·권한·조직 승인, 네트워크, 원격 브랜치 규칙 확인 |
| 2 | 설정·입력·작업 폴더 검증 실패 | `.env`, 허용 저장소, URL, 작업 경로, 브랜치 확인 |
| 3 | 푸시 후 PR 생성 결과 확인 실패 | GitHub에 PR이 이미 생성됐는지 확인한 뒤 재시도 |
| 130 | 사용자 중단 | 로컬 커밋과 GitHub 상태 확인 |

작업 경로는 저장소 최상위 디렉터리여야 하며, `origin`의 가져오기·푸시 URL은 요청한 GitHub HTTPS 저장소와 일치해야 합니다. SSH URL, 기본 브랜치, 브랜치가 선택되지 않은 detached HEAD 상태는 지원하지 않습니다.

푸시가 실패해도 로컬 커밋과 작업 폴더는 유지됩니다. 원인을 해결한 뒤 같은 경로에서 `publish`를 다시 실행하세요. PR 결과가 불명확한 경우 먼저 GitHub를 확인하고, 이미 PR이 있으면 `--pr`을 빼고 진행합니다. 원격과 이력이 충돌하면 상태를 검토해 해결해야 하며, 테스트 도구는 강제 푸시나 자동 병합을 수행하지 않습니다.
