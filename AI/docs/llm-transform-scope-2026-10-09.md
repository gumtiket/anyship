# LLM 초기 변환의 수정 범위 검사 강화 — 2026-10-09

## 해결한 문제

기존 LLM 변경안 검사는 허용 파일, 클래스, 새 호출, 프레임워크/신호, 컴파일과 위반 해소를 검사했다. 그러나 같은 파일의 기존 함수나 상수를 바꾸는 것은 막지 못했다.

예를 들어 파일 로그를 없애는 변경안에 API 응답 `amount: 100 → 1`을 섞어도 file_log가 해소됐다는 이유로 승인됐다. 이번 변경은 초기 safe LLM 변환에서 이 문제를 거부한다.

## 바뀐 파일과 이유

| 파일 | 변경 | 이유 |
| --- | --- | --- |
| `ai/src/ai/transform/scope.py` | 지정 위반 위치와 Python AST 비교 검사 추가 | 같은 파일이라도 수정 목적 밖의 업무 코드는 바꾸지 못하게 함 |
| `ai/src/ai/transform/service.py` | LLM 변경안 승인 전에 범위 검사, 위치 재계산, safe/confirmed 조건 연결 | 새로운 검사를 실제 승인 경로에 적용하고 risky 후보가 safe 경로에 들어오지 않게 함 |
| `ai/src/ai/prompts/transform.txt` | 허용 표현식과 보존할 코드 명시 | 모델이 검사기에 맞는 작은 변경안을 생성하도록 안내 |
| `ai/tests/test_transform_scope.py` | 신규 회귀 35개 | 무관한 업무 변경은 거부하고 정상 변환은 유지되는지 확인 |
| `ai/tests/test_golden_cache.py` | 캐시 hit 테스트에 기록 당시 엔진 일치 조건 명시 | 과거 캐시를 현재 코드의 검증 기록으로 위장하지 않고 재생 동작 자체를 테스트 |

## 검사 방식

1. 규칙에서 확인한 `safe`, `confirmed`, `auto_fixable` Python 항목만 초기 LLM 변환 대상으로 삼는다.
2. 원본 진단의 줄 번호를 템플릿 적용/앞선 수정 후 소스에서 다시 찾는다. 위반 ID는 그대로 유지한다.
3. 기존 경로·시크릿·호출·프레임워크·신호·컴파일 검사를 수행한다.
4. 선택한 위반 위치의 허용된 표현식만 다른 AST를 인정한다. 다른 노드는 원래 구조를 유지해야 한다.
5. 범위 위반은 `patch_scope_violation`, 위치를 찾지 못하면 `patch_target_not_found`로 거부한다. 고정 오류 코드만 기존 재생성 루프에 전달한다.
6. 재생성도 실패하면 기존 보류 보고를 유지한다. 승인된 수정과 보류된 수정은 기존 addressed/deferred 필드로 표시한다.

줄 번호 이동은 기존 줄과 현재 줄의 대응으로 처리한다. 대상 줄이 사라졌거나 중복 줄 때문에 대상을 확정할 수 없으면 다른 위반 위치를 대신 수정하지 않고 보류한다.

## 허용·거부 예시

| 수정 목적 | 허용 | 거부 |
| --- | --- | --- |
| 파일 로그 | basicConfig의 filename/filemode 제거, 기존 level/format 유지, 필요한 경우 stream=sys.stdout 추가 | 로그 수정에 API 응답·인증조건·SQL·다른 함수 변경을 섞음 |
| 파일 핸들러 | 선택한 FileHandler 계열 호출을 StreamHandler(sys.stdout)로 교체 | 다른 핸들러/함수까지 임의 변경 |
| 포트 | 선택한 port 값을 int(os.environ["PORT"]) 또는 허용된 getenv 표현식으로 변경 | 같은 uvicorn 호출의 host/앱 진입점도 함께 변경, 다른 변수명·임의 기본값 사용 |
| 기존 DB 주소 설정 추출 | 선택한 DB URL 리터럴을 os.environ["DATABASE_URL"]로 변경 | 엔진 옵션·쿼리·DB 종류를 변경 |
| 더미 시크릿 설정 추출 | 선택한 더미 리터럴을 해당 환경변수 읽기로 변경 | 다른 설정값·실제 시크릿 복원·임의 변수 추출 |
| 필요한 import | 모듈 상단 import 구간에 os/sys/logging 별도 import 추가 | 기존 이름을 덮어쓰는 import, 임의 라이브러리·별칭 추가 |

함수 전체를 무조건 고정하지 않는다. 함수 안의 지정 설정 표현식은 수정할 수 있고, 같은 함수의 조건문·반환값·다른 호출은 보존한다. 위치 정보·일반적인 포매팅·주석 변화는 AST 자체의 비교 대상이 아니다. 아래 후속 수정에서 주석과 인코딩에 별도 검사를 추가했다.

## 최초 수정 검증 결과 (후속 수정 전)

- 기본 전체: **330 passed, 5 skipped**, 17.93초.
- 신규 범위 회귀: **35개 통과**. 초기 295개에 추가했다.
- Ruff check/format check 통과. Python 파일 81개 format check 통과.
- 기존 Starlette/httpx 사용 중단 예정 경고 1개가 있다.
- 테스트는 Fake LLM과 임시 복사본에서 수행했다. 새 Bedrock/Docker 호출은 없다.
- 일반 앱은 gate skipped / pr_eligible=false를 유지하는 파이프라인 사례를 확인했다.
- 소스와 더미 DB를 포함한 입력 디렉터리 fingerprint 보존을 확인했다.
- 샘플·골든·LLM fixture·데모 캐시·reference·기준 계획 문서의 보호 파일 137개가 변경되지 않았다.

재현했던 파일 로그 + API 응답값 변경은 이제 거부된다. 새 테스트에는 인증조건·SQL 문자열·기존 호출 인자·전역 상수·기본 인자·라우트·다른 함수·로그 level/format 변경도 포함한다.

정상 로그 제거, stdout 전환, 함수 내부 PORT 읽기, DB 주소 설정 추출, 더미 시크릿 추출, 여러 줄 로그 설정, 템플릿 후 줄 번호 이동, 개별 재시도에서의 줄 번호 이동, 오류 피드백 후 정상 재생성도 확인했다.

## 적용 범위와 남은 확인

이번 검사는 `llm_patch`의 초기 safe 변환에 적용한다. 고정 템플릿 변환과 샘플 런타임 실패 복구(`repair_context`)의 별도 승인 정책은 바꾸지 않았다. 따라서 모든 LLM 복구나 임의 Python 코드의 안전성을 증명한 것은 아니다.

지원하는 좁은 표현식 밖의 합법적인 구현도 보수적으로 보류할 수 있다. 새 표현식을 허용하려면 그 범위와 업무 코드 보존 테스트를 먼저 추가해야 한다.

기존 출력 모델/7종 계약, DB·파일 저장 승인, 데이터 이전 미지원, 일반 앱 컨테이너 실행 제한은 유지한다.

### 기존 데모 캐시

엔진 소스/프롬프트가 달라졌으므로 저장된 캐시의 engine_hash가 현재 코드와 일치하지 않는다. 실제 캐시 사용은 정상 분석으로 fallback한다. 과거 캐시의 해시나 검증 상태를 수동으로 수정하지 않았다.

캐시 hit 테스트는 기록 당시 엔진이 일치하는 조건을 mock하여 과거 결과 재생·미검증 표시·외부 호출 없음 동작을 검사한다. 별도의 engine mismatch 테스트는 실제 불일치에서 fallback하는 동작을 계속 검사한다. 이 테스트 통과가 현재 엔진의 새 Docker 검증을 뜻하지 않는다.

새 엔진에서 데모 캐시를 다시 사용하려면 자체 샘플의 게이트를 실제로 재실행해 캐시를 생성해야 한다. 이번 작업에서는 캐시 재생성이나 실제 STRONG 호출 품질 확인을 수행하지 않았다.

## 실행 방법

팀 저장소에서는 `AI/`, 로컬 개발에서는 `ai/`와 `samples/`가 있는 프로젝트 루트에서 실행한다. `ai/.venv`에 개발 의존성이 설치되어 있다는 전제다.

```sh
ai/.venv/bin/python -m pytest ai/tests/test_transform_scope.py -q
ai/.venv/bin/python -m pytest ai/tests -q -ra
ai/.venv/bin/ruff check ai
ai/.venv/bin/ruff format --check ai
```

기존 analyze CLI와 run_analysis 사용법은 같다. 추가 입력이나 서비스 HTTP 서버가 필요하지 않다.

## 후속 수정: 승인한 1·3·4·5 및 제한한 2

### 변경 내용과 이유

| 항목 | 구현 | 이유 |
| --- | --- | --- |
| 1. 인코딩 선언 보호 | `check_patch_scope`에서 `tokenize.detect_encoding` 결과와 첫 두 줄의 coding cookie를 비교한다. 추가·변경·삭제는 `patch_scope_violation`이다. | Unicode 문자열 AST가 같아도 실제 파일 바이트 해석이 달라져 한글 등의 값이 손상될 수 있다. UTF-8 선언 추가도 이 경로의 수정 목적 밖이다. |
| 2. 제한한 주석 보호 | 선택한 AST 표현식의 시작~끝 줄 안의 주석만 수정 가능하다. 그 밖의 `COMMENT` 토큰 내용과 순서를 보존한다. | 대상 밖의 설명이나 `noqa`/`type: ignore` 변경을 섞지 못하게 하면서, import 추가나 여러 줄 설정 수정으로 줄 번호가 이동하는 정상 수정은 허용한다. |
| 3. 보류 사유 표시 | `llm_transform_deferred` 메시지에 `[patch_scope_violation]`, `[patch_target_not_found]` 등 고정 코드를 넣는다. 알 수 없는 예외는 `[llm_patch_failed]`로 표시한다. | 왜 보류됐는지 확인할 수 있고, 소스·SDK 예외 원문은 출력하지 않는다. 같은 거부안을 반복하면 앞서 확인한 거부 사유를 유지한다. |
| 4. 시크릿 프롬프트 | 더미 시크릿 리터럴 → `os.environ["NAME"]`, 원래 변수명의 대문자 이름, 시크릿 기본값 없음이라고 명시한다. | 생성 지시를 실제 허용 표현식과 일치시킨다. 실제 시크릿 복원이나 변환 지원 범위 확대는 없다. |
| 5. 캐시 최신성 구분 | mock 기반 재생 테스트를 유지하고, `todo`/`todo-scheduler` 캐시의 실제 `engine_hash`를 현재 엔진과 비교하는 별도 테스트 2개를 추가했다. | 재생 로직 통과와 현재 엔진에서 캐시가 유효하다는 사실을 분리한다. |

변경 파일은 `transform/scope.py`, `transform/service.py`, `prompts/transform.txt`, `test_transform_scope.py`, `test_golden_cache.py`, `test_diagnose_transform.py`와 이 설명 문서다.

주석 예외는 줄 단위다. 같은 대상 줄의 다른 주석과 여러 줄 설정 표현식 내부 주석도 허용한다. 함수 전체나 파일 전체는 예외로 삼지 않는다. 문자열 안의 `#`는 주석으로 취급하지 않는다. 주석의 내용·순서를 검사하며 정확한 위치나 공백까지 고정하는 검사는 아니다. 인코딩 선언은 이 주석 예외로 허용하지 않는다.

기존의 “주석만 바꾸고 위반 해소를 주장”하는 단위 테스트는 두 경우로 나눴다. 대상 밖 주석 추가는 새 범위 검사에서 거부하고, 대상 줄의 허용된 주석 변경은 위반 해소 검사에서 거부한다. 거부 검사를 완화하거나 골든 정답을 바꾸지 않았다.

### 수정 전후 검증

| 검사 | 수정 전 | 수정 후 |
| --- | --- | --- |
| 기본 전체 pytest | 330 passed, 5 skipped, 18.75초 | **354 passed, 5 skipped, 2 xfailed**, 20.90초 |
| Ruff check | 통과 | 통과 |
| Ruff format check | 81개 파일 통과 | 81개 파일 통과 |

외부 호출 테스트 5개는 기본 실행 정책에 따라 건너뛰었고, 기존 Starlette/httpx deprecation 경고 1개는 동일하다. 새 일반 회귀 테스트는 24개이며, 인코딩 변경+한글, 선언 유지, 대상 밖 주석 추가/변경/삭제, 대상 주석 허용, 여러 줄 표현식과 import 이동, 보류 사유, 예외 원문 비노출을 포함한다. 별도로 캐시 최신성 검사 2개가 추가됐다.

캐시 검사 2개는 현재 불일치를 **사유가 표시되는 임시 `xfail(strict=True, raises=AssertionError)`**로 기록했다. 캐시를 갱신한 뒤에도 이 표시를 남기면 XPASS가 실패가 되어 정리를 요구한다. 파일 누락·JSON 오류까지 예상 실패로 숨기지 않는다. `-ra` 옵션으로 사유를 확인할 수 있다. 이 결과는 최신 캐시 검사 통과를 뜻하지 않는다.

샘플·골든·LLM fixture·데모 캐시·reference·기준 계획 문서 보호 파일 137개는 SHA-256 비교에서 변경이 없었다. 검증은 Fake LLM과 임시 복사본으로 진행했고 AWS/Bedrock/Docker 호출은 0회다. 원본 앱·DB 변경, 데이터 이전, 일반 앱 컨테이너 실행, PR 자격 판정 변경은 없다.

### 남은 작업

- 사용자 확인 후에만 `ai/scripts/build_demo_cache.py`로 기존 응답 replay + 실제 Docker 검증을 통한 캐시 재생성을 검토한다. 이번에는 실행하지 않았다.
- 재생성 후 임시 xfail을 제거하고 최신성 검사를 일반 필수 테스트로 유지한다. 프롬프트가 바뀌어 기록된 요청 해시와 맞지 않으면, 기존 기록을 임의로 수정하지 않고 그 불일치를 먼저 보고한다.
- 실제 모델의 새 프롬프트 생성 품질과 Docker 실행 결과는 이번 Fake 기반 회귀 검증으로 확인한 것이 아니다.

## 팀 저장소 PR 구성 검증

2026-10-09 기준 팀 저장소 `main`의 `414c198a3419eee13be50a95919b0a8961bcc43a`에서 이번 변경 7개 파일만 적용해 별도로 검증했다. 로컬의 다른 미커밋 구현, 서비스 전달 PR #24, Windows 호환 PR #32는 포함하지 않았다.

- 팀 저장소의 실제 소스 경로로 import되는 것을 확인한 뒤 전체 테스트: **339 passed, 5 skipped, 2 xfailed**, 19.69초.
- Ruff check와 format check: **75개 Python 파일 통과**.
- 로컬 개발 전체 결과와 개수가 다른 것은 별도 PR의 파일/테스트를 이 PR에 넣지 않았기 때문이다. 캐시 최신성 예상 실패 2개와 기존 deprecation 경고 1개는 동일하다.
- 커밋 범위에 샘플, DB, 골든, LLM fixture, 캐시, 서비스, 인프라, IAM 파일과 생성 산출물은 포함하지 않았다.


## 실제 Bedrock diff 적용 실패 수정과 재검증

### 문제와 수정 이유

실제 Sonnet 응답에서 파일 헤더의 `a/`, `b/` 접두사 누락과 잘못된 hunk 줄 수가 확인됐다. 또한 모델은 마스킹된 소스의 `[REDACTED]` 문맥을 반환하므로 이를 그대로 원본에 `git apply`하면 문맥이 맞지 않는다. 범위 검사를 통과하기 전에 전송 형식에서 실패하던 문제다.

| 파일 | 변경 | 이유 |
| --- | --- | --- |
| `transform/patch.py` | 초기 변환용 diff 정규화 추가 | 실제 이전 줄이 정확하게 한 곳에서 일치할 때만 변경을 구성하고 올바른 Git diff를 다시 생성한다. 모델이 쓴 줄 번호/줄 수를 적용 위치의 근거로 쓰지 않는다. |
| `transform/service.py` | 정규화 후 기존 승인 검사 수행, 고정 실패 코드 추가 | 형식 복구가 범위 승인으로 간주되지 않도록 원본 기준 경로·시크릿·AST·컴파일·신호·위반 해소 검사를 유지한다. |
| `prompts/transform.txt` | 헤더·본문 형식, 정확한 문맥, 마스킹 표식 취급 명시 | 모델 응답의 형식 오류를 줄인다. |
| `transform/scope.py` | `stream=sys.stdout`을 기존 로그 인자 사이에도 삽입 가능 | 실제 응답은 stdout 인자를 맨 앞에 넣었다. 기존 level/format 등 인자의 값과 상대 순서를 유지하면 같은 허용 변환이다. |
| `test_transform_patch.py`, `test_transform_scope.py` | 추가 회귀 38개 | 형식 복구 성공과 범위·시크릿 보호를 함께 검증한다. |

마스킹된 파일에서 바뀌지 않은 줄은 원본 줄을 그대로 복사한다. `[REDACTED]` 값을 시크릿으로 역치환하지 않는다. 수정·추가 줄에 표식이 남거나 마스킹 전후 줄 대응이 맞지 않으면 보류한다. 한 줄에 시크릿과 수정 대상이 함께 있어 표식을 제거할 수 없는 경우도 보류한다.

허용 파일의 정확한 이름만 접두사를 보완한다. 경로 이탈, 새 파일·삭제·이름 변경, 파일 모드 변경, 중복 파일, 없는 문맥·중복 문맥·겹친 hunk는 거부한다. 문맥이 없는 순수 삽입도 추측하지 않는다. 초기 `llm_patch`에만 적용하며 runtime repair 경로는 확장하지 않았다.

stdout 인자 위치를 허용해도 로그 level/format 변경, 기존 인자 순서 변경, stderr 사용, force/handlers 추가는 거부한다. 다른 업무 코드·인코딩·대상 밖 주석 보존 규칙도 유지한다.

### 확인한 실제 호출 결과

Haiku 4.5 / Sonnet 4.6으로 새 Bedrock 호출을 수행했다. 입력은 로컬에서 만든 작은 FastAPI 검증 앱이며 컨테이너 실행이나 배포를 하지 않았다.

- 직접 변환: Sonnet 1회로 더미 시크릿 환경변수 추출·PORT 읽기·stdout 로그 3개 변경을 생성하고 실제 diff 적용·컴파일·범위 검사를 통과했다.
- 전체 `run_analysis`: Haiku 진단 1회 → 고정 템플릿의 시크릿/포트 변경 → Sonnet 로그 수정 1회 → Haiku 추천 1회가 성공했다. `addressed_ids` 3개, `deferred_ids` 0개, `llm_attempts=1`, `patch_valid=true`, `compile_passed=true`, 추천 `rationale_source=llm`이다.
- 성공 실행은 총 4회, 입력 5,525 / 출력 1,080 토큰이다. replay나 수동으로 응답을 바꾼 결과가 아니다.
- 중간 실행에서는 직접 변환은 성공했으나 stdout 인자 순서 때문에 전체 흐름의 로그 수정이 3회 거부됐다. 이 오탐을 수정한 뒤 위 성공 실행을 확인했다. 이번 후속 작업의 실제 호출은 중간 실행 포함 총 9회다.
- 이전에 형식 오류로 거부된 실제 응답 6개도 저장 응답을 이용한 오프라인 검사에서 통과했다. 이것은 추가 실시간 호출 성공 횟수로 집계하지 않는다.
- 입력 앱·더미 DB 파일 fingerprint와 업무 함수의 AST가 보존됐다. DB 접속이나 데이터 이전을 검증한 것은 아니다.
- 게이트는 `skipped`, `pr_eligible=false`다. 이번 성공은 safe 코드 변경안 검증이며 Docker/Postgres 게이트·자동 PR 자격·실제 배포 성공을 의미하지 않는다.
- 모델 단가가 등록되지 않아 비용은 `null`이다. 토큰 사용량은 기록했으며 무료라고 표시하지 않는다.

로컬 성공 증거는 `out/live-transform-fixed-d75km7zs/summary.json`, `direct-diff.patch`, `pipeline-result/changes.diff`, `pipeline-result/llm-trace.json`에 보관했다. 인증 정보나 생성 실행 산출물은 PR에 포함하지 않는다.

### 최종 회귀 검증

- 수정 전: 로컬 **354 passed, 5 skipped, 2 xfailed** / Ruff Python 81개 통과.
- 수정 후: 로컬 **392 passed, 5 skipped, 2 xfailed** / Ruff Python 83개 통과.
- 팀 PR 체크아웃: **377 passed, 5 skipped, 2 xfailed** / Ruff Python 77개 통과.
- 팀 첫 실행에서는 CRLF 테스트 1개가 기존 `Workspace.read()`의 줄바꿈 정규화로 실패했다. 전송 형식 테스트가 파일 바이트를 직접 읽도록 수정했다. 별도 Windows PR의 구현은 가져오지 않았다.
- 기존 Starlette/httpx 경고 1개와 캐시 엔진 불일치 예상 실패 2개는 유지한다.
- 보호 파일 137개는 변하지 않았다. 골든, 샘플, 기존 응답 fixture, 데모 캐시는 갱신하지 않았다.

재현은 위 전체 테스트 명령 또는 `ai/.venv/bin/python -m pytest ai/tests/test_transform_scope.py ai/tests/test_transform_patch.py -q`다. 실제 Bedrock 검증은 별도 유료 실행 기록이며 기본 pytest는 외부 호출 없이 통과한다. Docker 게이트·캐시 재생성·서비스/어댑터 연동과 PR 자격 결정은 후속 작업으로 남는다.
