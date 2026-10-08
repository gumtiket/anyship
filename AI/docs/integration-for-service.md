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
