# Task 04 · aDR 드릴 / Failover / Failback 실행

**요약**: aDR **복구 계획(Recovery Plan)** 단위로 드릴 → 완료 대기 → DR 쪽 서비스 포트 확인 → 드릴 정리를 한 번에 돌립니다. Failover·Failback도 같은 방식이에요.

- 실행은 콘솔 API(`https://SCP:4430/admin/...`)로 해요. 인증은 OpenAPI 토큰을 그대로 씁니다(Task 01 `--console`로 확인).
- 상태는 `GET /admin/view/dr-rp-list`의 `status.state`(`ready` 대기 / `finish` 완료)와 `task_progress`(성공·실패 건수)로 추적해요.
- 실행 API 경로·본문은 공식 문서에 없어서 **Task 02 캡처 값을 `endpoints.json`에 채워야 동작**합니다. 채우기 전에는 계획만 보여주고 실행을 거부해요.

## 설치·실행

```bash
tar xzf 04-adr-drill.tar.gz && cd 04-adr-drill
./install.sh
vi .env                                              # SCP_HOST, SCP_USER/SCP_PASS, VERIFY_TARGETS
vi endpoints.json                                    # 캡처 결과로 path/body 채우기
./run.sh list                                        # 복구 계획 목록·상태
./run.sh drill    -p aDR-Auto-SCP-Test               # dry-run: 순서만 출력
./run.sh drill    -p aDR-Auto-SCP-Test --execute     # 실제 드릴
./run.sh drill    -p aDR-Auto-SCP-Test --execute --keep   # 드릴 VM 남겨두기
./run.sh cleanup  -p aDR-Auto-SCP-Test --execute     # 테스트 종료(정리)만
./run.sh failover -p aDR-Auto-SCP-Test --execute --confirm aDR-Auto-SCP-Test
```

## 드릴 본문 자동 생성

드릴 시작(`POST /admin/dr/rps/drill`) 본문은 `GET /admin/view/dr-server-list`에서 계획에 속한 VM 값을 모아 자동으로 만듭니다.
(`pg_id`, `server_id`, `protection_id`, 원본/DR 클러스터, 복구 저장소. 복구 시점은 최신)
dry-run에서 만들어질 본문을 미리 볼 수 있어요. 6.11.3 실측 캡처 본문과 일치하는 것을 확인했습니다.

| `.env` | 의미 | 기본 |
|---|---|---|
| `DRILL_NEED_SYNC` | 1이면 드릴 전 데이터 동기화 | `0` |
| `DRILL_RESOURCE_RESERVE` | 1이면 리소스 예약 | `0` |

## 랩 검증 (`--trust`)

`endpoints.json`의 `verified`를 바꾸지 않고, 이번 실행에서만 검증된 것으로 취급합니다.
```bash
./run.sh cleanup -p aDR-Auto-SCP-Test --execute --trust drill_cleanup,clear_state
./run.sh drill   -p aDR-Auto-SCP-Test --execute --trust drill_start,drill_cleanup,clear_state
```
랩에서 성공하면 `endpoints.json`의 해당 항목을 `"verified": true`로 바꾸세요.

## 안전장치

- `--execute` 없으면 항상 dry-run
- `endpoints.json`에서 `verified: true`가 아닌 단계가 하나라도 있으면 시작 전에 거부
- failover/failback은 `--confirm`에 복구 계획 이름을 정확히 넣어야 실행
- 사전 점검(사이트 상태, VM 수, `require_state`)이 FAIL이면 중단. 예: 드릴은 `ready` 상태에서만 시작
- 완료 판단은 작업 ID(`ulog_id`)가 바뀐 뒤의 상태만 인정 (이전 실행 결과를 완료로 착각하지 않음)
- 작업 실패(`task_progress.failed`)가 생기면 즉시 중단
- 드릴 중 서비스 검증이 실패해도 드릴 환경은 정리 (`--keep` 제외)

## 환경별로 수정할 값

### `.env`

| 값 | 언제 바꾸나 | 예시 |
|---|---|---|
| `SCP_HOST` | **항상** | `192.168.0.210` |
| `SCP_USER`, `SCP_PASS` | **항상**. 콘솔 API 로그인용 (OpenAPI 토큰을 콘솔에 재사용) | `admin` |
| `CONSOLE_TOKEN_SOURCE`, `CONSOLE_PORT` | 01 `--console` 결과가 다를 때만 | `janus`, `4430` |
| `VERIFY_TARGETS` | **고객·정책마다**. 드릴/전환 후 DR 사이트에서 떠야 할 서비스 `IP:포트` | `10.20.0.11:22,10.20.0.12:443` |
| `TASK_TIMEOUT` | VM이 많거나 용량이 커서 복구가 1시간 넘게 걸릴 때 | `3600` |
| `TASK_POLL_INTERVAL` | 진행률 확인 주기(초) | `10` |
| `ENDPOINTS_FILE` | 고객별 `endpoints.json`을 따로 관리할 때 | `/etc/adr/endpoints-custA.json` |

### `endpoints.json` (Task 02 결과로 채움)

| 항목 | 채울 내용 |
|---|---|
| `api` | `console`(4430, 기본) 또는 `openapi`(443) |
| `method`, `path` | 캡처한 값. 복구 계획 ID 자리는 `${rp_id}` (`${rp_name}`, `${project_id}`, 현재 작업 ID `${drlog_id}`도 사용 가능) |
| `body` | 캡처한 요청 본문. 고정값이 아닌 ID는 변수로 바꾸기 |
| `require_state` | 실행 전 필요한 계획 상태 (예: 드릴 시작은 `["ready"]`) |
| `wait` | 실행 후 기다릴 상태 (예: 드릴은 `{"until_state":["finish"],"action":"drill"}`) |
| `verified` | 랩에서 단독 호출로 동작 확인 후에만 `true` |

**SCP 버전이 바뀌면** 내부 API도 바뀔 수 있어요. 패치 후에는 다시 캡처하고 `verified`를 재확인하세요. 패키지를 새로 풀면 `endpoints.json`이 덮어써지니 먼저 백업하세요.

## 운영 환경 주의

고객 운영 환경의 failover/failback은 본사 확인 전에는 쓰지 말고, 드릴 자동화부터 적용하세요.
