# P5 — 실제 인프라 적용 전 C 확인 항목

현재 tfvars와 비용은 **확인 필요(C 확정 전)**이다. 이 체크리스트가 완료되기 전에는 추천 JSON을 Terraform/배포 API에 바로 전달하지 않는다. B는 `.tf` 생성·apply·클라우드 배포를 하지 않는다.

## 변수 계약

- [ ] C의 실제 변수명과 `ai/src/ai/spec/tfvars_schema.py`의 Field alias가 일치한다. 이름·기본값·허용 범위는 이 파일에서만 수정한다.
- [ ] 공통 변수와 Lambda 전용/EC2 Compose 전용 변수를 구분했다. 현재 `ServerlessVars`와 `ContainerVars`는 임시 계약이며 AWS의 실제 한도를 주장하지 않는다.
- [ ] C의 Terraform validation과 타입·범위·기본값·필수/선택 항목이 일치한다. 잘못된 입력은 클램프하지 않고 경고와 기본값 대체로 보고하므로, A가 이를 화면에서 숨기지 않는다.
- [ ] `port`는 명세와 일치하고, 스케줄러/웹 프로세스의 인스턴스 수는 규칙의 1개와 일치한다. 임의 복제 변경으로 중복 작업이 발생하지 않는다.
- [ ] A가 실제 빌드한 이미지 태그/digest를 제공했다. 미제공 시 변수 출력에서 이미지 값은 생략된다. `source.commit`은 추적용이며 이미지 주소를 대신하지 않는다.
- [ ] 이미지의 대상 아키텍처, Lambda 호환성, EC2/온프레미스 실행 조건을 C가 확정했고, 실제 배포할 이미지로 다시 검증했다.
- [ ] 변수에 시크릿 값을 넣지 않고 C의 바인딩/Secret 관리 방식을 사용한다.

## 비용 계약

- [ ] `ai/src/ai/spec/cost_table.py`의 모든 **단가 미확인** 숫자를 확인했다. 지금 숫자는 계획용 가정이며 실제 AWS 요금/청구 견적이 아니다.
- [ ] 리전, Lambda 아키텍처·메모리, EC2 타입, DB 타입·가동 시간, 스토리지 종류/크기를 확정했다. 현재 서버리스는 별도 DB, 상시 컨테이너는 동일 서버의 Postgres를 가정한다.
- [ ] 월 요청 수, 평균 요청 실행 시간, 상시 가동 시간, 스토리지 사용량을 확인했다. 평균 시간은 `max_request_seconds`와 다르다.
- [ ] 프리티어·크레딧·할인 제외 가정을 확인했다. 환율 변환은 적용하지 않는다.
- [ ] 누락 비용(전송·NAT·로그·백업·세금·DB HA·온프레미스 하드웨어/운영)을 추가하거나 화면에 명시했다. 요청 수에 비례한 계산이 없는 상시 세트의 용량도 검토한다.
- [ ] 확인한 요금 출처·확인일·단위·통화를 기록하고 단가 테이블을 갱신했다. Bedrock 호출 비용은 별도 `ai/pricing.json`과 `cost.json`에서 관리한다.

## A에서 표시할 상태

- [ ] `recommendation.needs_confirmation = ["tfvars_schema", "cost_table"]`일 때 **임시 추정치**와 확인 필요를 표시한다. C 확인 전 이 필드를 임의로 비우지 않는다.
- [ ] `needs_approval`, `data_migration_unsupported`, 보류된 파일 저장/의존성 항목을 표시한다. 샘플 실행 성공을 실제 사용자 변경 승인으로 간주하지 않는다.
- [ ] 게이트의 `scope`, `status`, 원본 비교 여부와 재시도 기록을 표시한다. Fake/샘플 밖의 `skipped`를 성공 또는 PR 승인 가능으로 바꾸지 않는다.
- [ ] 게이트 통과만으로 전체 기능·배포 준비 완료를 표시하지 않는다. 현재 `pr_eligible=false`다.

참고할 공식 요금 페이지는 [Lambda](https://aws.amazon.com/lambda/pricing/), [EC2](https://aws.amazon.com/ec2/pricing/on-demand/), [RDS PostgreSQL](https://aws.amazon.com/rds/postgresql/pricing/)이다. 이 링크가 현재 테이블 숫자의 검증 근거는 아니다.
