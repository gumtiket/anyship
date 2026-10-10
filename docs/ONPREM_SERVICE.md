# 온프레미스 서비스 연결

이슈 [#68](https://github.com/gumtiket/anyship/issues/68). Infra의 온프레미스 준비 작업 #63을 바탕으로 서비스 등록과 프로젝트 배포를 연결한다. 현재 전송은 SSH이며 에이전트는 구현하지 않는다.

## 실행 준비

Service 의존성과 프런트엔드를 설치·빌드한 뒤, 대상 DB를 확인하고 `service/`에서 `python -m alembic upgrade head`로 `0010`을 적용한다. 기존 AWS 환경·배포·작업은 유지된다. 온프레미스 배포 대상이 남아 있으면 `0009`로의 다운그레이드를 거부한다. 환경 등록·작업 이력은 다운그레이드 시 삭제되므로 DB 백업이 필요하다.

기존 실제 배포 설정(`APP_DEPLOYMENT_MODE=real`)을 사용한다. `APP_DEPLOY_SSH_KEY`와 그 경로에 `.pub`을 붙인 공개 키 파일, Docker·Git·SSH 실행 환경을 준비한다. 공개 키는 현재 준비 스크립트가 지원하는 ed25519 형식이어야 한다. `APP_APP_ORIGIN`은 대상 서버에서 접근 가능한 서비스 HTTPS 주소여야 한다. 로컬 주소는 화면 자동 검증용이며 외부 서버의 신고를 받을 수 없다.

현재 실제 배포 실행기는 AWS와 온프레미스를 함께 조립하므로 기존 `APP_DEPLOY_SERVICE_IP`, `APP_DEPLOY_ACME_EMAIL`, `APP_DEPLOY_BASE_DOMAIN`, Terraform 경로 검증도 유지한다. 온프레미스 작업은 AWS 공용 기반/Terraform/AssumeRole을 호출하지 않는다. `APP_DEPLOY_DNS=on`이면 서비스 실행 역할에 Route 53의 온프레미스 와일드카드 레코드 관리 권한이 필요하다. `off`이면 DNS는 직접 관리한다. 인증서의 기본 staging 설정과 TLS 검증 설정은 [어댑터 안내](../infra/adapters/README.md)를 따른다.

시험 대상은 Amazon Linux 2023 x86_64, 공인 IPv4, 접속 가능한 22/80/443 포트다. 준비 스크립트는 Docker, deploy 계정, Traefik을 설치하며 서버 전체의 root·비밀번호 SSH 로그인을 끈다. 기존 관리 접속을 유지한 상태에서 실행한다. 공유 SSH 키 하나를 사용하며 환경별 키, 사설망, Ubuntu, 에이전트 지원은 후속 범위다.

## 사용자 흐름

1. 로그인 후 **온프레미스 환경**에서 이름과 인증서 안내 이메일을 입력한다.
2. **등록하고 준비 명령 받기**로 발급된 명령을 대상 서버에서 실행한다. 명령에는 15분짜리 일회용 토큰이 있으므로 공유하거나 기록하지 않는다. 명령은 다운로드를 완료한 뒤 실행하고 임시 파일을 제거한다.
3. 서버가 준비 신호를 보내면 `ISSUED → SIGNALED`로 바뀐다. 서비스가 `Deployer.check`를 실행하고 독립적으로 관측한 IP가 신고 주소와 일치해야 `VERIFIED`로 바뀐다. 신고만으로는 배포할 수 없다. 실패 시 원인을 해결하고 **연결 다시 확인**을 누른다.
4. 프로젝트 배포 화면에서 확인된 온프레미스 환경을 선택·저장한 뒤 배포한다. 상태 조회와 서버에 남은 커밋 SHA로의 롤백을 지원한다. 롤백은 DB 스키마를 되돌리지 않는다.
5. **배포 제거**는 앱 컨테이너·볼륨·파일을 제거하므로 앱 데이터도 삭제된다. 환경 DNS와 공용 프로그램은 남는다. 배포 실패로 리소스가 일부 남을 수 있어 실패한 앱도 이 순서로 정리해야 한다.
6. 남은 앱과 진행 중인 작업이 없으면 환경 화면의 **환경 정리**로 해당 환경 DNS와 서비스 등록을 정리한다. 서버 자체와 Docker·deploy 계정·Traefik은 유지된다. 다른 환경의 DNS는 건드리지 않는다.

토큰은 DB에 SHA-256 해시만 저장한다. 원문은 최초 발급·재발급 응답의 명령에만 표시하고 목록이나 중복 등록 응답에서는 반환하지 않는다. 준비 스크립트를 받기 위해 본문에 토큰을 보내며, 신고가 성공할 때 한 번 소비한다. 모든 토큰은 환경에 한정되고 재발급하면 이전 토큰은 무효화된다. 사용 중인 환경에서는 재발급을 거부한다. 서비스/프록시에서 요청·응답 본문을 로깅하지 않는다. 토큰은 URL에 넣지 않는다.

## API와 실행 경계

일반 API는 기존 로그인 세션·소유권·워크스페이스 검사를 사용하고 변경 요청에는 Origin/CSRF가 필요하다. `/setup`, `/ready`만 로그인 대신 본문의 등록 토큰을 검증한다.

| 요청 | 내용 |
| --- | --- |
| `POST /api/onprem/environments` | UUID `request_id`, `name`, `email`, 선택적 `connection_kind=ssh`. 새 등록은 201, 동일 요청은 200과 `registration=null` |
| `GET /api/onprem/environments` | 소유한 활성 환경 상태·안내·검증된 IP·마지막 확인 시각 |
| `POST /api/onprem/environments/{id}/registration` | 준비 명령 재발급. 기존 명령 무효화 |
| `POST /api/onprem/environments/{id}/setup` | `token` 본문으로 준비 스크립트 요청. `Cache-Control: no-store` |
| `POST /api/onprem/environments/{id}/ready` | `token`, `public_ip`. 토큰 소비·상태 저장·check 작업 생성을 한 트랜잭션으로 처리 |
| `POST /api/onprem/environments/{id}/jobs` | UUID `request_id`, `action=check\|remove_environment` |
| `GET /api/onprem/environments/{id}/jobs` | 최근 환경 작업 50개. 정리된 환경의 이력도 소유자가 조회 가능 |
| `PUT /api/projects/{id}/deployment` | `environment_id`, `set_name=onprem` |
| `POST /api/projects/{id}/deployment/jobs` | UUID `request_id`, `action=deploy\|status\|rollback\|destroy`. rollback만 `image_tag`, deploy만 `secrets` 허용 |

표시 시각은 Unix 밀리초다. 프로젝트와 무관한 check/환경 정리는 `OnpremJob`, 프로젝트 작업은 기존 `DeployJob`에 남는다. 환경 전체에 하나의 임대를 적용하여 서로 다른 프로젝트의 배포와 환경 정리가 겹치지 않도록 한다. 중복 작업은 같은 결과를 반환하고 만료된 작업은 interrupted로 정리한다. 재시작하면 기존 작업은 중단 처리되며 새 요청으로 재시도한다. 서비스 DB마다 실행기 프로세스 하나만 지원한다.

`app/onprem_transport.py`만 SshRunner/SshConnection과 연결 필드를 해석한다. API/실행기는 이 모듈이 제공하는 환경 변환·명령·안내·오류 문구를 사용한다. OnpremAdapter에는 `connect=transport.connect`를 주입한다. 이미지 전달은 어댑터의 `ComposeHost.load_image`를 거치며 서비스에는 임의 원격 명령을 추가하지 않는다. 어댑터 오류 코드는 유지한다. DB에는 nullable host/ssh_user/ssh_port와 후속 자격 증명용 credential_ref를 둔다.

## 자동 검증과 남은 검증

`service/tests/test_onprem_integration.py`는 가짜 connect와 실제 어댑터를 사용해 등록·신고·check·배포·상태 조회·롤백·삭제·환경 정리를 검증한다. 토큰 해시·만료·일회성·환경 범위, 동시 신고, 소유권/CSRF, 비밀 마스킹, 중복 요청, 늦은 작업 결과, 실패한 배포의 정리 순서와 DNS 격리도 검사한다. `test_onprem_migration.py`는 AWS 데이터 보존과 대상 제약/다운그레이드를 검증한다. `infra/adapters/tests/test_transport_contract.py`의 전송 계약은 나중에 에이전트 fixture에도 재사용할 수 있다. 셸 계약 테스트는 로컬 POSIX 셸만 사용하고 서버에 접속하지 않는다.

서비스 테스트 실행 시 실제 로컬 `.env` 로딩을 피하려면 `PYTHON_DOTENV_DISABLED=1`을 사용하고 실제 `APP_*` 변수를 상속하지 않는 테스트 프로세스로 실행한다. Windows 셸 테스트에는 Git Bash를 PATH 앞에 둔다. PostgreSQL 테스트는 기존 `ANYSHIP_TEST_DATABASE_URL`의 `_test` DB/임시 스키마 규칙을 사용한다.

브라우저 검증은 `service/`에서 `python -m tests.browser_fixture --onprem`을 실행하고 `http://127.0.0.1:8001/_test_only/login`을 연다. 환경을 등록한 뒤 `/_test_only/onprem/ready`로 가장 최근 환경의 신고를 모의 실행한다. 이후 프로젝트 화면에서 전체 흐름을 확인한다. 이 도우미는 임시 DB와 가짜 서버·DNS를 사용하며 운영 앱에는 포함되지 않는다.

2026-10-10 검증: 시험 서버가 없어 실서버 검증은 수행하지 않았다. PostgreSQL 실행 파일은 이 PC의 Device Guard 정책으로 차단되어 이번 변경의 PostgreSQL 실행 검증도 미실시다. 실제 서버 등록→신고→check, 앱 배포·삭제, 환경 DNS 정리는 시험 환경이 준비된 뒤 확인해야 한다. 자동 검증 통과는 실제 연결 성공을 보장하지 않는다.
