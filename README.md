# AnyShip

GitHub 저장소 URL을 연결하고, 코드 변경을 검토한 뒤 실제 GitHub Draft PR로 제출하는 웹 서비스입니다.

- GitHub 로그인·가입 → 개인 워크스페이스 → 저장소 URL·기준 브랜치 등록
- 분석 요청 → 수정 항목 선택 → 수정 내용 저장·diff 검토 → GitHub 브랜치·커밋·Draft PR 생성
- 현재 AI는 미연결입니다. 개발용 `APP_AI_MODE=placeholder`에서는 AI 대신 안내 주석 파일을 추가하는 고정 항목을 반환합니다. 로그인·저장소·PR은 실제 GitHub를 사용합니다.
- 실제 AI 분석·수정 제공자, 프로젝트 실행 검증, AWS·온프레미스 배포는 후속 범위입니다.

## 시작하기

- [로컬 실행 및 GitHub App 설정](docs/LOCAL_DEVELOPMENT.md)
- [AI 개발자 연결 계약](docs/AI_INTEGRATION.md)
- [기존 GitHub 모듈 사용법](service/README.md)

`./scripts/start-local.ps1`로 실행합니다. GitHub App 설정이 없으면 설정 대기 화면이 표시됩니다. 샘플 계정으로 실제 연결을 대신하지 않습니다. 상세 설정은 위 로컬 실행 안내를 따르세요.
