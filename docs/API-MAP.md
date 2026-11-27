# API 맵 (SCP 6.11.3 실측)

## 1. 공식 OpenAPI (443, `/janus`) - 01·03에서 사용

| 용도 | 메서드·경로 |
|---|---|
| 버전 | `GET /janus/20180725/system/version` |
| 리소스 풀(AZ) | `GET /janus/20180725/azs` |
| DR 정책 | `GET /janus/20240725/protections` (6.11.1+) |
| 보호 VM | `GET /janus/20220725/servers?in_protection=1` |
| 작업 진행률 | `GET /janus/20180725/tasks/{task_id}` |

인증: EC2 AK/SK(AWS4-HMAC-SHA256, region `cn-south-1`, service `sdk-api`, 서명 헤더 `cookie;x-amz-date`, **쿼리는 서명하지 않음**) 또는 토큰(`/janus/v2/public-key` + OAEP, `/janus/public-key` + PKCS1).

**드릴·전환 실행 API는 공식 OpenAPI에 없습니다.** → 콘솔 내부 API 사용.

## 2. 콘솔 로그인 (4430) - 콘솔 로그인 버튼과 같은 흐름

| 순서 | 요청 | 비고 |
|---|---|---|
| 1 | `GET /login` | HTML에서 `RSAModulus`, `window.VMP.data.ticket`(UUID) 추출. ticket을 `CSRFPreventionToken` 쿠키로 |
| 2 | `POST /logout` (헤더 `csrfpreventiontoken: ticket`) | 화면이 로그인 전에 먼저 부름 |
| 3 | `GET /salt` | `{salt, timestamp}` |
| 4 | 비밀번호 암호화 | 평문 `timestamp#salt#password` → RSA PKCS#1 v1.5 (e=0x10001) → 16진수 |
| 5 | `POST /ticket` (form) | `username, password, status=agree, user_login=true` |
| 6 | 응답 `data.client_token`, `data.CSRFPreventionToken` | 이후 요청: 쿠키 `aCMPAuthToken`, `CSRFPreventionToken` + 헤더 `Client_token`, `Csrfpreventiontoken`, `X-Requested-With: XMLHttpRequest` |

OpenAPI 토큰을 콘솔에 넣으면 **조회(GET)만 되고 쓰기는 "Page has expired"(CSRF)** 로 거부됩니다. 그래서 기본은 위 로그인(`CONSOLE_TOKEN_SOURCE=ticket`).

## 3. 콘솔 aDR API (4430, `/admin`) - 04에서 사용

| 단계 | 메서드·경로 | 본문 | 실행 전 상태 | 실행 후 기다리는 상태 | 검증 |
|---|---|---|---|---|---|
| 계획 목록·상태 | `GET /admin/view/dr-rp-list?start=0&limit=200` | | | | ✔ |
| VM 목록 (드릴 본문 재료) | `GET /admin/view/dr-server-list?start=&limit=100` | | | | ✔ |
| 드릴 시작 | `POST /admin/dr/rps/drill` | 아래 참고 (자동 생성) | `ready` | `finish` + action `drill` | ✔ |
| 테스트 종료 | `DELETE /admin/dr/rps/{rp_id}/drill/{drlog_id}` | `{rp_id, drlog_id}` | `finish`/`failed` | `ready`/`finish` | ✔ |
| 상태 정리 | `PUT /admin/dr/rps/state/transform` | `{"rps":[{"rp_id":"…"}]}` | `finish`/`failed` | `ready` | ✔ |
| Failover | (미확인) | | | | ✘ |
| Failback ("Migration to Primary Site") | (미확인, `migrate` 동작) | | | | ✘ |

콘솔 JS(모듈 46667)에서 본 그 밖의 API (사용 안 함): `dr/rps-view`, `dr/rps`(생성), `dr/drlogs`, `dr/drlogs/{id}`, `dr/rps/drill/drill-server`, `dr/rps/{rp_id}/trigger-migration-sync`, `dr/rps/delete`, `dr/rps/{rp_id}/drill/{drlog_id}/drill-servers`, `dr/rps/calc-sync-time`, `users/verify-password`

**드릴 시작 본문**
```json
{"drill": {
  "rps": [{"rp_id": "<계획ID>", "servers": [{
     "pg_id": "…", "server_id": "…", "protection_id": "…", "recovery_storage_id": "…",
     "src_clusters": [{"cluster_id": "…", "status": "…"}],
     "des_clusters": [{"cluster_id": "…", "status": "…"}]}]}],
  "need_sync": 0, "enable_resource_reserve": 0}}
```
값은 `dr-server-list`의 VM 행에서 채웁니다 (`id`, `pg.pg_id`, `protection.id`, `recovery_storage_id`, 클러스터). 복구 시점은 최신(생략).

## 4. 복구 계획 상태값 (`dr-rp-list` 행)

| 필드 | 값 |
|---|---|
| `status.action` | `drill` 드릴 · `drill_clean` 테스트 종료 · `recover` 전환 · `migrate` 복귀 · `null` |
| `status.state` | `ready` 대기 · `doing` 진행 중 · `finish` 완료 · `failed` 실패 |
| `status.ulog_id` | 작업 ID (테스트 종료 때는 **바뀌지 않음**) |
| `status.drlog_id` | 현재 드릴 ID (테스트 종료 API에 사용) |
| `task_progress` | `{succeed, failed, total}` |

드릴 한 번의 흐름: `ready/null` → `doing/drill` → `finish/drill` → (테스트 종료) `doing/drill_clean` → `finish/drill_clean` → (상태 정리) `ready/null`

## 5. SCP 버전이 바뀌었을 때 재확인 절차

1. `01 ./run.sh --console-login` - 로그인 흐름 확인
2. `04 ./run.sh list`, `./run.sh drill` (dry-run) - 조회 API·본문 확인
3. 랩에서 `04 ./run.sh drill --execute --step` - 단계별로 콘솔과 대조
4. 실패하는 단계가 있으면 콘솔에서 해당 버튼을 누르며 F12 → Network(또는 Task 02 HAR 분석)로 경로·본문을 확인하고 `endpoints.json`의 `method`/`path`/`body`를 고친 뒤 `verified: true`
5. 버전별로 따로 두려면 `endpoints-6.11.x.json`으로 저장하고 `.env`의 `ENDPOINTS_FILE`로 지정
