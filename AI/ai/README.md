# Bronze AI — P5

실행 기준 디렉터리는 팀 저장소의 `AI/`다. 상위 [시작 안내](../README.md)를 먼저 따른다.

## 출력과 상태

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

진단은 원본 기준이며 변경안 반영 여부는 `transformation.addressed_ids/deferred_ids`로 구분한다. 자체 샘플의 위반 6개 중 4개를 제안에 반영하고, 파일 저장 전환과 미확인 의존성 버전 고정은 보류한다. `partial`을 전체 준수로 표시하지 않는다.

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

선택 순서는 onprem 대상 → scheduler → websocket → 최대 요청 시간 후보가 25초 초과 → 짧은 요청이다. 각각 onprem / aws-always-on / aws-always-on / aws-always-on / aws-serverless다. 25초는 배치 규칙이며 플랫폼 제한이 아니다. 최대 요청 시간 기본 후보 10초는 실측값이 아니다.

FAST는 근거 문장만 작성한다. 다른 세트를 주장하면 재생성 후 규칙 템플릿으로 대체한다. 설명의 모든 사실 오류를 자동 검증하는 기능은 없다. C 확인 전 변수명/범위/default는 `src/ai/spec/tfvars_schema.py`, 단가/가정은 `src/ai/spec/cost_table.py` 한 곳에서 관리한다. Lambda와 EC2 Compose 변수 모델을 나누고 범위 오류는 클램프 없이 경고+기본값 대체다.

`--image-tag`/함수 `image_reference`가 없으면 이미지 값을 생략한다. A가 실제 이미지 주소/태그/digest를 확정해야 한다. `--tfvars-json`은 선택 세트의 변수 객체를 읽는다. `--no-gate`는 게이트 생략, `--no-compare`는 원본 복사본 비교 생략이며 일반 앱의 실행을 허용하지 않는다.

`needs_confirmation=["tfvars_schema", "cost_table"]`과 **임시 추정치**를 화면에 표시한다. 리전·요청 수·가동 시간·평균 실행 시간·스토리지·프리티어 제외·누락 비용은 assumptions에 있으며 실제 적용 전 [C 체크리스트](../docs/p5-infra-confirmation-checklist.md)를 확인한다. DB/파일 변경 승인과 `data_migration_unsupported` 경고를 함께 표시한다.

## 검증과 남은 작업

로컬 P5 기준 기본 테스트 195 passed / 외부 연동 5 skipped, 실제 Docker 선택 테스트 3 passed다. 실제 FAST Haiku 4.5 + Docker는 todo=aws-serverless / todo-scheduler=aws-always-on으로 끝까지 검증했다. 실제 STRONG 생성 복구 품질은 미검증이며, 복구 루프는 Fake 수정안+실제 Docker로 검증했다. 이력 결과를 이 저장소에 포함하지 않으므로 새 환경에서 위 명령으로 재현한다.

P6 골든 테스트/캐시, C 계약 확정, A의 권한 확인된 코드 자료 제공과 AIProvider 연결은 남아 있다. 게이트 통과는 샘플 기동/CRUD 범위의 증거이며 전체 기능·PR 승인·클라우드 배포 준비 완료를 뜻하지 않는다.
