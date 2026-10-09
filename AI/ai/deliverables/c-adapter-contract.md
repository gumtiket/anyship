# C 답변에 맞춘 B 출력 계약 — 2026-10-10

기준은 C의 2026-10-10 답변과 main에 머지된 C PR #41이다. B의 변경안 생성과 샘플 검증 범위는 유지한다.
서비스/인프라 코드와 기존 데이터는 수정하지 않는다.

Windows 호환(#32), LLM 범위 검사·diff 정규화(#33), Anthropic 제공자(#39)가 들어간
main을 이 브랜치에 merge했다. 범위 검사와 정규화 구현은 유지하고 C의 env 정책을 추가로
적용한다. 일반 DB URL을 `DATABASE_URL`로 추출하는 후보는 구조상 scope 검사를 통과해도
C가 관리하는 바인딩이므로 보류한다. 자체 샘플의 승인된 SQLite → Postgres 템플릿 변환은
기존 backing_services 계약을 사용한다. scope 허용 여부가 env 정책의 승인을 대신하지 않는다.

| 항목 | C 규칙 | B의 처리 |
| --- | --- | --- |
| PORT | 명세 port에서 주입 | spec.port=8080. 앱은 PORT를 읽지만 env 목록에는 넣지 않는다. |
| 외부 자원 주소 | C가 연결 주소를 바인딩 | DATABASE_URL/STORAGE_URL/REDIS_URL은 일반 앱 env 이름으로 허용하지 않는다. 샘플의 SQLite 변환은 postgres → DATABASE_URL 바인딩을 사용한다. |
| object_storage | MVP 미지원 | backing_services에 출력하지 않는다. 저장 방식 변경은 보류한다. |
| 예약 이름 | COMPOSE_, TRAEFIK_, LD_, POSTGRES 접두사, PATH/HOME 등 | 기존 AWS_/DOCKER_/LAMBDA_ 및 프로세스 예약 이름과 합쳐 차단한다. 추출할 이름이 예약어면 이름을 바꾸지 않고 항목을 보류한다. |
| 일반 env 값 | 최대 1024자, 줄바꿈/작은따옴표 금지 | Pydantic/JSON Schema 검사. 위반 값은 명세에 넣지 않고 원문 없는 경고를 남긴다. 기존 NUL·자격 증명 URI·전체 UTF-8 4KB 검사도 유지한다. |
| migrate 문자열 | 한 줄, 500자 이하 | 문자열 검증 실패는 명세에서 제외하고 보류 경고를 남긴다. 문자열 검증은 임의 셸 명령의 실행 허가가 아니다. |
| aws-always-on / onprem tfvars | 앱별 tfvars 없음 | recommendation.tfvars={}. 근거에 “C: 앱별 tfvars 없음”을 기록하고 tfvars_schema 확인 항목을 제거한다. 앱별 override는 적용하지 않는다. |
| aws-serverless tfvars | C Lambda 세트 미정의 | 기존 임시 port/memory_mb/timeout_s를 유지하며 “C Lambda 세트 미정의”라고 표시한다. 실제 적용 전 확인이 필요하다. |
| aws-always-on 비용 | 환경 공용 기반 | t3.small 호스트 + RDS db.t4g.micro 20GB + 루트 볼륨 30GB + 탄력적 IP를 여러 앱이 공유한다. 앱별 비용으로 표시하지 않는다. 단가 미확정으로 총액은 null이며 새 단가를 추측하지 않는다. |
| 컨테이너 실행 조건 | 메모리 512MB·CPU 1·읽기 전용·/tmp | gate/security.py의 기존 --memory 512m, --cpus 1, --read-only, /tmp tmpfs를 그대로 유지한다. C가 제시한 자원·파일 시스템 조건과 대응한다. |
| migrate 순서 | 앱 시작 → compose run --rm web sh -c migrate → healthcheck | app_start → 같은 앱 이미지·환경변수·네트워크의 별도 일회성 migrate 컨테이너 → healthcheck → CRUD·재기동 후 조회. 시작한 앱 컨테이너에 exec하지 않는다. |

## 게이트 보안·검증 범위

read-only, /tmp의 noexec/nosuid, nonroot, cap-drop=ALL, no-new-privileges,
PID 제한, internal network와 환경 allowlist를 유지한다. 보안 조건 전체가 C와 동일하다는
주장이 아니라, C가 답한 메모리·CPU·읽기 전용·/tmp 조건과의 대응이다.
게이트의 `docker run`/wait/정리는 C의 `docker compose run --rm web`과 같은 일회성 실행 방식을
검증한다. 앱 이미지의 컨테이너 안에서 고정 명령 `sh -c 'python -m app.migrate'`만 실행하며,
일회성 컨테이너에도 기존 보안 플래그와 env allowlist를 적용하고 성공·실패 모두 정리한다.
명세의 임의 명령이나 호스트 셸을 실행하지 않는다. 실제 Compose·SSH·RDS 실행 검증은 아니다.

C #41의 시크릿 계약은 생성된 비밀과 AWS 앱 DB 비밀번호를 호스트의 기존 설정에서 재사용하는
방식이다. 앱 비밀의 원본은 현재 권한 600의 `app.env`이며, Secrets Manager에는 RDS 관리자
비밀번호만 있다. 사용자가 입력한 비밀은 재배포마다 전달해야 하고 호스트 교체 시 생성 비밀의
유지는 미지원이다. 이미지는 서비스 서버에서 `docker save` → SSH → `docker load`로 전달한다.

게이트는 해시로 식별한 todo/todo-scheduler의 임시 복사본에서만 실행한다.
스키마 생성은 빈 DB용이며 기존 데이터 이전은 미지원이다. 샘플 성공은 사용자 앱의 DB
변경 승인이 아니며 pr_eligible=false를 유지한다. 주기 작업의 타이밍·중복 실행과 실제
AWS/온프레미스 배포는 게이트의 검증 범위가 아니다.

## 재현

팀 저장소의 AI 디렉터리에서 기본 설치/pytest를 준비한 뒤 실행한다.

```sh
python -m ai analyze samples/todo --llm none --gate docker --out out/c-contract-todo
python -m ai analyze samples/todo-scheduler --env onprem --llm none --gate docker --out out/c-contract-scheduler
```

LLM 없이 C 계약과 실제 Docker 순서를 확인하는 명령이며 새 유료 모델 호출은 없다.
기존 골든 JSON과 데모 캐시는 재생성하지 않는다. scheduler의 기존 골든에서 tfvars 및
needs_confirmation 두 필드는 C 답변으로 바뀌므로 테스트에서 새 계약을 명시적으로
비교하고 나머지 골든 필드는 그대로 비교한다.

## 남은 C 확인

- Lambda 세트의 실제 정의와 변수/실행 범위.
- 공용 기반 자원의 리전별 확정 단가와 앱별 비용 배분 정책(배분을 구현하지 않음).
- 실제 app 예약 이름과 최종 시크릿/URL 주입 후 값·전체 크기 검사. C #41의 시크릿 재사용·호스트 교체 한계와 사용자 비밀 재전달은 A 연결 시 확인한다.
- 최종 이미지 아키텍처와 태그/digest 전달·검증 이미지와의 관계.
