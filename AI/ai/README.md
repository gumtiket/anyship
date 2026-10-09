# Bronze AI — P6

실행 기준은 `ai/`와 `samples/`가 나란히 있는 프로젝트 루트다. 팀 저장소에서는 `cd AI` 후 실행한다.

## 설치와 PyCharm

Python 3.12를 사용한다. 기존 프로젝트 밖의 가상환경을 실행 의존성으로 쓰지 않는다.

```sh
python3.12 -m venv ai/.venv
ai/.venv/bin/python -m pip install -e 'ai[dev]' -c ai/requirements-dev.lock
```

PyCharm은 Existing environment에서 현재 프로젝트의 `ai/.venv/bin/python`을 고른다. Run Configuration은 module `ai`, parameters `analyze samples/todo --llm replay --out out/todo/`, working directory는 ai와 samples가 있는 디렉터리다.

| 환경변수 | 의미 |
| --- | --- |
| AWS_PROFILE | 개발자의 로컬 프로필. 서버에서는 IAM 역할 사용 가능 |
| AWS_DEFAULT_REGION | 프로필/인증 갱신 리전 |
| BEDROCK_REGION | 실제 Bedrock 호출 리전 |
| BEDROCK_MODEL_ID_STRONG | 계정에서 확인한 코드 생성/복구 모델 ID |
| BEDROCK_MODEL_ID_FAST | 계정에서 확인한 설명/근거 모델 ID |

기본 none, fake, replay, 데모 캐시 hit는 AWS 자격 증명 없이 실행된다. 실제 bedrock/record만 위 설정을 요구한다. 모델 버전 비교는 [Claude 전달 프롬프트](deliverables/model-selection-prompt.md)로 별도 판단한다.

## 출력과 상태

DB 변환안은 `psycopg2`로 통일한다. 설치 패키지는 `psycopg2-binary`다.
어댑터는 `postgresql://` 주소를 주입하고 변환된 앱이 `postgresql+psycopg2://`로
드라이버를 명시한다. 실행 검증은 자체 샘플의 임시 복사본과 임시 Postgres에 한정한다.
실제 사용자 앱은 risky 변경안만 제공하며 기존 데이터 자동 이전은 지원하지 않는다.

```text
out/
  diagnosis.json
  changes.diff
  Dockerfile
  deploy-spec.yaml
  recommendation.json
  gate-report.json
  cost.json
```

진단은 원본 기준이며 변경안 반영 여부는 `transformation.addressed_ids/deferred_ids`로 구분한다. 자체 샘플의 위반 6개 중 4개를 제안에 반영하고 (수정 파일 5개에는 .dockerignore가 포함됨), 파일 저장 전환과 미확인 의존성 버전 고정은 보류한다. `partial`을 전체 준수로 표시하지 않는다.

`--save-llm-trace`는 `llm-trace.md/json`, `llm-comparison.json`을 추가한다. 마스킹한 프롬프트·응답·파싱·실제 모델·토큰·규칙 차이를 읽을 수 있다. 모든 시크릿 패턴을 탐지하는 보장은 없다. 트레이스/실행 결과는 Git에 넣지 않는다.

`cost.json`은 실제 LLM 요청의 호출/단계별 토큰과 비용을 기록한다. `pricing.json`의 `models`는 비어 있으며 단가 미확정 호출 비용은 null이다. `recommendation.estimated_monthly_cost`는 이와 별개인 임시 인프라 비용이다. `spec/cost_table.py`의 숫자는 실제 AWS 요금/청구 견적이 아니다.

## 함수 호출

```python
from ai import run_analysis
from ai.llm import FakeLLMClient
from ai.llm.fake import recommendation_response

client = FakeLLMClient(
    {
        "diagnose": ['{"explanations":[],"candidates":[]}'],
        "recommend": [recommendation_response],
    }
)
result = run_analysis(
    "samples/todo",
    out_dir="out/todo",
    llm=client,
    decision_llm=client,
    log=lambda stage, message: print(stage.value, message),
)
try:
    payload = result.model_dump(mode="json")
finally:
    if result.build_context is not None:
        result.build_context.cleanup()
```

`llm`은 진단/초기 변경안, `decision_llm`은 추천 설명, `repair_llm`은 게이트 실패 수정용이며 각각 기본 None이다. CLI의 `--llm`은 이 셋에 같은 클라이언트를 전달한다. `artifact_llm`은 Dockerfile/명세 제안용으로 별도 선택한다. 기본 템플릿으로 패키징할 수 있어 `--artifact-llm bedrock`은 추가 유료 호출이다.

`runner=FakeRunner()`는 순서 검사, `runner=DockerCliRunner()`는 자체 샘플 실제 검증이다. 함수 호출자는 반환 BuildContext를 사용 후 정리한다. CLI는 자동 정리한다. 입력과 출력 경로를 분리하고 원본/원본 상위 경로를 출력으로 지정하지 않는다.

## Bedrock 선택 실행

AWS 인증은 각 개발자의 프로필/SSO 또는 실행 서버의 IAM 역할로 제공한다. 비밀키를 코드·명세·로그에 넣지 않는다. 모델은 계정과 리전의 목록에서 확인하고 성공한 ID를 환경변수로 설정한다.

```sh
export AWS_PROFILE=your-local-profile
export AWS_DEFAULT_REGION=ap-northeast-2
export BEDROCK_REGION=ap-northeast-2
ai/.venv/bin/python ai/scripts/bedrock_check.py --list-only

# 실제 계정에서 확인한 모델 ID를 입력한다. 실제 추론 요금 발생.
export BEDROCK_MODEL_ID_STRONG=your-verified-strong-model-id
export BEDROCK_MODEL_ID_FAST=your-verified-fast-model-id
ai/.venv/bin/python -m ai analyze samples/todo --llm bedrock \
  --save-llm-trace --out out/bedrock-todo/
```

Converse를 사용한다. 지원 모델은 temperature=0이며 Sonnet 5.5/Haiku 5.5는 비기본 sampling 옵션을 생략한다. 모델 출력의 완전한 재현성을 주장하지 않는다. JSON 최초 요청+재생성 최대 2회, SDK 전송은 요청당 최대 3회이며 usage를 기록한다. 계정/Marketplace/최초 사용 접근 문제가 있으면 안전하게 분류하고 실제 AI 성공으로 숨기지 않는다.

## Docker 선택 실행

```sh
docker pull postgres:16-alpine
docker pull curlimages/curl:8.12.1
ai/.venv/bin/python -m ai analyze samples/todo --llm fake --gate docker --out out/docker-todo/
ai/.venv/bin/python -m pytest -m docker ai/tests/test_gate.py ai/tests/test_recommend_retry.py -v
```

해시로 확인한 두 자체 샘플의 임시 변환본만 실행한다. Linux 이미지, nonroot/read-only/tmpfs, internal network, cap-drop/no-new-privileges, CPU/메모리/PID 제한을 적용한다. 부모 시크릿/실제 DB와 Docker socket을 컨테이너에 전달하지 않는다. 마이그레이션 명령은 빈 DB용 `python -m app.migrate`로 제한하며 기존 스키마 업그레이드나 데이터 복사를 하지 않는다.

Dockerfile은 Python 3.12-slim, LWA 1.1.0, PORT=8080, readiness `/healthz`를 사용한다. 이미지 내용에 SHA/시각/랜덤 값을 넣지 않는다. 외부 태그와 `source.commit`은 추적 메타데이터다. 동일 이미지 재사용과 재빌드 동일성을 구분하며 대상 플랫폼은 C가 확정하고 재검증해야 한다. 러너는 현재 macOS/Linux POSIX 잠금을 사용한다.

게이트는 최초 포함 최대 3회 실행한다. 기존 Python 파일/고정 Dockerfile 템플릿 안의 수정만 허용하며 공개 API·데이터 모델·환경변수 계약·보안 조건의 변경은 거부한다. 의존성 파일을 임의로 바꾸는 복구는 지원하지 않는다. 수정안은 apply 검사/컴파일 뒤 재검증하고 시도별 원인·수정 요약·중단 사유를 GateReport에 남긴다. 보안 제약은 [체크리스트](../docs/gate-security-checklist.md)를 따른다.

검증용 컨테이너·네트워크·임시 이미지/볼륨은 자신의 실행 범위에서 정리한다. 공용 helper 이미지와 빌드 캐시는 유지하고 Docker 전체 prune는 하지 않는다.

## 추천과 임시 인프라 계약

선택 순서는 onprem 대상 → scheduler → websocket → 긴 요청 신호 또는 명시된 요청 시간 후보가 30초 초과 → 짧은 요청이다. 각각 onprem / aws-always-on / aws-always-on / aws-always-on / aws-serverless다. 30초는 팀 MVP 계약이며 AWS 플랫폼 자체 제한이 아니다. 기준과 tfvars 범위는 tfvars_schema.py에 모아 두었다. 최대 요청 시간 기본 후보 10초는 실측값이 아니다.

FAST는 근거 문장만 작성한다. 다른 세트를 주장하면 재생성 후 규칙 템플릿으로 대체한다. 설명의 모든 사실 오류를 자동 검증하는 기능은 없다. C 확인 전 변수명/범위/default는 `src/ai/spec/tfvars_schema.py`, 단가/가정은 `src/ai/spec/cost_table.py` 한 곳에서 관리한다. Lambda와 EC2 Compose 변수 모델을 나누고 범위 오류는 클램프 없이 경고+기본값 대체다.

`--image-tag`/함수 `image_reference`가 없으면 이미지 값을 생략한다. A가 실제 이미지 주소/태그/digest를 확정해야 한다. `--tfvars-json`은 선택 세트의 변수 객체를 읽는다. `--no-gate`는 게이트 생략, `--no-compare`는 원본 복사본 비교 생략이며 일반 앱의 실행을 허용하지 않는다.

`needs_confirmation=["tfvars_schema", "cost_table"]`과 **임시 추정치**를 화면에 표시한다. 리전·요청 수·가동 시간·평균 실행 시간·스토리지·프리티어 제외·누락 비용은 assumptions에 있으며 실제 적용 전 [C 체크리스트](../docs/p5-infra-confirmation-checklist.md)를 확인한다. DB/파일 변경 승인과 `data_migration_unsupported` 경고를 함께 표시한다.

## 검증과 남은 작업

로컬 P5 기준 기본 테스트 195 passed / 외부 연동 5 skipped, 실제 Docker 선택 테스트 3 passed다. 실제 FAST Haiku 4.5 + Docker는 todo=aws-serverless / todo-scheduler=aws-always-on으로 끝까지 검증했다. 이 수치는 P5 당시 결과다. 최신 수정 후 기본 테스트는 280 passed / 외부 연동 5 skipped다. 실제 STRONG 로그 변환 한 사례도 검증했으며 복잡한 복구 품질은 추가 확인 대상이다. 복구 루프는 Fake 수정안+실제 Docker로 검증했다. 검토한 샘플 캐시/fixture 이외의 개인 이력은 포함하지 않으며 새 환경에서 위 명령으로 재현한다.

P6의 두 샘플 골든 회귀와 사전 실행 캐시를 구현했다. C 계약 확정과 A의 권한 확인된 코드 자료 제공·AIProvider 연결은 남아 있다. 게이트 통과는 샘플 기동/CRUD 범위의 증거이며 전체 기능·PR 승인·클라우드 배포 준비 완료를 뜻하지 않는다.

## P6 기록·재생·골든

```sh
# 기록된 실제 응답을 사용한다. 현재 AWS 호출/토큰/비용은 0이다.
ai/.venv/bin/python -m ai analyze samples/todo --llm replay --gate fake --out out/replay-todo/
ai/.venv/bin/python -m ai analyze samples/todo-scheduler --llm replay --no-gate --out out/replay-scheduler/

# 유료 실제 Bedrock 응답을 재기록한다. 먼저 모델/프로필 환경변수를 설정한다.
ai/.venv/bin/python -m ai analyze samples/todo --llm record --no-gate --out out/record-todo/

# 기존 골든과 비교한다. 차이가 있으면 검토용 out을 남기고 종료 코드 1이다.
ai/.venv/bin/python ai/scripts/refresh_golden.py
# 의도한 프롬프트/스키마 변경 후 실제 재기록. 유료 호출이며 기준은 자동 덮어쓰지 않는다.
ai/.venv/bin/python ai/scripts/refresh_golden.py --record
# 스크립트가 출력한 새 golden-refresh 디렉터리의 diff/명세를 검토한 뒤 기준을 갱신한다.
ai/.venv/bin/python ai/scripts/refresh_golden.py --accept
```

fixture는 `ai/tests/fixtures/llm/<sample>/<stage>.json`에 있다. 실제 전송 system/schema/user/추론 옵션의 해시와 마스킹한 원문 응답·사용량·모델·응답 해시를 저장한다. 프롬프트 원문·인증 정보·SDK 오류·HTTP 헤더는 저장하지 않는다. 두 자체 샘플만 기록/재생하며, 프롬프트/스키마/입력/옵션이 달라지면 `prompt_hash_mismatch`로 즉시 실패한다. 응답 변조/누락/미사용 기록도 명확한 에러다. 일반 LLM 템플릿 fallback으로 이 오류를 숨기지 않는다.

record/replay CLI의 패키징은 고정 템플릿이며 artifact-llm은 none이다. 함수에서 RecordingClient/ReplayClient를 직접 사용할 수도 있다. replay의 새 전송 수·토큰·비용은 0이고, `cost.calls`는 로컬 재생 횟수다. 원래 사용량은 fixture의 response에 보존한다. 실제 Docker 검증은 별도 --gate docker 선택이며 replay 자체는 런타임 검증 성공을 뜻하지 않는다.

골든은 위반 집합·12-factor 담당 표·신호·추천 세트·명세 핵심 필드·변수·변경안 적용/컴파일·Dockerfile lint/바이트 동일성을 고정한다. 두 샘플의 기록 기반 회귀이며 독립 holdout이나 임의 앱/모델 정확성·재빌드 이미지 동일성 검증이 아니다.

## P6 데모 캐시

```sh
# 사전 결과 표시. hit는 현재 Bedrock/Docker 호출 없이 로그만 순서대로 재생한다.
ai/.venv/bin/python -m ai analyze samples/todo --use-demo-cache --out out/cached-todo/
ai/.venv/bin/python -m ai analyze samples/todo-scheduler --use-demo-cache --out out/cached-scheduler/

# 실제 Bedrock + Docker로 두 캐시와 LLM fixture 재작성. 실제 추론 요금 발생.
ai/.venv/bin/python ai/scripts/build_demo_cache.py
```

캐시는 `ai/demo-cache/<sample>/out`의 7종과 manifest에 있다. source/engine/설정/각 파일 해시가 맞아야 사용한다. 대상 env, commit, 명시한 source.repo, profile, 이미지 식별자, tfvars/비용 가정, 원본 비교 여부도 확인한다. 캐시가 없거나 달라지면 정상 실행으로 돌아가고 로그로 알린다. 실제 분석 실패 후 몰래 캐시로 성공을 대신하지 않는다. source.repo 미제공의 데모 캐시는 sample:// 이름을 사용하며 실제 GitHub 저장소/commit으로 해석하지 않는다.

모든 재생 로그에 `(사전 실행 결과)`를 붙이고 짧고 제한된 지연만 적용한다. 과거 로그의 단계 시간/trace 언급은 과거 실행을 가리키며, 공유 캐시에 개인 trace 파일은 넣지 않는다. 응답은 LLM fixture에서 확인한다. 현재 결과는 execution_source=demo_cache, 현재 gate.status=skipped, historical_status=passed, pr_eligible=false다. 캐시 비용은 historical=true와 external_calls=0이며 total/calls/stages는 과거 사용량이다. 추가 cache-provenance.json에 이전 시간·해시를 기록한다. 캐시 hit에서는 새 BuildContext를 반환하지 않는다.

함수의 `run_analysis(..., use_demo_cache=True, demo_cache_dir=...)`도 같은 경계를 따른다. 일반 앱과 다른 코드에는 캐시를 적용하지 않는다. 출력은 원본과 분리하고 요청마다 새 경로를 사용한다.

## 단계와 테스트

Stage는 `src/ai/stages.py` 하나에서 정의한다: 분석 중, 검증 중, PR 대기, 빌드 중, 배포 중, 성공, 실패. 서비스와 공동 확정 전의 값이며 로그 문자열을 status 판정 대신 쓰지 않는다.

```sh
ai/.venv/bin/python -m pytest ai/tests -q
ai/.venv/bin/ruff check ai
ai/.venv/bin/ruff format --check ai
# 실제 외부 호출은 별도 선택한다.
ai/.venv/bin/python -m pytest -m bedrock ai/tests -v
ai/.venv/bin/python -m pytest -m docker ai/tests -v
```

기본은 Fake/기록 replay/캐시 검증으로 AWS·Docker 없이 통과해야 한다. 기본 실행은 외부 마커를 건너뛴다. fixture/cache의 자격 증명 패턴 검사는 인식한 패턴의 범위이며 모든 비밀을 자동 탐지한다는 보장은 없다. cache manifest와 해시는 손상/오사용 검출용이며 신뢰할 수 없는 사람이 제공한 파일의 진위를 인증하는 서명이 아니다.

[서비스 연결 문서](../docs/integration-for-service.md)와 [인수인계 체크리스트](../docs/handoff-checklist.md)를 따른다. C 계약/단가, 서비스 서버 Docker/플랫폼, 웹 AIProvider 연결, 실제 STRONG 복구 품질과 운영 데이터/롤백은 별도 확인이 남아 있다.

2026-10-09 P6 완료 검증: 기본 219 passed / 외부 연동 5 skipped, P6 추가 24 passed, ruff 통과. 실제 사전 실행은 두 샘플 모두 Docker/Postgres 범위 통과다. 캐시 저장 검사 수정 전의 성공 분석까지 포함한 실제 사용은 총 6회, 입력 12,317 / 출력 4,650토큰이며 비용 단가는 미확정이다. 캐시에는 최종 성공 실행만 포함하고 전체 사용 집계/개인 trace는 out에 별도 보존했다.


## 2026-10-09 독립 검토 후 수정

함수와 CLI의 out은 요청별 새 디렉터리여야 한다. 비어 있지 않은 out은 호출 전에 거부한다.
내부 임시 디렉터리에서 전체 결과를 완성한 뒤 한 번에 게시하며 예외 시 임시 컨텍스트도 정리한다.
CLI/함수의 `--app-name`/`app_name`, `--max-request-seconds`/`max_request_seconds`는 A 또는 사용자의 명시 입력이다.
LLM 제안으로 요청 시간·세트·ingress를 바꾸지 않는다. 기본 로컬 source는 개인 절대 경로 대신 `local://앱이름`이다.
A는 실제 GitHub 주소와 커밋을 source_repo/commit으로 전달한다. 이름의 예약어·최종 식별자 충돌은 A/C 확인이 필요하다.

환경변수는 일반 값/템플릿에서 추출한 생성 대상 SECRET_KEY/사용자 제공 비밀로 구분한다.
PORT·프로세스 제어·AWS/DOCKER/Lambda 변수, 중복 이름, 줄바꿈·NUL·알려진 자격 증명 URL 값을 검증한다.
B는 알려진 UTF-8 key/value 크기를 검증하고 C는 DB URL·시크릿·시스템 주입 후 전체를 다시 검증한다.
DATABASE_URL은 임의 생성하지 않으며 기존 외부 DB 종류/자원을 추측하지 않는다.
`needs_confirmation`에 env_policy/app_reserved_names와 필요한 사용자 입력 항목을 함께 표시한다.

직접 sqlite3/aiosqlite 연결, 함수 인자/Authorization/URL/JSON 비밀을 검사한다.
FastAPI의 Starlette 보조 import와 독립 Starlette 앱을 구분한다. 누락·빈 의존성 선언을 진단하고,
루트 requirements.txt가 없는 형식/민감한 패키징 입력은 명세 생성을 보류한다.
`ok`는 현 규칙에서 위반을 찾지 못했다는 뜻이며 전체 준수를 보장하지 않는다.

`.dockerignore`는 파일 7종을 늘리지 않고 changes.diff에 포함한다. 일반 출력과 캐시 복원에도 보조 파일로 제공한다.
A는 diff의 이 변경을 포함해 PR/빌드 컨텍스트를 구성한다. 기존 ignore 패턴은 보존하며 안전 제외를 마지막에 추가한다.
MVP ingress는 public, object_storage는 명세에서 거부, profile은 메타데이터이며 C가 무시하는 계약을 확인한다.

기본 데모 캐시는 최신 실제 FAST Bedrock 호출과 Docker 검증 결과다. 상세 사용량과 STRONG 검증 범위는 수정 요약에 기록한다.

### 기존 실제 응답으로 캐시 검증

```sh
# 동일 요청 해시의 기존 Bedrock 응답 + 지금 실행하는 Docker/Postgres 검증. 새 AWS 호출은 없음.
ai/.venv/bin/python ai/scripts/build_demo_cache.py --llm replay
```

자동으로 실패한 실제 분석을 재생으로 바꾸지 않는다. 위 모드는 개발자가 명시적으로 고른다.
캐시 provenance의 llm_execution_source=llm_replay와 recorded_llm_usage를 표시한다.
이 replay 모드로 생성한 cache cost는 과거의 재생 실행 사용량(새 AWS 토큰/비용 0)이고, recorded_llm_usage는 별도의 원래 Bedrock 과거 사용량이다.
그 원래 비용 null을 0원으로 바꾸지 않는다. 캐시 복원 시 현재 gate는 skipped이고 과거 Docker passed만 표시한다.

검토 결함/증거와 남은 계약은 [수정 요약](../docs/review-fix-summary.md),
A/C의 실행 조건은 [배포 명세 계약](deliverables/deploy-spec-contract.md)을 참고한다.

### 서비스에 결과 전달하기 (A와 합의 전의 예제)

`scripts/service_handoff.py`는 새 분석 결과를 JSON으로 전달하고 안전·비용·캐시 정보를 보존한다.
기본 Fake, 컨테이너 미실행이며 선택 항목별 수정·웹 제공자·PR·배포는 연결하지 않는다.
개인 출력 경로/BuildContext/원시 컨테이너 로그는 전달 JSON에서 제외하고 컨텍스트를 정리한다.
실행 방법과 코드/SHA·항목 선택·결과 계약 및 서버 Bedrock 설정은
[서비스 연결 다음 단계](../docs/service-connection-next.md)를 참고한다.
