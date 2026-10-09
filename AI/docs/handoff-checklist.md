# AI 모듈 인수인계 체크리스트

## 파일과 경로

- [ ] 실행 필수 `ai/`·`samples/`를 팀 저장소 `AI/` 아래 나란히 둔다. 필수 테스트·LLM fixtures·골든·demo-cache는 ai 안에 포함한다.
- [ ] 전달 문서 docs/reference도 함께 복사하되 실행 코드가 이 문서 경로나 개인 프로젝트 절대 경로에 의존하지 않는다.
- [ ] 개인 IAM 정책, 인증 정보, out/실행 트레이스/문의 문안, DB·로그·캐시·가상환경·기존 개인 Git 이력은 제외한다. 명시적인 `ai/demo-cache/<sample>/out`은 검토된 사전 결과 데이터로 별도 취급한다.
- [ ] memo-app은 미지원 테스트 픽스처로만 유지하고 샘플 원본을 수정하지 않는다.
- [ ] 복사본의 새 Python 3.12 환경에서 실제 import 위치가 복사본 아래인지 확인한다.

## 의존성과 CI

- [ ] `ai/requirements-dev.lock`은 현재 검증한 개발 버전 스냅샷이다. 서비스 서버 OS/아키텍처에서도 설치·검증한다. 입력 앱 의존성 버전을 추측해서 고정하지 않는다.
- [ ] 기본 CI는 아래 오프라인 명령만 실행하며 AWS/Docker 호출을 허용하지 않는다.

```sh
cd AI
python3.12 -m venv ai/.venv
ai/.venv/bin/python -m pip install -e 'ai[dev]' -c ai/requirements-dev.lock
ai/.venv/bin/python -m pytest ai/tests -q
ai/.venv/bin/ruff check ai
ai/.venv/bin/ruff format --check ai
```

- [ ] 실제 Bedrock/Docker 테스트는 수동 `-m bedrock`/`-m docker`로 별도 선택한다. 단가가 null이면 청구 총액을 주장하지 않는다.
- [ ] Python/pydantic/프롬프트/스키마 변경으로 replay 해시가 깨지면 의도한 변경을 검토한 후 refresh_golden.py로 재기록한다. 기준을 자동으로 덮어쓰지 않는다.

## 서비스와 인프라 경계

- [ ] integration-for-service.md의 로그·종료 코드·BuildContext 정리를 연결한다.
- [ ] source/commit/허용 경로/크기/diff 적용 검증과 사용자 검토·게시 경계는 A가 유지한다. B 제공자 추가만으로 웹 AI 연결 완료를 표시하지 않는다.
- [ ] 캐시/replay 표시와 과거 사용량을 UI에 명시한다. 캐시의 현재 게이트는 skipped이며 pr_eligible=false다.
- [ ] C의 명세/tfvars/단가/대상 플랫폼을 확정하고 p5-infra-confirmation-checklist.md를 확인한다.
- [ ] 실제 배포할 이미지로 검증한다. 이미지 재빌드 동일성, 전체 기능·부하, 운영 마이그레이션/롤백/데이터 이전을 샘플 기동·CRUD 검증으로 대신하지 않는다.

골든은 고정 샘플 회귀다. 독립 holdout 성능, 모든 시크릿의 마스킹, 실제 STRONG 수정안 품질, 운영 배포 완료의 증거가 아니다.


## 독립 검토 후 추가 확인

- [ ] 요청마다 새 out·새 클라이언트, 현재 결과/예외와 오래된 파일을 구분한다.
- [ ] diff의 .dockerignore를 PR/실제 빌드에 포함하고 원래 패턴도 보존한다.
- [ ] 사용자 제공 비밀과 시스템 생성 SECRET_KEY를 구분하고 생성 값은 다음 배포에서 재사용한다.
- [ ] 기존 DATABASE_URL은 자원/주소를 추측 생성하지 않고 사용자에게 확인한다.
- [ ] ENV 거부 목록/예약어·최종 UTF-8 4KB·30초 경계를 C와 확인한다.
- [ ] pyproject 분석과 실제 패키징 지원을 구분하고 partial을 완료로 표시하지 않는다.
- [ ] replay+새 Docker 캐시는 llm_execution_source와 recorded_llm_usage를 보이고 실제 신규 LLM 성공으로 표시하지 않는다.
- [ ] 원래 비용 null, 현재 외부 호출 0, 과거 Docker passed와 현재 gate skipped를 구분한다.
