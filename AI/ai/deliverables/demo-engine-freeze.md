# 2026-10-11 시연용 B 엔진 동결

이번 PR은 엔진·도구·오프라인 회귀와 자체 샘플 Docker 검증까지 수행한다.
실제 모델 호출, 새 응답 녹화, 골든 정식 갱신, 데모 캐시 재생성은 다음 단계다.
최종 commit과 engine_hash를 PR 본문/검증 보고에 고정한다. PR은 머지하지 않는다.

동결 engine_hash: `d9ac3c2c0e01033cd1c6cf0ae3aa9881287d35e5ec393bbed3d7be2611c8b3a8`.
검증: 기본 487 passed / 5 skipped / 기존 캐시 최신성 2 xfailed, Ruff 통과.
LLM 없이 todo(onprem)·todo-scheduler(aws) 각각 Docker 게이트 1회 통과.

## 출력과 안전 경계

- `diagnosis.violations`: 규칙 위반만. `review_candidates`: 검증된 위치의 LLM 검토 후보.
- 후보의 원칙 번호는 II/III/IV/VI/VII/XI다. 실제 소스 줄의 마스킹된 발췌와 evidence가
  맞을 때만 출력한다. 맞지 않으면 후보를 버리고 고정 warning을 남긴다.
- 후보 유무는 규칙 판정·addressed/deferred·변환 상태·추천 세트를 바꾸지 않는다.
  후보는 계속 JSON/trace/CLI 개수에 표시하되 사용자 검토 대상이며 자동 수정 대상이 아니다.
- 골든은 후보와 LLM 설명 문장을 제외한다. diff/Dockerfile 해시·명세·세트·tfvars·
  변환 결과와 경고 코드 검사는 유지한다. #42의 scheduler 기대값 보정은 현재 유지한다.
- 원본/DB/샘플 manifest는 수정하지 않는다. DB 변경 승인과 데이터 이전 미지원,
  자체 샘플 외 실행 금지, pr_eligible=false는 유지한다. 시드·AI 우선 모드는 넣지 않는다.

## 녹화·replay 계약

새 녹화는 `<root>/<bedrock|anthropic>/<sample>/manifest.json`에 기대 제공자, origin,
요청 모델과 파라미터를 고정한다. stage 파일 v2의 entry에도 요청 파라미터를 보존하며
요청 해시는 제공자·요청 모델·파라미터·system/user·tier를 묶는다.
각 stage의 origin/모델/파라미터/응답 해시와 실제 요청 해시가 하나라도 다르면
PlaybackError로 실패한다. 정상 LLM fallback으로 삼키거나 다른 제공자로 넘어가지 않는다.
replay는 SDK/키 없이 snapshot을 사용한다. 호출자는 expected_models/expected_parameters로
기대 설정을 추가 지정할 수 있다. 설정을 바꿀 때는 기존 기록을 덮지 말고 새 경로에 녹화한다.

기존 Bedrock v1의 네 stage 응답은 변경하지 않았다. 고정된 legacy metadata 두 개로
해당 요청 모델과 파라미터를 검증한다. 새로운 엔진/환경에 맞는 응답으로 위장하지 않는다.
Fake의 namespaced 녹화는 테스트 전용이며 실제 제공자 replay/데모 캐시로 사용할 수 없다.
metadata와 해시는 손상·오사용 검사용으로, 외부인이 준 파일을 인증하는 서명이 아니다.

## CLI 대비책

캐시는 소스/엔진/출력 해시와 settings_key의 모든 필드가 같을 때만 hit한다.
생성 환경은 todo=onprem, todo-scheduler=aws다. 다음 두 명령을 고정한다.

```sh
python -m ai analyze samples/todo --env onprem --use-demo-cache --llm none
python -m ai analyze samples/todo-scheduler --env aws --use-demo-cache --llm none
```

commit/source_repo/app_name/profile/image_reference/tfvars/cost assumptions/compare_original/
max_request_seconds를 바꾸면 hit하지 않을 수 있다. 캐시가 안 맞으면 정상 규칙 분석으로
넘어가며 llm none이므로 모델 호출은 없다. execution_source를 보고 hit를 직접 확인한다.
현재 웹(A)에서는 사용하지 않는다. 웹 시연 실패 시 CLI로 전환하는 별도 대비책이다.
캐시 gate는 skipped, historical_status=passed, pr_eligible=false다. 재생 로그는 사전 결과다.
C smoke 스크립트는 raw 파일을 읽으므로 추천 세트나 settings_key를 자동 적용하지 않는다.

## 다음 단계 — 아직 실행하지 않음

팀 저장소의 AI 디렉터리에서 시연용 설치/모델 환경변수를 준비하고 새 기록 경로를 쓴다.
키는 AI 프로세스에만 전달하며 명령 인자·녹화·게이트 컨테이너에는 넣지 않는다.

```sh
# 유료 호출 + 두 자체 샘플의 Docker 검증. 다음 단계에서만 실행.
python ai/scripts/build_demo_cache.py --llm anthropic --fixtures out/demo-recordings

# 새 모델 호출 없이 녹화를 다시 읽고 실제 Docker 검증.
python ai/scripts/build_demo_cache.py --llm replay --llm-provider anthropic --fixtures out/demo-recordings

# 골든의 차이를 먼저 검토. 이 명령은 기본적으로 파일을 덮지 않는다.
python ai/scripts/refresh_golden.py --llm-provider anthropic --demo-env --fixtures out/demo-recordings
```

의도한 차이를 확인한 후에만 --accept로 골든을 갱신하고, 다음 작업에서 #42 기대값 보정을
제거하며 todo의 공식 골든 환경도 onprem으로 맞춘다. 캐시 최신성 두 테스트가 실제로
통과한 뒤 임시 xfail을 제거한다. 날짜·엔진 해시만 바꿔 캐시를 최신으로 표시하지 않는다.

동결 뒤 엔진 소스/프롬프트/모델 계약을 바꾸면 녹화·캐시 검증을 다시 해야 한다.
일요일 오전에는 같은 commit/모델/고정 명령과 준비된 환경으로 실시간·CLI 대비책을 리허설한다.
