# 배포 명세 계약 — 검토 후 수정

이 문서는 B가 생성하는 명세의 현재 검증과 A/C 책임을 구분한다.
MVP/설계 원문에 없는 예약어·tfvars·가격은 임의로 확정하지 않는다.

## 필드와 실행 경계

| 항목 | B의 현재 규칙 | A/C 책임 |
| --- | --- | --- |
| app | 3~31자 소문자 DNS 라벨. 명시 app_name 우선, 없으면 폴더명을 정규화 | 예약어 공유, 짧은 식별자·충돌 처리, 최종 이름 63자 이내 |
| source | source_repo/commit은 추적 정보. 기본 local URI에 개인 절대 경로를 넣지 않음 | GitHub 주소/원본 SHA 전달, 머지 후 실제 배포 이미지 확정 |
| build/port/healthcheck | Python 3.12 템플릿, PORT 8080, /healthz | 검증한 이미지와 실제 이미지의 관계, 대상 아키텍처 확인 |
| ingress/profile | public만 허용. profile은 dev/prod 메타데이터 | profile을 실행 정책으로 사용하지 않는 MVP 계약 확인 |
| env | 아래 모델/JSON Schema·의미 검증 | 동일 거부 목록, 최종 값·시크릿 주입과 전체 크기 검증 |
| backing_services | SQLite 변환안의 postgres만 생성, 기존 DB는 추측해 생성하지 않음 | 실제 DB 생성/주소 주입. object_storage는 MVP에서 거부 |
| workload | 규칙/명시 max_request_seconds만 사용. LLM 제안은 판정을 변경하지 않음 | 30초 경계, 사용자 후보 시간과 실제 운영 제한의 관계 확인 |
| release.migrate | 자체 샘플은 python -m app.migrate. 일반 앱 실행은 하지 않음 | 컨테이너 내부·앱 DB 계정·시간 제한. 호스트 셸 실행 금지 |

source.commit은 참고용이다. 실제 배포 대상은 A가 확정해 전달하는 이미지 식별자다.
동일 이미지를 재사용하는 것과 새로 빌드한 결과가 동일한 것은 다르다.
B의 자체 샘플 게이트가 머지 후 이미지의 검증을 대신하지 않는다.

## env 의미

| secret | generate | 의미 |
| --- | --- | --- |
| false | false | 일반 설정. value 필수이며 빈 문자열은 허용 |
| true | true | 템플릿에서 확인한 생성 대상 SECRET_KEY. C가 처음 한 번 생성하고 재사용 |
| true | false | 사용자 제공 비밀. value를 명세에 넣지 않고 C의 별도 secrets 인자로 전달 |

B는 API 키·기존 SECRET_KEY·DATABASE_URL·REDIS_URL을 자동 생성 대상으로 추측하지 않는다.
SQLite 변환안에는 postgres/DATABASE_URL 바인딩을 만들고 env 목록에는 같은 바인딩을 중복하지 않는다.
기존 DATABASE_URL은 사용자 제공 비밀로 분류하고 external_resource_required 확인을 남긴다.
변환된 앱의 드라이버는 psycopg2/설치 psycopg2-binary이고, C의 postgresql://을 앱에서
postgresql+psycopg2://로 명시한다. 기존 데이터 복사는 지원하지 않는다.

PORT, PATH/LD_PRELOAD 등 프로세스 제어 이름, AWS_/DOCKER_/LAMBDA_ 접두사와 Lambda 예약 이름을 거부한다.
목록과 조건은 src/ai/spec/env_policy.py에 있으며 **확인 필요(C 확정 전)**이다.
값의 CR/LF/NUL, 알려진 자격 증명 URL, 중복 env 이름/자원 바인딩을 검사한다.
Pydantic은 알려진 UTF-8 key/value 합계와 PORT를 포함한 4096바이트 상한을 검사한다.
JSON Schema는 구조/조건 검증에 쓰고, 바이트 합계와 자격 증명 의미 검증은 모델도 거쳐야 한다.
C는 생성/사용자 비밀·DB URL·추가 시스템 변수까지 주입한 **최종 전체 값**을 다시 검사해야 한다.
비밀의 내부 모델 값 null은 내용 없음이며 생성 YAML에는 value 자체를 생략한다.

값이 없거나 충돌하는 일반 설정·금지 이름·안전하지 않은 기본값은 원문 없이 경고와 확인 필요를 남긴다.
B의 검사 범위 밖 비밀 패턴까지 모두 마스킹한다는 보장은 없다.

## 패키징·출력·판정

출력의 기본 7종 계약은 유지한다. .dockerignore는 changes.diff에 포함하고 보조 파일로도 제공한다.
A는 이 변경을 누락하지 않고 원본·변경안을 합친 빌드 컨텍스트에 적용한다.
개인 .env/인증 디렉터리/DB/키와 원본 Dockerfile의 취급을 명시적으로 확인한다.
루트 requirements.txt가 없거나 민감한 패키징 입력이 있으면 Dockerfile/명세 생성을 보류한다.
pyproject의 정상 의존성 선언을 Factor II 위반으로 오인하지 않는다.

추천/복구 루프는 구현되어 있다. onprem → scheduler → websocket → 긴 요청 신호 →
명시 후보 30초 초과 → 짧은 요청 순서로 판정한다. timeout_s의 MVP 범위는 1~30이다.
후보 시간은 실측 또는 실행 보장이 아니며 C의 최종 변수명/범위와 비용은 확인 필요다.

기본 입력은 새 출력 디렉터리·요청별 LLM 클라이언트다. 같은 클라이언트의 동시 분석은 거부한다.
일반 앱은 proposal-only, 컨테이너 gate=skipped, DB/영속 파일 변경은 risky/사용자 승인 필요다.
실행 성공/샘플 CRUD를 전체 기능·운영 권한·PR 자동 승인 준비로 표시하지 않는다.
