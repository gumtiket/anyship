# AnyShip AI 연결 경계

## Fake 연결 검증 (#28)

`APP_AI_MODE=fake`는 GitHub에서 권한 확인한 기준 SHA의 코드를 실제 AI 규칙/변환 파이프라인에 전달한다. 모델 응답만 FakeLLMClient의 사전 값을 사용한다. AWS·Bedrock·Docker를 호출하지 않으며, 앱 실행이나 원격 저장소 변경을 하지 않는다.

PR #24의 전달 제안을 참고해 진단·변환·추천·gate·미확정 비용·출처를 보존한다. Draft PR #24를 병합하거나 그 스크립트에 런타임 의존하지 않는다. 이 단계의 계약은 `service_fake_bundle_v1`이며 기존 `ai_contract.py`의 항목별 analyze/modify를 완성한 것으로 취급하지 않는다.

## 실행

1. `service/`에서 `python -m pip install -r requirements-dev.txt`. 같은 저장소의 AI/ai와 infra/adapters를 함께 설치한다. Python 3.12 이상과 Git이 필요하다.
2. `service/.env.github.local`에 `APP_AI_MODE=fake`를 설정한다. 기존 실제 GitHub 로그인 설정을 사용한다.
3. 대상 DB를 확인하고 `python -m alembic upgrade head`로 0008을 적용한다. ai_analyses 테이블만 추가하며 기존 작업은 보존한다.
4. `frontend/`에서 `pnpm build` 후 기존 서버를 재시작한다.
5. 프로젝트 상세 → **기준 커밋으로 새 분석** → 진단/보류/추천/전체 diff 확인 → 묶음 선택 → **선택한 묶음 검토 기록**.

원격 호출 없는 브라우저 검증: service/에서 `python -m tests.browser_fixture --ai` 후 http://127.0.0.1:8001/_test_only/login. 임시 DB와 샘플 코드의 GitHub HTTP 대역을 사용하는 별도 테스트 실행기다. 운영 로그인 경로에 테스트 인증을 추가하지 않는다.

## 코드 자료와 실행 경계

Service가 GitHub 권한을 요청/백그라운드 실행/검토 시 다시 확인한다. 브랜치에서 전체 40자리 SHA를 확정하고 그 커밋의 tree/blob을 읽는다. commit/tree 응답 SHA와 blob의 Git SHA-1·바이트 크기를 대조한다. GitHub 토큰은 코드 수집에만 사용한다.

요청마다 임시 코드 폴더·새 출력 폴더·새 Fake 클라이언트를 만든다. AI subprocess는 서비스 DB·GitHub 토큰·AWS 인증 환경변수를 상속하지 않는다. 실행 위치는 service/이며 사용자 코드를 import/실행하지 않는다. diff 적용 검사와 Python 문법 검사는 임시 복사본에서 수행한다. 종료 후 파일/컨텍스트를 정리하고 표시용 JSON/diff만 DB에 저장한다.

수집 상한은 tree 항목 5,000개, 대상 파일 200개, 파일당 512 KiB, 전체 5 MiB다. 저장소 루트만 지원한다. 경로 탈출·Windows 예약 이름·대소문자 충돌·심볼릭 링크·서브모듈·잘린 tree·잘못된 blob은 거부한다. .env*, 인증/가상환경/생성물 폴더, 키·DB·로그·바이너리는 제외하고 개수를 표시한다. AI 자체 ignore/스캔 제한도 적용된다. 이를 저장소 전체 검증으로 표시하지 않는다.

Windows에서는 POSIX Docker 러너 import를 지연하고 실제 Docker 게이트는 명시적으로 거부한다. 임시 소스·diff·아티팩트·git apply 입력의 UTF-8 바이트/줄바꿈을 보존한다. Windows Docker 검증 지원을 추가한 것은 아니다.

## API와 작업 기록

| API | 역할 |
| --- | --- |
| POST /api/projects/{id}/ai-analyses | {request_id: UUID}. 신규 202, 같은 ID 재전송은 기존 작업과 200 |
| GET /api/projects/{id}/ai-analyses?limit=20 | 최신 작업 요약, 최대 50개 |
| GET /api/projects/{id}/ai-analyses/{job_id} | 상태·로그·SHA·결과·diff·검토 해시 |
| POST /api/projects/{id}/ai-analyses/{job_id}/review | {review_hash, selected_bundle_ids: ["all-changes"]}로 전체 묶음 검토 기록 |

변경 요청에는 로그인 쿠키·Origin·X-CSRF-Token이 필요하다. 현재 워크스페이스 소유권을 확인한다. 로컬 경로·임의 코드·모델 선택·비밀값은 API 입력으로 받지 않는다. 프로젝트당 한 작업, 프로세스당 최대 두 작업을 실행한다. 응답 유실 시 같은 request_id로 확인하고 새 분석은 새 ID를 사용한다. 실패를 과거 캐시/성공 결과로 대체하지 않는다.

상태는 queued → running → completed/failed → reviewed다. completed는 보고서 생성 완료이며 analysis_status·transformation.status·gate를 함께 표시한다. 코드 수집은 60초 예산(진행 중 GitHub 호출 timeout 최대 20초), AI subprocess는 90초, 실행 임대는 240초다. 비정상 종료 후 작업은 **임대 만료 뒤 조회/다음 요청 시** interrupted로 바뀐다. 자동 재실행하지 않고 늦은 성공 응답으로 중단 기록을 덮어쓰지 않는다. 정상 종료 시 실행 작업이 끝날 때까지 기다린다.

새로고침/재시작 후 이력을 조회한다. 분석 중 프로젝트 삭제는 차단한다. 완료 후 프로젝트 연결을 삭제하면 분석 이력도 함께 삭제한다.

## 선택·검토 계약

진단 위반 ID는 독립 적용 가능한 diff 조각이 아니다. 첫 단계에서는 .dockerignore를 포함한 전체 diff를 단일 all-changes 묶음으로 선택한다. Dockerfile/배포 명세는 함께 보여주는 제안이며 게시/빌드하지 않는다. 항목별 선택·연관 수정·의존 관계는 A/B 후속 계약이다.

Service가 최종 diff의 크기·경로·기준 코드 적용 가능성·문법을 검사한다. 검토 해시는 저장소/브랜치·SHA/tree·코드 자료 digest·결과·diff·묶음에 묶인다. 검토 시 기준 브랜치 변경 또는 해시 불일치는 새 분석/재검토를 요구한다. reviewed는 검토 의사를 저장한 것이며 AI의 pr_eligible을 바꾸지 않는다.

화면은 fake, 현재 gate skipped/PR 승인 불가, partial/보류/위험 변경, 기존 데이터 이전 미지원, 인프라 계약/비용 확인 필요를 표시한다. 비용 null을 0으로 바꾸지 않는다. 개인 출력 경로·BuildContext·원시 컨테이너 로그를 응답에서 제외하고 알려진 소스 비밀/자격 증명 패턴을 마스킹한다. 모든 비밀 패턴의 탐지를 보장하지 않는다.

## 모드와 후속 범위

- fake: 개발용 AI 분석·전체 묶음 검토. 기존 /changes/apply 및 /changes/pr은 사용할 수 없다.
- placeholder: 기존 단일 안내 파일의 실제 GitHub Draft PR 흐름. AI 결과와 분리한다.
- unavailable: 새 분석·수정/게시 차단. 기존 분석 조회는 소유자에게 제공한다.
- 운영 환경에서는 fake/placeholder를 모두 거부한다.

/api/config.ai_available은 실제 모델 제공자가 없어 false다. ai_analysis_available과 ai_mode=fake로 연결 검증 기능을 구분한다.

Bedrock 인증/모델 연결, 항목별 modify, 다중 파일 PR 게시, 실제 빌드·배포는 후속 범위다. fake 결과를 실행 검증·자동 승인으로 사용하지 않는다.

검증: service/에서 `python -m pytest tests/test_ai_analyses.py tests/test_real_workflow.py tests/test_registration_deletion.py tests/test_aws_config_migration.py -q`. AI 줄바꿈 경계는 AI/에서 `python -m pytest ai/tests/test_windows_handoff.py -q`.

AI 전체 회귀 테스트는 Windows에서 모두 통과하지 않는다. POSIX 잠금·심볼릭 링크 권한·열린 임시 파일 교체·줄바꿈을 전제한 녹화/재시도 경로는 이번 fake/no_gate 연결의 검증 범위 밖이다. AI 개발 테스트 의존성도 별도로 설치해야 한다. 엔진 파일 변경으로 기존 demo-cache의 무결성 해시는 더 이상 일치하지 않으며, 캐시를 사용하려면 AI 담당자가 정해진 절차로 다시 생성하고 검증해야 한다. 이번 Service 경로는 해당 캐시를 사용하지 않는다. 실제 gate·녹화/재생·캐시 동작의 Linux 전체 회귀 검증은 후속으로 필요하다.

2026-10-09 Windows 검증: Service 전체 222 passed / 3 skipped(PostgreSQL 전용), 추가 AI 줄바꿈 경계 3 passed, 프런트 TypeScript/Vite 빌드 성공. 임시 DB와 GitHub HTTP 대역을 사용하는 브라우저에서 실제 Fake 파이프라인 완료 → 전체 묶음 검토 저장 → 새로고침 복원 → 두 번째 분석 → 이전 이력 선택을 확인했다. 실제 GitHub OAuth·원격 코드 수집은 별도 환경 검증이 필요하다.
