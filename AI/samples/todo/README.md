# todo — 의도적 위반이 있는 FastAPI 샘플

FastAPI + SQLAlchemy + SQLite로 실행하는 할 일 CRUD 앱이다. B의 HTTP 분석 서버가 아니라 **배포 대상**이다.
스케줄러는 없다. 목표 세트는 serverless다(실제 추천 구현은 P5).

## 안전한 로컬 실행

프로젝트 루트에서 의존성을 설치한 뒤 임시 복사본을 실행한다. 원본 코드/DB에 쓰지 않는다.

```sh
ai/.venv/bin/python -m pip install -e 'ai[dev,samples]'
project_dir="$PWD"
sample_dir=$(mktemp -d)
cp -R samples/todo/. "$sample_dir/"
cd "$sample_dir"
"$project_dir/ai/.venv/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

브라우저에서 로컬 8000 포트에 접속한다. 두 샘플은 각각 별도 복사본·별도 실행으로 사용한다.
종료는 Ctrl+C. 자동 검증은 프로젝트 루트에서 `ai/.venv/bin/python ai/scripts/smoke_samples.py`를 실행한다. 이 스크립트는 복사·기동·HTTP CRUD·정리까지 수행한다.

## 기능

- `/`: 단일 HTML UI, 추가/완료 변경/삭제/내보내기.
- `GET /todos`, `POST /todos`, `PUT /todos/{id}`, `DELETE /todos/{id}`.
- `POST /export`: `./data/todos.json`에 저장한다(의도한 영속 파일 위반).
- 시작 시 빈 DB에 데모 할 일 2개를 넣는다. 재시작 때 중복으로 넣지 않는다.
- 마감 입력의 timezone은 UTC로 정규화하고 DB에는 UTC naive 값으로 저장한다.
- `/healthz`는 아직 없으며 404다. 추가는 P2 범위다.

## 의도한 위반 6개

1. `app/db.py`: `sqlite:///./todo.db` 하드코딩 (`sqlite_usage`).
2. `app/main.py`: 명백한 더미 시크릿 `dummy-secret-do-not-use` (`hardcoded_secret`).
3. `app/main.py`: `logging.FileHandler` (`file_log`).
4. `app/main.py`: `uvicorn.run(..., port=8000)` (`fixed_port`).
5. `requirements.txt`: 정확한 버전이 없는 의존성 (`unpinned_dependency`, 파일당 하나로 집계).
6. `app/main.py`: 로컬 export 파일 쓰기 (`local_file_write`, needs_review/risky).

정답 목록은 `VIOLATIONS.json` 및 상위 폴더의 `todo.expected.json`이다. SQLite URL을 DB URL 규칙과 중복 집계하지 않는다. 이 목록은 탐지기의 입력으로 사용하지 않는다.

Postgres 변환·외부 파일 저장·기존 데이터 이전은 이 원본에 구현하지 않았다. 손 명세는 변환 후의 목표 예시이며 원본 코드가 그대로 명세를 충족한다는 증거가 아니다.
