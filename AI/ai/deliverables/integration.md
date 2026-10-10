# A가 현재 AI 파트에 연결하는 방법 (P6)

## 시연 엔진 출력 변경 — 2026-10-10

`diagnosis.violations`는 규칙으로 찾은 위반만 담는다. LLM 후보는 다음 새 필드로 분리한다.
파일 7종, 함수 시그니처와 Stage enum은 유지한다.

```json
{
  "review_candidates": [{
    "id": "llm_candidate:app/main.py:1:2",
    "factor": 2,
    "file": "app/main.py",
    "line": 1,
    "evidence": "import json",
    "description": "검토가 필요한 후보",
    "source": "llm",
    "confidence": "needs_review"
  }]
}
```

위 객체는 `diagnosis` 안에 있으며 기본은 빈 배열이다. factor는 II/III/IV/VI/VII/XI만
허용한다. evidence가 해당 실제 소스 줄의 마스킹된 내용과 일치하는 발췌일 때만 줄 번호를
공개한다. 잘못된 위치/근거 후보는 버리고 diagnosis.warnings에 고정 코드를 남긴다.
위치 일치는 내용의 정확한 위반 판정을 뜻하지 않으며 후보는 계속 needs_review다.

A는 규칙 위반 수와 AI 검토 후보 수를 따로 표시하고 후보를 숨기지 않는다. 후보는 수정
선택지/규칙 확정/PR 승인 대상으로 취급하지 않는다. addressed_ids/deferred_ids와
transformation.status 및 추천 세트는 후보 유무와 무관하다. 후보 0개를 LLM 검토 성공으로
해석하지 말고 기존 enrichment_status와 execution_source를 함께 표시한다.
trace의 `llm-comparison.json.llm_candidates`에는 검증한 후보를 계속 기록한다.
로그/reason의 내부 마일스톤 번호는 제거했으나 Stage 값은 바꾸지 않았다.

### CLI 전용 데모 캐시

현재 웹(A) 흐름에는 이 캐시가 연결되어 있지 않다. 웹 호출 실패를 자동으로 복구하는
기능이 아니라 CLI로 전환하는 대비책이다. 캐시는 소스/엔진/파일 해시 및
settings_key(target_env, commit, source_repo, app_name, profile, image_reference,
tfvars_overrides, cost_assumptions, compare_original, max_request_seconds)가 모두 같아야 쓴다.
기본 명령은 다음이며 별도의 commit/source-repo/app-name 옵션을 추가하면 캐시가 맞지 않을 수 있다.

```sh
python -m ai analyze samples/todo --env onprem --use-demo-cache --llm none
python -m ai analyze samples/todo-scheduler --env aws --use-demo-cache --llm none
```

캐시가 안 맞으면 정상 규칙 분석으로 돌아간다. 위 고정 명령은 llm none이므로 이 경우에도
새 모델 호출은 없으며, 캐시 hit는 execution_source=demo_cache로 직접 확인해야 한다.
사전 결과의 gate.status=skipped/historical_status=passed/pr_eligible=false를 유지한다.
C smoke 스크립트는 명세 파일을 직접 읽으므로 CLI의 settings_key 검사나 추천 세트를
자동 적용하지 않는다. 갱신 후 C가 사용할 --out 경로를 따로 확인해야 한다.

녹화 v2는 제공자별 경로와 manifest의 제공자/origin/요청 모델/파라미터를 고정하고,
stage·응답 모델·파라미터·응답 및 요청 해시가 맞지 않으면 PlaybackError로 거부한다.
기존 Bedrock v1 응답은 변경하지 않고 별도 고정 metadata로 계속 검증한다.
Fake 녹화는 오프라인 테스트 전용이며 실제 제공자로 replay/캐시 검증할 수 없다.

현재 B는 로컬 레포 경로를 받아 진단 JSON, 코드 변경안 diff, Dockerfile과 배포 명세를 생성한다. GitHub URL 클론과 PR 생성은 A에서 연결한다. B의 HTTP 서버는 없다.

프로젝트 루트에서 Python 3.12로 설치한다.

```sh
python3.12 -m venv ai/.venv
ai/.venv/bin/python -m pip install -e 'ai[dev,login]'
ai/.venv/bin/python -m ai analyze samples/todo --llm none --out out/todo/
```

함수 호출 예시:

```python
from ai import run_analysis

result = run_analysis(
    "samples/todo",  # A가 클론한 레포의 로컬 경로
    out_dir="out/todo",  # 입력 레포와 분리된 출력 경로
    log=lambda stage, message: print(stage.value, message),
)
payload = result.model_dump(mode="json")
diff_path = result.output_files["changes.diff"]
# 자체 샘플의 proposed BuildContext는 사용 후 정리한다. 일반 앱에서는 None이다.
if result.build_context is not None:
    with result.build_context as context:
        print(context.root)  # 자체 샘플 게이트 입력 경로; 일반 앱은 None이다.
```

실제 LLM은 BedrockClient를 주입하거나 CLI에 --llm bedrock을 지정한다. 함수의 `llm`은 진단/초기 변경안, `decision_llm`은 추천 근거, `repair_llm`은 게이트 실패 수정용이다. 추가 호출을 명시적으로 선택하도록 각각 기본 None이다. CLI의 `--llm bedrock`은 이 셋에 같은 클라이언트를 전달한다. `artifact_llm`은 계속 별도 선택이다. 모델/프로필 설정은 ai/README.md를 따른다. --save-llm-trace를 추가하면 out에 입력·응답·규칙 비교를 남긴다. none/fake 결과는 실제 AI 검증으로 표시하지 않는다.

현재 샘플 결과는 원본 위반 6개, 변경안 반영 4개, 보류 2개다. SQLite 전환과 파일 저장 관련 needs_approval은 true다. 원본 DB와 코드는 변경하지 않는다. 데이터 이전은 미지원이다.

**runner=None/Fake/일반 앱의 gate-report.status는 skipped다. 자체 샘플을 Docker로 검증하면 passed/failed다. pr_eligible은 현재 false다.** 자동 PR 승인이나 배포 가능한 결과로 표시하지 않는다. A의 PR 생성 기능을 확인하려면 별도 테스트 저장소의 draft PR로 연동하고, 승인·배포 경로와 구분한다. Dockerfile은 고정 템플릿 lint, deploy-spec.yaml은 pydantic/JSON Schema만 통과했다. 두 자체 샘플의 Docker 빌드·읽기 전용 기동·임시 Postgres CRUD는 실제 검증했다. 일반 앱과 전체 기능 배포를 증명하지 않는다.

P3를 Fake로 확인하는 명령은 `--llm fake --artifact-llm fake --save-llm-trace`다. 함수의 `artifact_llm`은 Dockerfile(strong)/명세(fast) 제안용이며 기본 None은 규칙 템플릿만 쓴다. 기존 `llm`만 Bedrock으로 설정해도 추가 패키징 유료 호출은 생기지 않는다. 실제 패키징 호출은 명시적으로 `--artifact-llm bedrock` 또는 클라이언트 주입으로 선택한다.

두 자체 샘플은 임시 복사본에서 healthz, Postgres 저장·조회와 컨테이너 게이트를 검증했다. 일반 사용자 앱은 변경안 생성까지만 제공한다.

P4 호출은 CLI --gate docker 또는 함수 runner=DockerCliRunner()다. --gate fake는 실제 통과로 표시하지 않는다. gate-report의 scope/transformed/original/cleanup_errors와 recommendation.needs_approval을 함께 표시한다. 파일 저장 전환 보류와 risky DB 변경 승인, 데이터 이전 미지원 경고를 숨기지 않는다. 로그 callback에는 분석 중/빌드 중/검증 중이 전달된다.

P5는 `recommendation.set`을 규칙으로 고정하고 LLM에는 근거 문장만 맡긴다. C의 tfvars/단가가 미확정이므로 `needs_confirmation=["tfvars_schema", "cost_table"]`을 화면에 **임시 추정치**로 표시한다. 실제 인프라 적용 전 체크리스트는 `docs/p5-infra-confirmation-checklist.md`다. 변수 alias/범위/기본값은 `spec/tfvars_schema.py`, 비용 가정과 단가는 `spec/cost_table.py`에만 있다.

함수에 `runner=DockerCliRunner(), decision_llm=client, repair_llm=client`를 추가하면 자체 샘플의 추천/검증까지 수행한다. 최대 게이트 실행은 최초 포함 3회이며 성공·반복 제안·보안 검사 거부·비코드 실패 시 일찍 종료한다. `gate_report.attempts`, `retry_stop_reason`, `timings_s`를 A가 그대로 읽을 수 있다. 단계별 토큰/비용은 `cost.stages`에 모이고, 단가 미확정은 null이다. CLI `--no-gate`는 게이트 생략, `--no-compare`는 원본 복사본 비교 생략이다. 일반 앱은 이 옵션과 무관하게 게이트 skipped다.

P6의 엄격 LLM replay와 사전 결과 캐시를 지원한다. 현재 실행과 과거 검증/사용량 표시 및 예외 처리의 상세 계약은 docs/integration-for-service.md를 따른다. cache의 gate.status=skipped / historical_status=passed이며 pr_eligible=false다. 캐시 비용은 historical=true와 external_calls=0으로 표시한다.

## Anthropic 직접 API 선택 연결

설치: `python -m pip install -e 'ai[anthropic]'`. AI 분석 프로세스에
`ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL_ID_STRONG`, `ANTHROPIC_MODEL_ID_FAST`를 주입한다.
키는 SDK의 기본 인증 경로가 해석하며 함수/CLI 인자, 작업 JSON, 로그/trace에 넣지 않는다.
선택 설정은 `ANTHROPIC_EFFORT_STRONG`, `ANTHROPIC_EFFORT_FAST`,
`ANTHROPIC_REFUSAL_FALLBACK`이다. 이 키와 모델/effort 설정은 게이트 컨테이너에 절대 넘기지 않는다.
기존 runner의 환경 allowlist를 유지하고 프로세스 환경 전체를 컨테이너에 복사하지 않는다.
소스는 기존 마스킹 후 Anthropic으로 직접 전송된다.

```python
from ai.llm import AnthropicClient

client = AnthropicClient()  # 모델 환경변수 필수, SDK 인증 사용
result = run_analysis(
    repo_path,
    out_dir=output_dir,
    llm=client,
    decision_llm=client,
    no_gate=True,
    save_llm_trace=True,
)
# artifact_llm/repair_llm은 필요할 때 명시적으로 선택한다.
if result.build_context is not None:
    result.build_context.cleanup()
```

기존 Bedrock 연결과 기본값, 함수 시그니처는 유지한다. `--llm anthropic` CLI는
기존 Bedrock CLI처럼 llm/decision_llm/repair_llm에 같은 클라이언트를 전달한다.
짧은 확인 호출은 `python -m ai llm-check --llm anthropic --tier fast`이며 재시도 없이
1회만 전송한다. 결과는 out/llm-check/llm-check.json에 저장한다. 인증 오류/400/403/404,
타임아웃/최종 refusal/max_tokens는 자동 재호출하지 않는다. 개별 SDK timeout은 60초이며
전체 서비스 요청의 90초 제한 충족은 실측으로 따로 확인해야 한다.

fallback이 실행되면 trace의 실제 model_id, usage.fallback_ran/served_by_fallback/iterations를
확인한다. cost.calls는 모델별 시도이며 HTTP 요청 수와 다를 수 있다. fallback 앞선
refusal의 청구 여부를 모르면 cost.total.cost_usd=null이다. 토큰·known_cost_usd는 부분 집계다.
게이트/PR 자격·템플릿·replay/데모 캐시 계약은 변경하지 않는다.
