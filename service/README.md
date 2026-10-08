# GitHub 모듈 테스트 가이드

`github/`는 저장소 복제, 브랜치 생성, 변경 확인, 커밋·푸시, PR 생성을 담당하는 모듈입니다. `tests/github_manual.py`는 이 기능들을 연결해 실제 GitHub 저장소에서 실행하는 수동 테스트입니다.

자동 테스트부터 실행한 뒤, 수동 테스트의 `prepare`로 작업 폴더를 준비하고 직접 파일을 수정합니다. 마지막으로 `publish`를 실행하면 변경 사항을 커밋·푸시합니다. HTTP 서버를 실행할 필요는 없습니다.

## 1. 실행 환경 준비

Python 3.12와 Git을 사용할 수 있는 환경을 기준으로 합니다. 아래 명령은 Windows PowerShell용이며, 프로젝트를 받은 위치에서 `service` 디렉터리로 이동해 실행합니다.

```powershell
cd .\service
python --version
git --version
```

가상환경이 없는 경우에만 생성합니다. `python`은 설치한 Python 3.12 실행 파일을 가리켜야 합니다.

```powershell
python -m venv .venv
```

새 환경에는 개발·테스트 의존성을 설치합니다. 이미 설치된 환경이면 생략할 수 있습니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

가상환경에 `pip`가 없으면 다음을 먼저 실행합니다. `ensurepip`도 지원하지 않는 배포판이라면 표준 Python 설치로 별도 가상환경을 준비하세요.

```powershell
.\.venv\Scripts\python.exe -m ensurepip --upgrade
```

`requirements.txt`는 모듈 실행 의존성이고, `requirements-dev.txt`는 자동·수동 테스트 의존성을 포함합니다. 아래에서는 가상환경 활성화 없이 Python 경로를 직접 지정합니다.

## 2. 자동 테스트

자동 테스트에는 GitHub 토큰이나 `.env`가 필요하지 않습니다. GitHub 호출과 원격 푸시는 모의 처리하고, 일부 테스트는 임시 로컬 Git 저장소에서 실제 커밋을 검증합니다.

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

현재 테스트 구성은 47개입니다. 특정 기능만 확인하려면 파일을 지정합니다.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_repository.py -v
.\.venv\Scripts\python.exe -m pytest tests/test_changes.py -v
.\.venv\Scripts\python.exe -m pytest tests/test_pull_request.py -v
```

`test_manual_*.py`도 모의 호출을 사용하는 자동 테스트입니다. `github_manual.py`는 일반 `pytest` 실행으로 실제 GitHub 작업을 시작하지 않습니다.

## 3. 수동 테스트용 GitHub 토큰 발급

본인에게 쓰기 권한이 있는 테스트 저장소를 준비합니다.

1. [GitHub Fine-grained tokens](https://github.com/settings/personal-access-tokens)에서 **Generate new token**을 선택합니다.
2. 이름과 만료 기간을 설정합니다.
3. **Resource owner**에서 저장소 소유 계정 또는 조직을 선택합니다.
4. **Repository access → Only select repositories**에서 테스트 저장소를 선택합니다.
5. **Repository permissions**에 아래 권한을 추가합니다.
6. **Generate token**을 누르고 발급된 값을 복사합니다. 기존 토큰의 권한을 수정하는 경우에는 **Update**로 저장합니다.

| 저장소 권한 | 설정 | 용도 |
| --- | --- | --- |
| Contents | Read and write | 복제·코드 푸시 |
| Pull requests | Read and write | Draft PR 생성 |
| Metadata | Read-only | 저장소 정보 조회 |

**Account permissions** 메뉴가 열렸다면 닫고 저장소 선택과 **Repository permissions**를 확인하세요. 이 테스트에 계정 권한을 추가할 필요는 없습니다. 조직 정책에 따라 토큰 사용 승인이 필요할 수 있습니다.

발급 절차와 조직 정책은 [GitHub 공식 토큰 안내](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)를 참고하세요. 위 권한은 일반 파일 수정 기준이며, Actions 워크플로 파일 수정 등은 추가 권한이 필요할 수 있습니다.

## 4. 로컬 토큰 설정

기존 설정을 덮어쓰지 않도록 `.env`가 없을 때만 복사합니다.

```powershell
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
}
notepad .env
```

다음 값을 실제 토큰과 저장소명으로 바꾸고 저장합니다.

```dotenv
GITHUB_TOKEN=발급받은_실제_토큰
GITHUB_ALLOWED_REPO=owner/repo
```

`GITHUB_ALLOWED_REPO`에는 URL 대신 `소유자/저장소명`을 입력합니다. 토큰은 `.env`에만 저장하고 `.env.example`, 코드, 커밋, 채팅에 넣지 않습니다. `.env`는 Git 추적에서 제외됩니다.

수동 테스트는 `service/.env`를 읽습니다. 같은 이름의 환경변수가 이미 설정되어 있으면 환경변수가 우선합니다. 이 허용 저장소 제한과 설정 로드는 테스트 실행 로직에 속하며, 개별 `github/` 함수는 호출자가 전달한 값을 사용합니다.

## 5. 작업 폴더 준비

아래 예시의 `owner/repo`를 설정한 저장소명으로 바꿉니다.

```powershell
$repoUrl = "https://github.com/owner/repo"
$repoDirectory = ".\workspaces\repo"
$workBranch = "work/manual-test"

.\.venv\Scripts\python.exe -m tests.github_manual prepare $repoUrl $repoDirectory --branch $workBranch
```

새 경로이면 기본 브랜치를 복제하고 작업 브랜치를 생성합니다. 처음 실행할 때 대상 폴더를 미리 만들 필요는 없습니다. 성공하면 `prepared`, 작업 폴더, 브랜치가 출력됩니다. 이 단계에서는 푸시하지 않습니다.

- 상대 경로는 현재 디렉터리를 기준으로 해석합니다. 절대 경로도 지정할 수 있습니다.
- `--branch`를 생략하면 `ai/manual-...` 이름을 생성합니다.
- 기존 경로는 Git 저장소 최상위 경로, 원격 URL, 작업 브랜치를 확인한 후 재사용합니다.
- 기존의 빈 폴더나 다른 저장소를 덮어쓰지 않습니다. 다른 브랜치를 요청해도 자동 전환하지 않습니다.
- 기존 저장소를 재사용할 때 자동으로 fetch·pull하여 최신화하지 않습니다.

`service/workspaces/`는 Git 추적에서 제외됩니다. 작업 폴더는 실행 후에도 유지됩니다.

## 6. 텍스트 수정과 코드 추가

복제한 작업 폴더 안에서 편집기로 파일을 수정합니다. 예를 들어 `README.md` 문구를 변경하고 `src/`에 코드 파일을 추가할 수 있습니다. 수동 테스트는 데모 파일을 자동 작성하지 않습니다.

변경 사항을 검토합니다.

```powershell
git -C $repoDirectory status --short
git -C $repoDirectory diff
git -C $repoDirectory diff --cached
```

새 미추적 파일의 내용은 `diff`에 나오지 않으므로 편집기에서도 확인합니다. 대상 프로젝트의 테스트가 있다면 수정한 코드에 맞게 별도로 실행합니다.

## 7. 커밋과 푸시

브랜치만 푸시하려면 다음 명령을 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m tests.github_manual publish $repoUrl $repoDirectory
```

Draft PR도 만들려면 위 명령 대신 다음을 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m tests.github_manual publish $repoUrl $repoDirectory --pr
```

**이 단계는 실제 GitHub를 변경합니다.** Git이 무시하지 않는 수정·추가·삭제 사항 전체를 스테이징하고, 변경이 있으면 커밋한 뒤 작업 브랜치를 푸시합니다. 변경이 없어도 기존 커밋을 푸시하므로 푸시 실패 후 재시도할 수 있습니다.

현재 커밋 작성자는 `Team Bronze Bot`, 이메일은 `team-bronze-bot@example.com`, 메시지는 `chore: apply automated code changes`로 고정되어 있습니다. 작성자 설정은 대상 로컬 저장소에 적용됩니다.

| 결과 상태 | 의미 |
| --- | --- |
| prepared | 작업 폴더·브랜치 준비 완료 |
| pushed | 브랜치 푸시 완료 |
| created | 푸시 및 Draft PR 생성 완료 |

PR은 기본 브랜치를 대상으로 생성되며 자동 병합하지 않습니다. 출력된 URL에서 수정 내용과 새 코드가 포함되었는지 확인합니다.

## 8. 이어서 수정하기

같은 작업 폴더를 다시 수정하고 `publish`를 실행합니다. 이미 PR이 있다면 `--pr` 없이 실행하세요. 같은 브랜치의 기존 PR에 변경이 반영됩니다.

```powershell
.\.venv\Scripts\python.exe -m tests.github_manual publish $repoUrl $repoDirectory
```

`--pr`은 새 PR 생성 요청이며, 기존 PR을 조회해서 재사용하는 기능은 없습니다. 새로운 작업을 시작하려면 다른 작업 폴더와 새 브랜치로 `prepare`를 실행할 수 있습니다.

## 9. JSON 출력과 도움말

실행할 명령 뒤에 `--json`을 붙이면 정상 결과는 표준 출력으로, 오류는 표준 오류로 JSON을 출력합니다. 인자 파싱 오류와 도움말은 일반 텍스트로 출력됩니다.

```powershell
.\.venv\Scripts\python.exe -m tests.github_manual prepare $repoUrl $repoDirectory --json
.\.venv\Scripts\python.exe -m tests.github_manual prepare --help
.\.venv\Scripts\python.exe -m tests.github_manual publish --help
```

`publish`에도 `--json`을 사용할 수 있으며 실제 푸시 동작은 동일합니다.

## 10. 실패 시 확인 사항

명령 실행 직후 종료 코드를 확인합니다.

```powershell
$LASTEXITCODE
```

| 코드 | 의미 | 확인할 사항 |
| --- | --- | --- |
| 0 | 정상 완료 | 출력된 상태·브랜치·PR URL 확인 |
| 1 | Git·네트워크·파일 작업 실패 | Git 설치, 토큰 만료·권한·조직 승인, 네트워크, 원격 브랜치 규칙 확인 |
| 2 | 설정·입력·작업 폴더 검증 실패 | `.env`, 허용 저장소, URL, 작업 경로, 브랜치 확인 |
| 3 | 푸시 후 PR 생성 결과 확인 실패 | GitHub에 PR이 이미 생성됐는지 확인한 뒤 재시도 |
| 130 | 사용자 중단 | 로컬 커밋과 GitHub 상태 확인 |

작업 경로는 저장소 최상위 디렉터리여야 하며, `origin`의 가져오기·푸시 URL은 요청한 GitHub HTTPS 저장소와 일치해야 합니다. SSH URL, 기본 브랜치, 브랜치가 선택되지 않은 detached HEAD 상태는 지원하지 않습니다.

푸시가 실패해도 로컬 커밋과 작업 폴더는 유지됩니다. 원인을 해결한 뒤 같은 경로에서 `publish`를 다시 실행하세요. PR 결과가 불명확한 경우 먼저 GitHub를 확인하고, 이미 PR이 있으면 `--pr`을 빼고 진행합니다. 원격과 이력이 충돌하면 상태를 검토해 해결해야 하며, 테스트 도구는 강제 푸시나 자동 병합을 수행하지 않습니다.
