# AnyShip

GitHub 저장소 URL을 연결하고, 코드 변경을 검토한 뒤 실제 GitHub Draft PR로 제출하는 웹 서비스입니다.

- GitHub 로그인·가입 → 개인 워크스페이스 → 저장소 URL·기준 브랜치 등록
- 분석 요청 → 수정 항목 선택 → 수정 내용 저장·diff 검토 → GitHub 브랜치·커밋·Draft PR 생성
- 개발용 `APP_AI_MODE=fake`로 기준 SHA의 코드를 AI 분석기에 전달하고 진단·전체 수정안을 검토할 수 있습니다. 모델 응답은 사전 값이며 앱 실행·PR 게시·배포는 수행하지 않습니다. 기존 `placeholder` 모드는 안내 파일의 실제 GitHub PR 흐름을 제공합니다.
- FastAPI·SQLAlchemy·PostgreSQL로 사용자, 프로젝트와 수정 작업을 저장합니다. 로컬에서는 Uvicorn과 PostgreSQL을 직접 실행합니다.
- 실제 모델(Bedrock), 항목별 수정·다중 파일 PR 게시, 프로젝트 실행 검증, AWS·온프레미스 배포는 후속 범위입니다.

## 시작하기

- [로컬 실행 및 GitHub App 설정](docs/LOCAL_DEVELOPMENT.md)
- [AI 개발자 연결 계약](docs/AI_INTEGRATION.md)
- [기존 GitHub 모듈 사용법](service/README.md)

`./scripts/start-local.ps1`로 실행합니다. GitHub App 설정이 없으면 설정 대기 화면이 표시됩니다. 샘플 계정으로 실제 연결을 대신하지 않습니다. 상세 설정은 위 로컬 실행 안내를 따르세요.
