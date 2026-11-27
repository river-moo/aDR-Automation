# Task 04 · aDR 드릴 자동화

**요약**: 복구 계획 하나를 **드릴 시작 → 완료 대기 → 서비스 확인 → 테스트 종료 → Ready 정리**까지 한 번에 돌립니다.
콘솔(4430) 내부 API를 사용하며 SCP 6.11.3 실장비에서 검증했습니다.

```bash
./trigger.sh drill
```

## 설치

```bash
tar xzf 04-adr-drill.tar.gz && cd 04-adr-drill
./install.sh
vi .env          # SCP_HOST, SCP_AK, SCP_SK, SCP_USER, SCP_PASS, ADR_PLAN (+ VERIFY_TARGETS, NOTIFY_WEBHOOK)
```

## 명령

| 명령 | 하는 일 | SCP 변경 |
|---|---|---|
| `./run.sh list` | 복구 계획 목록·상태 | 없음 |
| `./run.sh status [-p 계획]` | 한 계획의 상태 (JSON) | 없음 |
| `./run.sh drill` | dry-run: 실행 순서·드릴 본문 미리보기 | 없음 |
| `./run.sh drill --execute --step` | 단계마다 Enter로 진행 (시연·첫 실행) | 있음 |
| `./trigger.sh drill` | 전체 자동 실행 (잠금·로그·알림) | 있음 |
| `./trigger.sh drill --keep` | 드릴 VM을 정리하지 않고 남김 | 있음 |
| `./trigger.sh cleanup` | 테스트 종료 + Ready 정리 | 있음 |
| `./trigger.sh clear` | 상태만 Ready로 | 있음 |
| `./run.sh --webhook` | HTTP 웹훅 수신기 실행 | |

계획은 `.env`의 `ADR_PLAN`, 또는 `-p 이름|ID`로 지정합니다.
그 밖의 옵션: `--no-notify`(이번엔 알림 안 보냄), `--skip-precheck`(점검 무시, 비권장), `--trust 단계`(랩 검증용).

## 종료 코드

`0` 성공 · `1` 점검 실패/실행 거부 · `2` 오류(API·인증·타임아웃) · `3` 이미 실행 중 · `130` 사용자 중단

## 폴더 구성

| 파일 | 내용 |
|---|---|
| `.env` | 환경 설정 (유일하게 고치는 파일) |
| `endpoints.json` | 콘솔 API 정의 (SCP 버전이 바뀔 때만) |
| `trigger.sh` | 무인 실행 진입점 |
| `webhook.py` | HTTP 트리거 수신기 |
| `systemd/`, `cron.example` | 정기 실행 예시 |
| `logs/` | 실행 로그, `latest.log`, `last-result.json` |

## 안전장치

- `--execute` 없으면 항상 dry-run
- 계획이 `ready`일 때만 드릴 시작 → **다른 DR 작업 중인 계획은 건드리지 않음**
- 각 단계 직전에 상태 재확인 (`require_state`)
- 같은 폴더 동시 실행 방지 (잠금)
- 작업 실패·`failed` 상태면 즉시 중단 + 알림
- 서비스 확인 실패해도 드릴 환경은 정리 (`--keep` 제외)
- `endpoints.json`에서 `verified: true`가 아닌 단계는 실행 거부 → failover/failback은 현재 막혀 있음

## 더 보기

- 단계별 실행: [docs/STEP-BY-STEP.md](../../docs/STEP-BY-STEP.md)
- 환경별 변경값: [docs/ENVIRONMENT.md](../../docs/ENVIRONMENT.md)
- 트리거 (cron, systemd, Jenkins, Ansible, 웹훅): [docs/TRIGGERS.md](../../docs/TRIGGERS.md)
- API·상태값: [docs/API-MAP.md](../../docs/API-MAP.md)
- 오류 대응: [docs/TROUBLESHOOTING.md](../../docs/TROUBLESHOOTING.md)
