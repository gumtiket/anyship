# A가 현재 AI 파트에 연결하는 방법 (P5)

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
