# 환경이 바뀔 때 고칠 값

코드는 고치지 않습니다. 바뀌는 값은 **`.env` 한 파일**(태스크 폴더마다 하나)과, SCP 버전이 바뀔 때만 **`endpoints.json`** 입니다.

- ● 환경마다 **반드시** 바꿈 · ◐ 상황에 따라 · ○ 보통 그대로
- 파일 위치: `/opt/sangfor-scp/<태스크>/.env` (설치 시 `.env.example`에서 생성, 권한 600)

## 1. 고객·사이트마다 바뀌는 값 (●)

| 값 | 의미 | 어디서 확인 | 예시 | 01 | 03 | 04 |
|---|---|---|---|:-:|:-:|:-:|
| `SCP_HOST` | SCP 관리 IP. 443이 아니면 `https://IP:PORT` | SCP 콘솔 주소 | `192.168.0.210` | ● | ● | ● |
| `SCP_AK`, `SCP_SK` | OpenAPI 키 | SCP 발급 | | ● | ● | ● |
| `SCP_USER`, `SCP_PASS` | 콘솔 관리자 계정 (드릴 실행용 로그인) | 고객 계정 | `admin` | ● | | ● |
| `ADR_PLAN` | 드릴할 복구 계획 이름 또는 ID | `./run.sh list` | `aDR-Auto-SCP-Test` | | | ● |
| `VERIFY_TARGETS` | 드릴 후 DR 쪽에서 응답해야 할 서비스 `IP:포트` (쉼표 구분) | 고객 업무 서비스 | `10.20.0.11:22,10.20.0.12:443` | | | ◐ |

## 2. 운영 정책에 따라 바꾸는 값 (◐)

| 값 | 의미 | 기본 | 언제 바꾸나 |
|---|---|---|---|
| `TASK_TIMEOUT` | 단계별 최대 대기(초) | `3600` | VM이 많거나 커서 드릴이 1시간 넘을 때 |
| `TASK_POLL_INTERVAL` | 상태 확인 주기(초) | `10` | |
| `DRILL_NEED_SYNC` | `1`이면 드릴 전 데이터 동기화 | `0` | 최신 데이터로 드릴해야 할 때 |
| `DRILL_RESOURCE_RESERVE` | `1`이면 DR 리소스 예약 | `0` | 콘솔에서 예약을 쓰는 고객 |
| `VERIFY_TIMEOUT` | 서비스 포트 확인 제한(초) | `5` | |
| `NOTIFY_WEBHOOK` | 결과 알림 URL | (없음) | 메신저로 결과를 받을 때 |
| `NOTIFY_FORMAT` | `slack` · `mattermost` · `teams` · `telegram` · `generic` | `generic` | |
| `NOTIFY_CHAT_ID` | telegram일 때 채팅 ID | | |
| `LOG_DIR`, `LOG_KEEP_DAYS` | 로그 위치, 보관 일수 | `logs/`, `30` | |
| `WEBHOOK_TOKEN` | 웹훅 수신기 인증 토큰 (16자 이상) | (없음) | 웹훅 사용 시 **필수** (`openssl rand -hex 24`) |
| `WEBHOOK_BIND`, `WEBHOOK_PORT` | 웹훅 수신 주소·포트 | `0.0.0.0`, `8780` | 포트 충돌, 관리망 IP로만 열 때 |
| `WEBHOOK_ALLOWED` | 웹훅으로 허용할 동작 | `drill,cleanup,clear` | |
| `ENDPOINTS_FILE` | 다른 `endpoints.json` 사용 | (이 폴더) | SCP 버전별 정의를 따로 둘 때 |
| `REPORT_DIR` | 03 리포트 위치 | `reports/` | |

## 3. 보통 그대로 두는 값 (○)

| 값 | 기본 | 바꾸는 경우 |
|---|---|---|
| `SCP_AUTH` | `auto` | AK/SK 없이 계정 토큰으로만 쓸 때 `token` |
| `SCP_VERIFY_TLS` | `0` | SCP에 정식 인증서가 있을 때 `1` |
| `SCP_TIMEOUT` | `30` | 느린 WAN 구간 |
| `SCP_EC2_REGION`, `SCP_EC2_SERVICE` | `cn-south-1`, `sdk-api` | 인증이 계속 실패하면 본사에 확인 |
| `SCP_EC2_SIGN_QUERY` | `0` (6.11.3 실측) | 01 점검이 `1`로 바꾸라고 할 때 |
| `CONSOLE_PORT` | `4430` | 콘솔 포트를 바꾼 사이트 |
| `CONSOLE_TOKEN_SOURCE` | `ticket` | 조회만 할 때 `janus`, 브라우저 쿠키로 테스트할 때 `manual` |
| `CONSOLE_LOGIN_ENC` | `page-pkcs1` (6.11.3 실측) | 로그인 암호화 방식이 바뀐 버전 |

## 4. 환경 바뀔 때 체크리스트

**새 고객·새 사이트**
1. 실행 서버 → SCP 443/4430 방화벽 허용, NTP 동기화
2. `.env`: `SCP_HOST`, `SCP_AK`, `SCP_SK`, `SCP_USER`, `SCP_PASS`, `ADR_PLAN`, `VERIFY_TARGETS`
3. `01 ./run.sh` → `01 ./run.sh --console-login` 모두 PASS
4. `04 ./run.sh drill` (dry-run) → 본문에 VM이 다 들어갔는지 확인
5. 랩/점검 시간에 `04 ./run.sh drill --execute --step` 한 번

**같은 고객, 복구 계획만 변경** → `ADR_PLAN`, `VERIFY_TARGETS`만

**비밀번호 변경** → `SCP_PASS` (01, 04 둘 다)

**SCP 업그레이드** → 01 `--console-login` → 04 dry-run → 랩에서 `--step`. 실패하면 [API-MAP.md](API-MAP.md)의 재확인 절차로 `endpoints.json` 갱신

**실행 서버 교체** → 새 서버에 deploy, 기존 `.env` 복사 (`scp old:/opt/sangfor-scp/04-adr-drill/.env new:...`), 트리거(cron/systemd) 재등록

## 5. 여러 고객·여러 계획을 한 서버에서

설치 폴더를 고객마다 하나씩 두면 서로 섞이지 않습니다(잠금·로그도 폴더별).
```bash
DEST=/opt/adr-custA ./scripts/deploy.sh root@HOST 04
DEST=/opt/adr-custB ./scripts/deploy.sh root@HOST 04
```
같은 SCP의 계획 여러 개는 폴더 하나에서 `-p`로 지정하면 됩니다: `./trigger.sh drill -p 계획B`
(같은 폴더에서는 잠금 때문에 한 번에 하나씩만 실행됩니다)
