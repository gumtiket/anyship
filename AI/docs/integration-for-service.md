# 서비스(A)와 AI 모듈 연결 — P6

B는 CLI와 `run_analysis` 함수만 제공한다. 입력은 권한 확인 후 A가 준비한 로컬 레포 경로다. GitHub 토큰·클라우드 자격 증명·서비스 DB 연결을 B에 전달하지 않는다. B의 HTTP 서버는 없다. 팀의 AIProvider Protocol에 연결하는 A 측 코드는 아직 별도 작업이다.

## CLI 연결

`ai/`와 `samples/`가 있는 디렉터리에서 실행한다. 팀 저장소에서는 `AI/`다. `subprocess`의 인자 리스트로 호출하고 shell 명령 문자열에 사용자 입력을 넣지 않는다. stdout은 진행 로그, out은 구조화된 결과다.

```sh
ai/.venv/bin/python -m ai analyze samples/todo --llm replay \
  --no-gate --out out/service-example/
```

종료 코드 0은 보고서 생성 완료다. 1은 미지원/변경안/진단 보강/게이트 실패, 2는 입력·출력·fixture/hash 오류다. 0이라도 partial 변환·skipped 게이트·승인 필요를 숨기지 않는다. 실패로 중단된 호출에서 이전 out을 현재 결과로 읽지 않도록 요청별 출력 경로를 사용한다.

## 함수 연결

```python
from ai import run_analysis
from ai.llm.recording import ReplayClient

client = ReplayClient("samples/todo")
result = run_analysis(
    "samples/todo", target_env="aws", out_dir="out/service-example",
    llm=client, decision_llm=client,
    log=lambda stage, message: print(stage.value, message),
)
try:
    client.assert_consumed()
    payload = result.model_dump(mode="json")
finally:
    if result.build_context is not None:
        result.build_context.cleanup()
```

실제 호출은 BedrockClient를 명시한다. `llm`/`decision_llm`/`repair_llm`은 진단/추천/복구용이다. 아티팩트 모델 호출은 `artifact_llm`으로 별도 선택한다. 로그 콜백은 `log(Stage, str)`이며 SSE에는 `stage.value`와 문자열 메시지를 전달한다. 함수 호출자는 BuildContext를 정리한다. 일부 실패는 보고서 상태로 반환하지만 입력/fixture 오류는 예외로 반환하므로 A가 실패 UI로 처리한다.

## 데모 표시와 비용

`use_demo_cache=True` 또는 `--use-demo-cache`는 명시적인 사전 결과 재생이다. 캐시가 없거나 코드·구현·설정·아티팩트 해시가 다르면 로그로 알리고 정상 분석한다. 실제 분석 실패를 자동으로 성공 캐시로 숨기지 않는다.

- 모든 캐시 로그에 `(사전 실행 결과)`가 붙는다. 화면에서도 이 표시를 유지한다.
- `AnalysisResult.execution_source=demo_cache`, `gate-report.execution_source=demo_cache`, 현재 gate.status=skipped다. `historical_status=passed`는 이전 실제 샘플 검증 결과다.
- 캐시 cost는 `historical=true`, `external_calls=0`이다. total/stages/calls는 **과거 실행 사용량**이므로 현재 과금/분석 시간으로 표시하지 않는다. `cache-provenance.json`에 이전 시간·해시가 있다.
- `--llm replay`는 분석 로직을 현재 실행하며 저장된 LLM 응답만 재생한다. 새 AWS 호출·토큰·비용은 0이고 source=llm_replay다. calls는 로컬 재생 횟수다.
- 현재 `pr_eligible=false`다. 캐시/replay/skipped를 실제 사용자 앱의 검증 또는 승인으로 바꾸지 않는다.

## Postgres 드라이버 계약 (B 선택)

SQLite 변환안은 psycopg2 드라이버를 사용한다. 설치 패키지는 `psycopg2-binary`이며,
기존에 psycopg2 또는 psycopg2-binary가 선언되어 있으면 중복 추가하지 않는다.
C는 `DATABASE_URL=postgresql://...`을 주입하고, 변환된 앱이 내부에서
`postgresql+psycopg2://...`로 바꿔 SQLAlchemy의 드라이버 선택을 명시한다.
명세에 드라이버 필드를 추가하지 않는다. 기존 psycopg3 의존성은 임의로 삭제하지 않는다.

게이트도 같은 일반 URL을 주입하여 자체 샘플의 임시 Postgres 초기화·CRUD·재시작 후
읽기를 확인한다. 실제 사용자 앱은 변경안만 생성하며 DB 변경은 risky/승인 필요다.
기존 SQLite 데이터는 자동으로 이전되지 않는다. 어댑터의 마이그레이션 실행은 이미지
컨테이너 내부·앱 DB 계정·시간 제한 조건을 C가 강제해야 한다. 샘플 검증의 DB 계정은
임시 검증용이므로 이 운영 권한 조건까지 검증한 것으로 해석하지 않는다.

## 확정 필요

| 계약 | 현재 값/경계 | 확정할 담당 |
| --- | --- | --- |
| 단계 enum/SSE | stages.py의 임시 7개 값 | A와 B |
| AIProvider 입력/항목 선택 | A의 SHA/코드 자료와 B의 로컬 경로/전체 diff 사이 매핑 필요 | A와 B |
| 배포 명세 스키마 | B의 pydantic/JSON Schema, 운영 호환성 공동 확정 전 | A/B/C |
| tfvars 이름·범위 | tfvars_schema.py의 임시 alias/validation, needs_confirmation 유지 | C |
| 인프라·Bedrock 단가 | cost_table.py는 임시 가정, pricing.json 미확정은 null | C/B |
| 게이트 실행 환경 | 자체 샘플만, POSIX Docker 러너, 내부 네트워크·자원 제한 | A/C |
| 캐시/replay 표시 | 위 execution_source/historical_status/비용 의미를 UI에 표시 | A와 B |

DB·영속 파일 변경은 risky/승인 필요이며 기존 데이터는 자동 이전하지 않는다. 일반 앱은 proposal-only이고 컨테이너 검증 skipped다. source.repo/commit과 실제 배포 이미지 주소는 A가 명시하며 원본 레포 내부/상위 경로를 out으로 사용하지 않는다.


## 검토 후 요청 격리·입력 계약

A는 작업마다 새 out과 새 LLM 클라이언트를 만든다. 같은 클라이언트를 동시에 쓰면 llm_client_in_use로 거부한다.
비어 있지 않은 out은 output_not_empty로 거부하고, 결과는 임시 폴더에서 완성한 뒤 전체 디렉터리를 게시한다.
실패한 요청의 이전 out을 읽지 말고 예외/반환 결과의 현재 상태를 기준으로 처리한다.
성공 함수 결과의 BuildContext는 A가 cleanup한다. 예외로 반환되지 않은 컨텍스트는 B가 정리한다.

app_name/--app-name과 source_repo/--source-repo를 A가 전달한다. max_request_seconds/--max-request-seconds는
명시한 후보 시간이며 실측값이 아니다. 후보 또는 LLM 설명을 실제 실행 보장으로 표시하지 않는다.
LLM의 spec 제안은 세트·시간·ingress를 변경하지 못한다.

changes.diff에 .dockerignore가 포함된다. 일곱 결과 파일만 옮기면서 이 변경을 버리면 안 된다.
보조 .dockerignore도 일반 분석과 캐시 복원에서 제공하며 기존 패턴을 보존해 빌드 컨텍스트에 적용한다.
pyproject 등 미지원 패키징은 명세 없음/partial과 dependency_packaging 확인 필요로 표시한다.
기존 외부 DB·사용자 시크릿은 주소/값 입력을 받아야 하며 B의 generate로 임의 생성하지 않는다.

4KB는 B의 알려진 값 검사만으로 확정하지 않는다. C가 URL·비밀·시스템 변수를 주입한 최종 합계를 검사한다.
env_policy/app_reserved_names 확인 필요 표시, 30초 경계/timeout_s 1~30, 예약어와 실제 범위는 C와 확인한다.

새 캐시는 기존 실제 응답을 동일 해시로 재생하고 새 Docker 검증으로 만들 수도 있다. 이 경우
cache-provenance.llm_execution_source=llm_replay와 recorded_llm_usage를 표시한다.
새 AWS 호출은 0이고 cache cost의 토큰은 원래 Bedrock 사용량이 아니다. 원래 토큰/미확정 비용은
recorded_llm_usage에 별도로 있으며 null을 0으로 바꾸지 않는다. 현재 gate=skipped/과거 passed는 그대로 유지한다.
