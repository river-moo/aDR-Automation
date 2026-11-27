# Task 04 · aDR 드릴 / Failover / Failback 실행

**요약**: 사전 점검 → 드릴 시작 → SCP 작업 완료 대기 → DR 쪽 서비스 포트 확인 → 드릴 정리를 한 번에 돌립니다. Failover·Failback도 같은 방식이에요. 실행 API는 공식 문서에 없어서 **Task 02로 캡처한 값을 `endpoints.json`에 채워야 동작**합니다. 채우기 전에는 계획만 보여주고 실행을 거부해요.

## 설치·실행

```bash
tar xzf 04-adr-drill.tar.gz && cd 04-adr-drill
./install.sh
vi .env
vi endpoints.json                                   # Task 02 결과로 채우기
./run.sh drill    -p ERP-DR                         # dry-run: 순서만 출력
./run.sh drill    -p ERP-DR --execute               # 실제 드릴
./run.sh drill    -p ERP-DR --execute --keep        # 드릴 VM 남겨두기
./run.sh cleanup  -p ERP-DR --execute               # 남긴 드릴 정리
./run.sh failover -p ERP-DR --execute --confirm ERP-DR
./run.sh failback -p ERP-DR --execute --confirm ERP-DR
```

## 안전장치

- `--execute` 없으면 항상 dry-run
- `endpoints.json`에서 `verified: true`가 아닌 단계가 하나라도 있으면 시작 전에 거부
- failover/failback은 `--confirm`에 정책 이름을 정확히 넣어야 실행
- 사전 점검(Task 03과 동일)이 FAIL이면 중단
- 드릴 중 서비스 검증이 실패해도 드릴 환경은 정리 (`--keep` 제외)

## 환경별로 수정할 값

### `.env`

| 값 | 언제 바꾸나 | 예시 |
|---|---|---|
| `SCP_HOST`, `SCP_AK`, `SCP_SK` | **항상** (Task 01과 동일) | `192.168.0.210` |
| `VERIFY_TARGETS` | **고객·정책마다**. 드릴/전환 후 DR 사이트에서 떠야 할 서비스 `IP:포트` | `10.20.0.11:22,10.20.0.12:443` |
| `TASK_TIMEOUT` | VM이 많거나 용량이 커서 복구가 1시간 넘게 걸릴 때 | `3600` |
| `TASK_POLL_INTERVAL` | 진행률 확인 주기(초) | `10` |
| `ENDPOINTS_FILE` | 고객별 `endpoints.json`을 따로 관리할 때 | `/etc/adr/endpoints-custA.json` |

### `endpoints.json` (Task 02 결과로 채움)

| 항목 | 채울 내용 |
|---|---|
| `path` | 캡처한 경로. 정책 ID 자리는 `${protection_id}`로 (`${policy_name}`도 사용 가능) |
| `body` | 캡처한 요청 본문. 고정값이 아닌 ID는 변수로 바꾸기 |
| `async`, `task_id_field` | 응답이 작업 ID를 주면 `true` + 그 필드 이름 (캡처 응답 확인) |
| `verified` | 랩에서 단독 호출로 동작 확인 후에만 `true` |

**SCP 버전이 바뀌면** 내부 API도 바뀔 수 있어요. 패치 후에는 다시 캡처하고 `verified`를 재확인하세요. 패키지를 새로 풀면 `endpoints.json`이 덮어써지니 먼저 백업하세요.

## 운영 환경 주의

고객 운영 환경의 failover/failback은 본사 확인 전에는 쓰지 말고, 드릴 자동화부터 적용하세요.
