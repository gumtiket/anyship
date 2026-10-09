# AnyShip AI 연결 경계

실제 AI 제공자는 아직 연결되지 않았습니다. `/api/config`의 `ai_available`은 false이며 `ai_mode`로 임시 모드 여부를 구분합니다.

- `APP_AI_MODE=placeholder`: 개발 환경에서만 고정 수정 항목을 반환합니다. `anyship_ai_placeholder.py`에 미연결 안내 주석을 추가하며 실제 저장소의 기준 커밋을 고정합니다. 로그인·GitHub 권한·PR 생성은 실제 구현을 사용합니다.
- `APP_AI_MODE=unavailable`: 분석과 수정·게시 요청을 503으로 차단합니다. AI의 오류를 감추기 위한 자동 fallback은 없습니다.
- 운영 환경에서는 placeholder 설정을 거부합니다.

## 현재 구현

`service/app/code_changes.py`가 임시 항목과 변경 내용을 만들고 GitHub 게시를 담당합니다. `service/app/github_api.py`는 GitHub App 사용자 토큰으로 Git tree·commit·ref·Draft PR API를 호출합니다. 기존 CLI `service/github`와 별도로, 웹의 단일 파일 작업은 Git Data API를 사용합니다. 저장소를 서버에서 실행하거나 임의 명령을 수행하지 않습니다.

분석 요청 → `proposed` → 수정 내용 저장·문법 확인 → `applied` → 사용자 diff 확인 → `publishing` → `pr_created`.

`code_changes` 테이블은 기준 SHA, 기준 tree, 파일 내용·diff, 검토 해시, 작업 브랜치, 게시된 tree·commit, PR URL 및 실패 사유를 저장합니다. 검토 해시는 대상 저장소·기준 브랜치·기준 SHA·작업 브랜치·파일 내용·diff에 묶입니다. 작업 시작마다 GitHub 권한을 다시 확인합니다. 원격 작업은 단계별 체크포인트와 브랜치·PR 조회로 재시도하며, 기존 브랜치를 강제 갱신하거나 PR을 자동 병합하지 않습니다. 현재 프로젝트당 한 개의 임시 작업을 저장합니다.

## 후속 AI 개발자 계약

`service/app/ai_contract.py`에 다음 Protocol이 정의되어 있습니다. 현재 웹 경로에 실제 제공자 주입은 아직 구현되지 않았습니다.

- `analyze(AnalysisInput) -> AnalysisResult`: 프로젝트 ID, 저장소명, 기준 SHA를 받아 지원 여부·근거·수정 항목을 반환.
- `modify(ModificationInput) -> ModificationResult`: 선택 항목과 SHA를 받아 patch와 요약을 반환.
- AI 제공자에 GitHub 토큰, 클라우드 자격 증명, DB 연결을 전달하지 않음.

실제 연결 시 서버가 권한을 확인한 코드 자료를 제공하고, 반환 patch의 기준 SHA·허용 경로·크기·적용 가능 여부를 검사해야 합니다. 현재 고정 파일만 허용하는 제약을 단순 해제해 임의 patch를 게시하면 안 됩니다. 다중 항목 선택·의존 관계, 작업 이력, 비동기 워커, 격리된 빌드·테스트는 후속 구현입니다. 사용자 검토 및 게시 경계는 유지합니다.
