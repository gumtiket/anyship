# PR #13 병합 후 서비스 연결 — A/B 합의용 제안

AI 모듈은 main에 병합됐다. 웹 경로는 여전히 별도 연결 작업이다.
이 문서는 A의 analyze/modify 계약을 이미 변경했다는 뜻이 아니다.
B는 HTTP 서버, GitHub 클론/토큰 처리, PR 게시 또는 배포를 추가하지 않는다.
서비스(A)의 실행/DB/API 코드와 어댑터(C)의 코드는 이번 작업에서 수정하지 않는다.

## 지금 실행 가능한 B 전달 예제

`ai/scripts/service_handoff.py`는 새 out과 새 클라이언트로 분석하고 JSON을 stdout으로,
`log(Stage, message)` 진행 정보를 stderr로 보낸다. 컨테이너는 실행하지 않는다.
일반 결과 파일 7종은 out에 그대로 남는다. BuildContext는 전달 직후 finally에서 정리한다.
웹 응답용 JSON에는 절대 출력 경로·BuildContext·원시 컨테이너 로그를 넣지 않는다.
진단·변환·추천·미지원/실패·승인 필요·확인 필요·비용/출처는 유지한다.

프로젝트 루트(팀 저장소에서는 `AI/`)에서 실행한다.

```sh
# 이 SHA는 로컬 샘플 예제용 더미다. GitHub 기준 커밋을 검증했다는 뜻이 아니다.
ai/.venv/bin/python ai/scripts/service_handoff.py samples/todo \
  --base-sha 0000000000000000000000000000000000000000 \
  --mode fake --out out/service-handoff-001/
```

`--mode fake`는 실제 모델 응답이 아니며 출력의 llm_mode도 fake다.
`--mode none`은 규칙만 실행한다. `--mode bedrock`을 명시해야 실제 유료 모델을 호출한다.
SHA 형식은 검사하지만 코드와 SHA의 일치·GitHub 권한은 A가 검증해야 한다.
CLI 종료 코드 0은 전달 JSON을 만들었다는 뜻이다. analysis_status/gate/pr_eligible을 읽어야 한다.
요청별 새 out을 쓰고, 이전 요청의 out을 재사용하지 않는다.

service_payload(result, base_sha, llm_mode=...) 함수만 기존 결과에 적용할 수도 있다.
캐시/재생 결과의 출처와 historical 비용, 현재 skipped/과거 passed를 유지한다.
이 실행 예제는 commit이 결합된 새 요청이므로 캐시 모드는 제공하지 않는다.
캐시 사용은 기존 파이프라인의 코드·설정·SHA 일치 검사를 유지해야 한다.

## A와 먼저 합의할 세 가지

1. **코드 입력과 SHA:** A가 권한 확인한 기준 SHA의 코드 복사본과 로컬 경로를 B에 제공한다.
   A의 현재 AnalysisInput에는 project_id/repository/base_sha만 있으므로 코드 제공 경계를 추가해야 한다.
   GitHub 토큰·클라우드 자격 증명·서비스 DB 연결·사용자 비밀을 모델 입력에 넣지 않는다.
2. **항목 선택:** B의 위반 목록과 전체 변경안은 개별 적용 가능한 조각이 아니다.
   여러 수정이 같은 파일을 바꾸거나 healthz/ignore/DB 의존성에 묶인다.
   위반별 항목 선택 또는 하나의 변경 묶음 방식을 A와 정하고 수정/의존 관계를 검증한다.
   이번 예제는 진단 정보를 전달하며 modify 또는 선택별 diff를 제공하지 않는다.
3. **화면과 게시 경계:** gate.status/pr_eligible, transformation의 승인·보류 항목,
   recommendation.needs_confirmation, execution_source 및 cost.historical/external_calls를 보존한다.
   기존 서비스 모델에 진단 결과만 넣어 추가 필드를 버리면 안 된다.
   전달 예제의 contract_status는 proposal_needs_A_confirmation이며 현재 웹에 주입하지 않는다.

일반 앱은 컨테이너 gate skipped, PR 승인 가능 false다. DB/영속 저장 변경 승인과
"기존 데이터는 자동으로 이전되지 않는다. 데이터 이전 필요(미지원)" 경고를 유지한다.
캐시의 과거 Docker 통과 또는 샘플 통과를 사용자 앱 승인으로 바꾸지 않는다.
테스트 저장소의 검토용 Draft PR 흐름도 자동 승인·배포와 구분해 A와 합의해야 한다.

## Bedrock 실행 환경 — C/B 확인 필요

- 개인 개발: `aws login --profile ai-bronze --region ap-northeast-2` 후 같은 컴퓨터/사용자의 프로필로 호출한다.
  다른 개발자는 자신의 허가된 인증을 사용한다. 개인 로그인 정보·AWS 키는 Git에 전달하지 않는다.
- 운영: 서비스 서버 EC2 역할로 호출하도록 C와 구성한다. 개인 AWS_PROFILE을 서버에 복사하지 않는다.
- 서버 계정에서 Bedrock을 사용할지, 별도의 계정/역할을 사용할지는 아직 합의가 필요하다.
- C가 선택한 모델/교차 리전 프로필에 대한 호출 권한과 계정 모델 접근을 준비하고 B가 실제 호출을 확인한다.
- 본인의 검증된 임시 모델은 STRONG `global.anthropic.claude-sonnet-4-6`,
  FAST `global.anthropic.claude-haiku-4-5-20251001-v1:0`다.
  다른 계정의 접근을 보장하지 않으며 5.5는 현재 개인 개발 계정에서 접근 제한이 확인됐다.

서비스 실행 프로세스에 모델 ID와 리전을 설정한다. 아래는 권한을 부여하는 설정이 아니다.

```sh
BEDROCK_REGION=ap-northeast-2
AWS_DEFAULT_REGION=ap-northeast-2
BEDROCK_MODEL_ID_STRONG=global.anthropic.claude-sonnet-4-6
BEDROCK_MODEL_ID_FAST=global.anthropic.claude-haiku-4-5-20251001-v1:0
```

AWS CLI 브라우저 로그인을 사용하는 개발 환경은 AI 패키지의 login extra도 설치한다.
서비스 가상환경에 B를 설치할 때 팀 저장소 루트에서 `python -m pip install -e 'AI/ai[login]'`을 사용한다.
EC2 역할 인증은 개인 브라우저 로그인과 별개다.

AWS 공식 설명: [Boto3 인증](https://docs.aws.amazon.com/boto3/latest/guide/credentials.html),
[사용자 계정의 임시 배포 역할](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_common-scenarios_third-party.html).

## 합의 후 진행 순서

1. A의 코드 공급·항목 선택·결과 계약을 확정한다.
2. 위 Fake 결과로 A의 미지원/실패/승인 필요 표시를 연결한다.
3. 서버 권한이 준비되면 자체 샘플로 실제 Bedrock 분석과 사용자 diff 검토 흐름을 확인한다.
4. A/C의 mock 어댑터에 spec·선택한 set·실제 이미지 태그·별도 secrets·로그를 전달한다.
5. 실제 빌드/어댑터/게시·승인 경계는 각각 검증한 뒤 연결한다.

Refs #8, #22, #23. 이번 전달 예제만으로 웹 AI 연동 또는 운영 배포 완료를 주장하지 않는다.

## 이 전달 예제의 검증

새 경계 테스트 8개와 기본 전체 288개 통과 / 외부 연동 5개 skipped.
Fake CLI에서 JSON stdout과 진행 stderr 분리, 원본 fingerprint 유지,
미검증/승인 필요 보존과 컨텍스트 정리를 확인했다. 이번 작업의 새 AWS 호출은 없다.
이전 실제 Bedrock·두 샘플 Docker 검증과 새 Fake 전달 예제 검증은 구분한다.
