# 전달 자료

- `hand-specs/`: 두 샘플의 초기 목표 명세 초안. 현재 검증 계약은 `deploy-spec-contract.md`와 `reference/deploy-spec.mvp.yaml`을 따른다.
- `deploy-spec-contract.md`: 검토 후 ENV/DB/이미지/패키징/실행 책임을 정리한 A/B/C 계약.
- `integration.md`: CLI/함수 연결 안내. 상세 요청 격리는 `docs/integration-for-service.md`를 참고한다.
- `model-selection-prompt.md`: 별도 모델 선택 검토 프롬프트. 이 작업에서 모델/IAM을 교체하지 않았다.

실행 결과·개인 trace는 요청별 `out/`에 생성하고 Git에서 제외한다. 검토한 두 샘플의 cache/fixture만 별도 포함한다.
데모 캐시의 현재 gate는 skipped이고 과거 통과·응답 출처·사용량을 명확히 구분한다.
