# Task 03 · aDR 사전 점검 리포트

**요약**: 공식 OpenAPI만으로 DR 정책 상태를 점검하고 리포트(md/json)를 남깁니다. 정책 활성 여부, 보호 사이트 → DR 사이트 구성, 다음 동기화 시각, 보호 VM 목록·복구 우선순위·상태를 확인해요. **읽기 전용**이라 운영 환경에서 매일 돌려도 안전합니다. Task 04도 실행 전에 같은 점검을 거칩니다.

## 설치·실행

```bash
tar xzf 03-adr-precheck.tar.gz && cd 03-adr-precheck
./install.sh
vi .env
./run.sh                 # 전체 정책
./run.sh -p ERP-DR       # 정책 이름 또는 ID 하나만
```

- 결과: `reports/precheck-YYYYmmdd-HHMMSS.md`, `.json`
- 종료코드: `0` 전부 PASS / `1` FAIL 있음 / `2` 오류 → 모니터링·cron 연동용

매일 아침 점검 (cron 예시):
```bash
0 8 * * * /opt/sangfor-scp/03-adr-precheck/run.sh >> /var/log/adr-precheck.log 2>&1
```

## 환경별로 수정할 값 (`.env`)

| 값 | 언제 바꾸나 | 예시 |
|---|---|---|
| `SCP_HOST`, `SCP_AK`, `SCP_SK` | **항상** (Task 01과 동일) | `192.168.0.210` |
| `SCP_EC2_SIGN_QUERY` | Task 01이 `0`으로 바꾸라고 한 경우 | `1` |
| `REPORT_DIR` | 리포트를 다른 곳(공유 폴더 등)에 둘 때 | `/var/lib/adr/reports` |

Task 01에서 이미 맞춘 `.env`가 있으면 그대로 복사해 쓰면 됩니다: `cp ../01-scp-connect-check/.env .` 후 `REPORT_DIR`만 추가.

## 점검 항목

| 등급 | 조건 |
|---|---|
| FAIL | 정책 비활성 / 보호 VM 없음 / 정책에 있는 VM이 보호 VM 목록에 없음 |
| WARN | 정책 안에서 비활성된 VM / 보호 VM 상세 조회 실패 |
| OK·INFO | VM별 우선순위·상태, 사이트·AZ 구성, 다음 동기화 시각 |
