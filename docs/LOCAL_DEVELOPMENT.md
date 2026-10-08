# AnyShip 로컬 실행 및 실제 GitHub 테스트

AnyShip은 GitHub 로그인 → 저장소 URL 등록 → 수정 항목 등록·실행 → diff 검토 → 실제 GitHub Draft PR 생성을 제공합니다. 현재 AI만 임시 구현입니다. `APP_AI_MODE=placeholder`로 실행하면 `anyship_ai_placeholder.py`에 AI 미연결 안내 주석을 추가합니다. 가짜 로그인·저장소·PR로 대체하지 않습니다.

## 이 PC에서 실행

의존성과 화면 빌드가 준비되어 있다면 저장소 루트에서 실행합니다.

```powershell
.\scripts\start-local.ps1
```

[AnyShip 열기](http://localhost:8000). 서버 종료는 실행한 터미널에서 Ctrl+C입니다. 이미 8000번 포트를 사용 중인 서버는 먼저 종료해야 합니다. 스크립트가 다른 프로세스를 임의로 종료하지 않습니다.

PowerShell 실행이 제한되어 있다면 같은 작업을 Python으로 실행합니다.

```powershell
.\service\.venv\Scripts\python.exe scripts/local_web.py
```

스크립트는 `service/.env.github.local`이 없으면 생성하고, 토큰 암호화 키가 비어 있으면 출력 없이 저장합니다. 기존 값은 보존합니다. DB 마이그레이션 후 127.0.0.1:8000으로 서버를 실행합니다. GitHub 설정이 없으면 연결 대기 화면을 표시합니다. `-CheckOnly` 또는 `--check`로 준비 상태만 확인할 수 있습니다.

## GitHub App 설정 — 서비스 운영자가 한 번 진행

1. [GitHub App 생성](https://github.com/settings/apps/new)을 엽니다. 표시 이름은 AnyShip을 사용하되 GitHub에서 이름이 이미 사용 중이면 사용 가능한 이름을 지정합니다. 서비스 UI 이름은 AnyShip으로 유지됩니다.
2. Homepage URL은 `http://localhost:8000`, **Redirect URI**(문서에서 Callback URL이라고도 부름)는 `http://localhost:8000/api/auth/github/callback`, Setup URL은 `http://localhost:8000/`로 설정합니다. **Redirect on update**도 켜면 기존 설치의 저장소 접근 범위를 변경한 뒤 AnyShip으로 돌아옵니다. `localhost`와 `127.0.0.1`을 혼용하지 마세요.
3. 사용자 액세스 토큰 만료 기능은 유지합니다. **Request user authorization (OAuth) during installation**은 해제합니다. 서비스 로그인 버튼으로 별도 인증합니다. 이 MVP는 웹훅을 사용하지 않으므로 **Active webhook**도 해제합니다.
4. Repository permissions에서 **Contents: Read and write**, **Pull requests: Read and write**를 설정합니다. Metadata 읽기는 기본 권한입니다. 외부 사용자도 설치할 수 있도록 설치 대상을 **Any account**로 설정합니다.
5. 생성 후 Client ID를 확인하고 Client secret을 생성합니다. 공개 App 페이지의 URL `https://github.com/apps/앱이름` 마지막 부분이 App slug입니다. GitHub가 설치 전에 private key 생성을 요구하면 **Private keys → Generate a private key**로 생성해 내려받은 파일을 안전하게 보관합니다. 현재 AnyShip 서버는 사용자 토큰 방식이므로 이 private key를 설정에 입력하거나 사용하지 않습니다.
6. `service/.env.github.local`의 다음 세 값을 로컬 편집기로 입력합니다. 비밀키를 채팅이나 저장소에 올리지 마세요.

```dotenv
APP_GITHUB_CLIENT_ID=실제_Client_ID
APP_GITHUB_CLIENT_SECRET=실제_Client_secret
APP_GITHUB_APP_SLUG=실제_App_slug
```

7. 서버를 재시작하고 페이지를 새로고침합니다. 일반 이용자는 App을 생성하거나 시크릿을 입력하지 않습니다. **GitHub로 시작하기**로 가입·로그인하고 저장소 주소를 입력하면, 필요한 경우에만 접근 승인 버튼이 표시됩니다. 기존 App의 읽기 권한을 쓰기 권한으로 변경했다면 설치 설정에서도 새 권한을 승인해야 합니다. 운영자 설정은 이 문서에서 관리하며 공개 로그인 화면에 노출하지 않습니다.

참고: [GitHub App 사용자 인증](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app), [Git tree 생성](https://docs.github.com/en/rest/git/trees#create-a-tree), [PR 생성 권한](https://docs.github.com/en/rest/pulls/pulls#create-a-pull-request).

## 직접 테스트할 순서

1. 커밋이 하나 이상 있는 본인의 GitHub 테스트 저장소를 준비합니다. 예: README가 있는 저장소. 계정에는 저장소 쓰기 권한이 있어야 합니다.
2. AnyShip에서 **GitHub로 시작하기**를 눌러 로그인합니다.
3. **저장소 연결**에서 `https://github.com/소유자/저장소` URL을 입력하고 **저장소 확인**을 누릅니다. 접근이 필요하면 **GitHub에서 접근 승인**을 눌러 GitHub에서 계정과 해당 저장소를 선택합니다. 모든 저장소를 허용할 필요는 없습니다. 승인 후 AnyShip으로 돌아오면 저장한 주소로 접근을 다시 확인합니다. 조직 승인 대기 또는 자동 복귀가 없는 경우 AnyShip을 다시 열고 **접근 권한 다시 확인**을 누르세요.
4. 접근 확인 후 기준 브랜치를 선택하고 **프로젝트 연결**을 누릅니다. 이미 등록했다면 **프로젝트 열기**로 이동합니다.
5. **분석 요청 · 임시 모드**를 누릅니다. 서버가 실제 기준 커밋을 확인하고 AI 미연결 안내 파일 추가 항목을 저장합니다.
6. 항목을 체크하고 **선택한 수정 실행**을 누릅니다. 새 파일의 내용과 diff가 DB에 저장되며 Python 문법을 확인합니다. 이 단계에서는 GitHub 원격 쓰기를 수행하지 않습니다.
7. diff를 읽고 확인 체크박스를 선택한 뒤 **GitHub Draft PR 생성**을 누릅니다. 실제 GitHub에 `anyship/ai-placeholder-...` 브랜치·커밋·Draft PR이 만들어집니다. **GitHub에서 PR 보기**로 실제 PR을 확인합니다.
8. GitHub에서 변경 파일과 기존 파일 보존을 확인합니다. 원본 브랜치에 자동 병합하지 않습니다. 테스트 파일이므로 병합 여부는 직접 결정하세요.

실제 AI 분석 결과는 생성하지 않으며 프로젝트 빌드·테스트도 실행하지 않습니다. 임시 파일과 동일한 경로가 이미 있으면 덮어쓰지 않고 중단합니다. 한 프로젝트에는 현재 한 개의 임시 수정 작업을 저장합니다. PR 생성 전에는 **최신 코드로 다시 요청**으로 검토를 초기화할 수 있습니다. PR 생성 후에는 기존 PR을 표시합니다.

## 실패와 재시도

- 연결 중인 URL은 사용자·워크스페이스별로 24시간 유지됩니다. 새로고침, GitHub에서 복귀, 같은 계정으로 재로그인 후에도 이어갈 수 있습니다. 승인 요청 state는 해시로 저장하고 1시간 뒤 만료되며, 사용자 일치와 일회성 소비를 검증합니다. GitHub가 반환한 installation_id는 접근 권한의 증거로 사용하지 않습니다. 프로젝트 등록 때에도 권한을 다시 확인합니다.
- 저장소 쓰기 권한 없음, 보관됨, 접근 중지, App 권한 부족, 빈 저장소는 별도로 안내합니다. GitHub가 숨기는 비공개 저장소는 실제로 존재하지 않는 저장소와 구분할 수 없으므로 주소 확인과 접근 승인을 함께 안내합니다.
- 프로젝트 화면 주소와 연결 화면 주소를 유지하므로 새로고침·뒤로 가기가 가능합니다. **입력 초기화**는 해당 사용자의 연결 초안만 지웁니다. 프로젝트나 GitHub 설치는 삭제하지 않습니다.
- 기준 브랜치가 바뀌면 **최신 코드로 다시 요청** 후 새 diff를 검토합니다. 이전 시도에서 생성된 GitHub 브랜치를 자동 삭제하지 않습니다.
- PR 생성이 실패하면 원인을 확인하고 같은 작업에서 다시 요청합니다. 저장된 커밋, 원격 브랜치와 PR을 확인해 중복 생성을 방지합니다.
- 서버가 중간에 종료되면 진행 중 표시가 최대 10분간 남을 수 있습니다. 작업 잠금이 만료되면 재시도할 수 있습니다.
- 인증 만료 시 다시 로그인합니다. 저장된 프로젝트와 작업 기록은 유지됩니다.
- App의 Contents/Pull requests 쓰기 권한, 설치 대상 저장소, 사용자 쓰기 권한, 조직 정책·브랜치 규칙을 확인합니다. 서비스는 GitHub의 규칙을 우회하지 않습니다.

## 설정과 새 개발 환경

```dotenv
APP_ENV=development
APP_DEMO=false
APP_AI_MODE=placeholder
APP_APP_ORIGIN=http://localhost:8000
APP_DATABASE_URL=sqlite:///./anyship-local.db
# APP_TOKEN_KEY는 실행 스크립트가 생성합니다. 기존 키를 교체하면 재로그인이 필요합니다.
```

`APP_AI_MODE=unavailable`이면 AI 작업을 차단합니다. 실제 AI 제공자가 구현되기 전에는 운영 환경에서 임시 분석 기능을 사용할 수 없습니다. 이전 데모 DB와 실제 GitHub DB는 분리하여 기존 샘플 계정이 실제 작업에 사용되지 않게 합니다. 예전 `-Mode demo` 실행은 지원하지 않으며 기본 실행은 GitHub 모드입니다. 이전 데이터 보존을 위해 데모 테이블과 격리된 레거시 API는 남아 있지만 AnyShip 화면에서는 사용하지 않습니다.

Python 3.12 이상, Node.js 22 이상과 pnpm을 준비한 새 환경에서는 다음을 실행합니다.

```powershell
cd service
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[web,test]"
cd ..\frontend
pnpm install --frozen-lockfile
pnpm build
cd ..
.\scripts\start-local.ps1
```

화면 개발 시 `frontend`에서 `pnpm dev`를 실행하면 Vite가 `/api`를 백엔드로 전달합니다. 이 경우 origin과 GitHub 콜백 URL을 모두 `http://localhost:5173` 기준으로 바꾸고, 아래 수동 API 실행을 사용합니다. 실행 스크립트는 8000번 기준입니다.

```powershell
cd service
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

## 검증과 현재 한계

```powershell
cd service
.\.venv\Scripts\python.exe -m pytest tests -q
cd ..\frontend
pnpm build
```

HTTP 응답 대역을 사용하는 자동 테스트가 실제 GitHub 어댑터의 요청 형식, 기존 파일 보존, 사용자 격리, CSRF, 권한 회수, 검토 해시, 기준 커밋 변경, 중복 PR 방지와 실패 복구를 검증합니다. 자동 테스트는 실제 GitHub를 변경하지 않습니다. 실제 OAuth와 GitHub PR 검증은 위 App 설정 후 직접 진행해야 합니다.

브라우저에서 승인 전후를 외부 변경 없이 검증하려면 `service`에서 `.\.venv\Scripts\python.exe -m tests.browser_fixture --onboarding`을 실행하고 `http://127.0.0.1:8001/_test_only/login`을 엽니다. 테스트 저장소 주소는 `https://github.com/owner/real-repo`입니다. 승인 버튼은 명시적인 테스트 전용 화면을 거쳐 복귀하며 실제 GitHub는 변경하지 않습니다. 이 도우미는 임시 DB와 별도 포트만 사용하고 운영 앱이나 실행 스크립트에 포함되지 않습니다. 실제 서비스의 localhost 로그인 쿠키와 분리하기 위해 테스트 브라우저 주소는 127.0.0.1을 사용합니다.

로컬 실행 가능한 MVP이며 공개 운영 배포 완료 상태는 아닙니다. 운영은 HTTPS·PostgreSQL·실제 App 설정을 요구합니다. 외부 공개 전에는 도메인·호스팅, PostgreSQL 실제 검증, 요청 한도, 탈퇴·보관 정책, 설치 해제 웹훅과 운영 시크릿 관리가 필요합니다. 브라우저에는 HttpOnly/SameSite 세션 쿠키만 저장하고 서버 DB에는 해시된 세션 ID와 암호화된 GitHub 토큰을 저장합니다. 토큰은 최대 8시간 세션 내에서 사용하며 만료 시 재로그인합니다. OAuth 콜백 쿼리 문자열은 로그에 남기지 않아야 합니다.
