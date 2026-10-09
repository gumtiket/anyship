# 독립 검토 후 수정 결과 — 2026-10-09

## 수정한 내용

- 마스킹·진단을 같은 자격 증명 기준으로 묶고 함수 인자, getenv 별칭/키워드 기본값,
  Authorization, 사용자 이름 없는 URL·쿼리 인증 값, 중첩 JSON을 처리했다.
  LLM 입력·응답·trace·명세·diff의 알려진 비밀값을 보호한다. 모든 비밀 패턴 탐지를 보장하지 않는다.
- 일반 설정 / 확인된 템플릿의 생성 SECRET_KEY / 사용자 제공 비밀을 구분한다.
  기존 DB URL이나 API 키를 임의 생성하지 않으며 기존 외부 자원 주소는 사용자에게 확인한다.
  여러 사용처에서 기본값이 충돌하면 사용자 입력을 요구하고 비밀 사용처가 있으면 비밀 분류를 유지한다.
- 직접 sqlite3/aiosqlite 연결과 누락·빈 의존성 선언을 진단한다.
  드라이버 접두사 치환을 하드코딩된 DB 주소로 오인하지 않는다.
  `ok`는 규칙에서 위반을 찾지 못한 상태라는 경고를 제공한다.
- PORT·위험한 이름·중복·secret/generate/value·줄바꿈·NUL·알려진 크기 합계를 검사한다.
  C가 최종 값을 주입한 뒤 전체 크기를 검증해야 한다.
- 배포 세트/시간/ingress는 규칙과 명시 입력으로 정한다. LLM 후보로 바꾸지 않는다.
  팀 MVP 30초 경계와 서버리스 tfvars 1~30을 한 파일에서 관리한다.
  public만 허용하고 object_storage 명세는 MVP에서 거부한다.
- 새 out에 전체 결과를 한 번에 게시한다. 기존 결과 폴더와 동시에 공유하는 클라이언트는 거부한다.
  실패 시 임시 컨텍스트를 정리하고, 비정상 JSON 응답은 게이트 실패 보고로 처리한다.
- .dockerignore를 changes.diff에 포함하고 보조 파일/캐시에서도 제공한다.
  기존 패턴을 보존하며 PR 변경안과 실제 샘플 빌드 컨텍스트가 같은 내용을 사용한다.
- FastAPI의 Starlette 보조 import와 독립 앱/여러 진입점을 구분한다.
  pyproject의 정상 의존성 선언은 인정하지만 현재 지원하지 않는 패키징은 명세 생성을 보류한다.
- app_name과 max_request_seconds 입력을 추가했고 로컬 source 기본값에 개인 절대 경로를 넣지 않는다.

## 검증

- 기본 pytest: **280 passed / 외부 연동 5 skipped**. 기존 Starlette/httpx 경고 1개.
- 새로운 검토 회귀: **51 passed**. 이동 복사본의 새 환경에서 관련 **75 passed**.
  ruff check/format, 두 샘플 골든 통과.
- 두 원본 샘플의 코드/DB를 수정하거나 기동하지 않고 임시 변환본을 검증했다.
- 실제 Docker/임시 Postgres: 두 샘플의 초기화·CRUD·재시작 후 읽기·원본 복사본 실패 비교 통과.
  검증용 컨테이너·네트워크 정리 확인.
- 기본 7종 계약 유지. 샘플의 변경 파일은 .dockerignore 포함 5개다.
- 골든 변경은 명세, 확인 필요 목록, 변환 보고서, diff 해시로 제한되었고 Dockerfile 바이트는 유지했다.

## LLM 검증 출처

초기 시도는 AWS 로그인 만료(LoginRefreshRequired)로 중단됐고, 그 실패를 성공으로 저장하지 않았다.
재로그인 후 개발 IAM 사용자 인증을 확인하고 실제 Bedrock 분석을 새로 수행했다.

- FAST: `global.anthropic.claude-haiku-4-5-20251001-v1:0`.
- STRONG: `global.anthropic.claude-sonnet-4-6`. 5.5 접근 승인은 이번에 재검증하지 않았다.
- todo/todo-scheduler 각각 진단·추천 2회씩, 실제 Docker/임시 Postgres 게이트 passed.
  두 샘플 모두 규칙 ID·판정·담당·신호는 보존됐고 설명 6개씩 보강됐다.
  범위/근거가 부적합한 AI 후보는 거부됐으며 검증된 새 위반으로 추가되지 않았다.
- 파일 로그 변환용 작은 FastAPI 입력을 별도로 작성해 FAST 진단 1회와 STRONG 코드 생성 1회를 검증했다.
  Sonnet이 `logging.basicConfig`의 파일 출력을 제거한 diff는 적용·컴파일·위반 해소 검사를 통과했다.
  원본은 보존됐으며 이 입력은 자체 런타임 샘플이 아니므로 컨테이너 게이트 skipped / PR 승인 불가다.
- 실제 호출 총 **6회**, 입력 **10,334**, 출력 **3,401** 토큰. 모두 schema 파싱 성공.
  단가 미확정이므로 비용은 **null**이며 0달러나 실제 청구액으로 표시하지 않는다.
- 실제 STRONG 코드 생성은 이 한 사례에서 검증됐으며 DB/복잡한 재시도/일반 앱/운영 배포 품질을 증명하지 않는다.

마스킹된 프롬프트·응답 원문·파싱 결과·규칙 비교·사용량은 로컬 `out/`의 요청별 trace에 저장했다.
개인 실행 trace는 공개 저장소에 넣지 않는다.
배포하는 기본 데모 캐시는 이번 실제 FAST + 새 Docker 검증 결과로 갱신했다.
캐시 복원 시 현재 게이트는 skipped, 과거 Docker 통과만 historical_status=passed로 제공한다.
고정 LLM replay fixture는 이전 실제 응답 그대로 보존해 회귀 기준을 임의로 바꾸지 않았다.
명시적 replay + 새 Docker 캐시 생성 기능도 유지하며 이 경우 provenance에
llm_execution_source=llm_replay와 recorded_llm_usage를 표시해 신규 Bedrock 호출과 구분한다.

## 실행과 남은 작업

프로젝트 루트(팀 레포에서는 AI/)에서 요청별 새 폴더를 지정한다.

```sh
ai/.venv/bin/python -m ai analyze samples/todo --llm replay --out out/review-run-001/
ai/.venv/bin/python -m ai analyze samples/todo --use-demo-cache --out out/review-cache-001/
ai/.venv/bin/python -m pytest ai/tests -q
```

A는 새 out·새 클라이언트, app_name/source_repo/commit, 현재 결과/예외, BuildContext 정리,
diff의 ignore 변경, partial/risky/승인·캐시 출처 표시를 연결해야 한다. B의 HTTP 서버는 만들지 않았다.
C는 예약어/동일 ENV 정책/최종 4KB/30초 override/운영 마이그레이션 권한·실제 변수·단가·이미지 계약을 확인해야 한다.

현재 MVP 예시는 reference/deploy-spec.mvp.yaml이다. 기존 example은 확장 초안으로 보존했고
그 안의 object_storage가 현재 MVP에서 허용된다는 뜻은 아니다.

새 실제 FAST 분석과 STRONG 로그 변환 검증은 완료했다. 복잡한 STRONG 복구 품질은 추가 확인 대상이다.
루트 콘솔 세션으로 개발 프로필 권한을 확대하지 않았다. 일반 앱 컨테이너 실행/데이터 이전/운영 배포는 범위 밖이다.
Git은 Issue #16 / Draft PR #13으로 검토하며 main 머지는 별도다.
