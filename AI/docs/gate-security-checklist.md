# P4 샘플 검증 게이트 보안·운영 확인

이 게이트는 소스 해시로 확인한 두 자체 샘플의 임시 변환본만 실행한다. 일반 사용자 앱에는 컨테이너 빌드·기동·DB 전환을 적용하지 않고 skipped를 반환한다. 변환/원본 BuildContext의 봉인 해시가 달라져도 실행하지 않는다. Python 호출자는 이 내부 객체를 사용자 입력으로 직접 구성하지 않는다.

## 실행 인자

- 모든 app·Postgres·migration·pg_isready·curl 실행에 read-only, /tmp tmpfs(noexec/nosuid, 512MB), cap-drop ALL, no-new-privileges, 비루트 UID/GID, memory 512m, cpus 1, pids-limit 128을 강제한다.
- 앱·curl·migration은 UID/GID 10001, postgres:16-alpine은 UID/GID 70을 명시한다. 이미지의 USER만 믿지 않는다.
- Postgres 데이터는 /tmp/pgdata만 사용한다. 공식 이미지의 초기화 psql이 기본 소켓 경로를 사용하므로 DB 이미지에만 /var/run/postgresql tmpfs(16MB, UID/GID 70)를 추가한다. 앱에는 이 예외를 주지 않는다.
- 네트워크는 러너가 --internal로 만든 고유 네트워크만 허용한다. 호스트 네트워크, privileged, publish, 호스트 경로/소켓 마운트, env-file, 추가 entrypoint 등은 거부한다.
- validate_run_args는 알 수 없는 옵션, 중복 옵션으로 제한을 덮어쓰는 시도, 허용되지 않은 tmpfs 경로·이미지·환경변수도 실행 전에 거부한다.
- 앱 환경은 PORT/LOG_LEVEL/더미 SECRET_KEY/임시 DATABASE_URL만 생성한다. DB 환경은 별도 허용 목록의 POSTGRES_USER/DB/PASSWORD/PGDATA만 생성한다. 서비스의 os.environ을 컨테이너에 복사하지 않는다. 실제 사용자 시크릿은 주입하지 않는다.
- build-arg·커밋 SHA·빌드 시각·랜덤 값은 이미지 내용에 넣지 않는다. 외부 이미지 태그는 임시 코드 트리의 내용 해시이고 실행 이름/임시 암호만 랜덤이다.

## 검증 범위

- 이미지 빌드, DB 준비, 빈 임시 DB의 create_all, healthz, 할 일 생성·조회·앱 재기동 후 조회·수정·수정 조회·삭제·삭제 조회를 확인한다.
- 원본 복사본은 별도 DB 없이 같은 읽기 전용 조건에서 시작하며, 시작 로그의 Read-only file system / unable to open database file / PermissionError / OSError: [Errno 30]을 기록한다.
- 런타임 DB·로그 파일은 RepoView에서 읽지 않고 BuildContext에도 넣지 않는다. 원본 레포와 SQLite 데이터는 변경하지 않는다. 기존 데이터 이전은 미지원이다.
- 파일 내보내기 저장 방식과 의존성 버전 고정은 여전히 보류다. sample_startup_and_postgres_crud 범위의 passed를 모든 기능·12-factor 완전 준수·운영 배포 가능 판정으로 사용하지 않는다. pr_eligible은 false이고 risky 변경 승인이 별도로 필요하다.
- FakeRunner는 단계/인자 검사이며 status=skipped다. 실제 Docker 통과와 혼동하지 않는다. 기본 pytest에는 Docker/AWS 연결이 필요 없다.

## 정리와 서비스 서버 이전

- try/finally에서 이 실행이 만든 컨테이너, 익명 볼륨, 네트워크, 임시 이미지 태그를 정리한다. 정리 오류가 있으면 passed를 유지하지 않고 failed로 보고한다. Docker 전체 prune는 사용하지 않는다.
- 같은 코드 해시의 동시 실행은 로컬 파일 잠금으로 충돌을 거부한다. 이미 존재하는 이미지 태그는 덮어쓰거나 제거하지 않는다. 파일 잠금은 동일 Docker 호스트를 사용하는 다른 서비스 머신까지 분산 잠금을 제공하지 않는다.
- 로그는 마지막 200줄/20KB로 제한하고 임시 암호·DB URL·계정 ID를 마스킹한다. 계정별 IAM 정책과 out 결과는 공용 Git 업로드에서 제외한다.
- Docker daemon 접근은 호스트 권한이다. 빌드에는 패키지 다운로드가 필요하며 실행 네트워크의 internal 설정은 완전한 VM 격리 증명이 아니다. 임의 사용자 코드를 실행하는 보안 경계로 확대하지 않는다.
- macOS Docker Desktop은 Linux VM에서 실행한다. 이번 Mac의 arm64 결과를 EC2 x86 이미지 검증으로 간주하지 않는다. 서비스 배포 대상의 플랫폼을 지정한 실제 이미지로 다시 검증한다. Lambda용 manifest 형식도 C가 확인해야 한다.
- 서비스 서버에는 Docker daemon/CLI, helper 이미지 사전 pull, POSIX 파일 잠금(fcntl), 빌드 다운로드 권한, 작업 시간 제한이 필요하다. HTTP/SSE 요청 처리 스레드와 분리해 실행한다. B의 HTTP 서버는 만들지 않는다.

리뷰 시에는 새 옵션이 allowlist를 우회하지 않는지, cleanup 대상이 자기 소유인지, 외부 DB/시크릿이 섞이지 않는지, 샘플 제한이 유지되는지, passed의 범위가 화면/PR 경로에 정확히 전달되는지 확인한다.
