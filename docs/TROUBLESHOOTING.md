# 문제 해결

실제 구축하면서 겪은 오류를 원인·조치 순으로 정리했습니다.

## 설치·배포

| 증상 | 원인 | 조치 |
|---|---|---|
| `tar: command not found` | 최소 설치 OS | `deploy.sh`는 자동 처리. 수동이면 `dnf install -y tar` 또는 `python3 -m tarfile -e 파일.tar.gz .` |
| `먼저 install.sh 를 실행하세요` | 설치 안 함 | 태스크 폴더에서 `./install.sh` |
| `python3 설치 실패` | 폐쇄망 | OS ISO 저장소 연결 후 `dnf install -y python3` |
| 새 버전 배포 후 새 기능 설정이 없음 | 기존 `.env` 유지 | `install.sh`가 새 키를 자동 추가함. `tail .env`로 확인 |
| Mac에서 붙여 넣은 명령이 이상하게 동작 | zsh에 `#` 주석이 섞인 여러 줄 | 명령을 한 줄씩 실행 |

## OpenAPI (01, 03)

| 증상 | 원인 | 조치 |
|---|---|---|
| TCP 실패 | 방화벽·IP | 실행 서버 → SCP 443 허용, `SCP_HOST` 확인 |
| `401` (EC2) | AK/SK 오타, 시각 차이, 쿼리 서명 방식 | AK/SK 확인, `timedatectl`로 NTP 확인, `SCP_EC2_SIGN_QUERY=0` (6.11.3) |
| DR 정책 조회만 실패 | 6.11.1 미만, 라이선스·권한 | SCP 버전·aDR 라이선스 확인 |

## 콘솔 로그인 (01 `--console-login`, 04)

| 증상 | 원인 | 조치 |
|---|---|---|
| `SCP_USER/SCP_PASS가 필요합니다` | `.env` 비어 있음 | 값 입력 (01, 04 폴더 각각) |
| `/ticket 로그인 실패 … System is busy` | 비밀번호 오류, 또는 로그인 흐름 불일치(구버전 스크립트) | 비밀번호 확인 후 최신 버전 사용 (salt·ticket·logout 흐름 반영됨) |
| `RSAModulus를 찾지 못했습니다` | 콘솔 포트·주소 틀림 | `CONSOLE_PORT=4430`, 브라우저로 `https://SCP:4430/login` 확인 |
| `로그인은 성공했지만 세션 사용 실패` | 쿠키 처리 방식이 다른 버전 | 01 `--console-login` 결과를 첨부해 문의 |
| 쓰기 요청이 `Page has expired` | CSRF 토큰 없음 (`janus` 토큰 사용) | `CONSOLE_TOKEN_SOURCE=ticket` |
| 계정 잠김 | 로그인 실패 반복 | 콘솔에서 잠금 해제, 비밀번호 확인 후 재시도 |

## 드릴 (04)

| 증상 | 원인 | 조치 |
|---|---|---|
| `사전 점검 FAIL (현재 상태 doing/…)` | 다른 DR 작업이 진행 중 | 끝난 뒤 재실행. 이 경우 아무것도 건드리지 않음 |
| `사전 점검 FAIL (현재 상태 finish/…)` | 이전 드릴이 정리 안 됨 | `./trigger.sh cleanup` 후 재실행 |
| `현재 상태 'failed'` | 이전 드릴 실패 | 콘솔 Tasks에서 원인 확인 → `./trigger.sh cleanup` |
| `복구 계획 작업 실패 N건` | DR 쪽 리소스·스토리지·네트워크 문제 | 콘솔 Tasks 원인 확인 → `./trigger.sh cleanup` |
| `대기 시간 초과` | 드릴이 `TASK_TIMEOUT`보다 오래 걸림 | `TASK_TIMEOUT` 늘림. 콘솔에서 진행 중이면 끝난 뒤 `./trigger.sh cleanup` |
| `[FAIL] IP:포트 응답 없음` | DR VM 서비스가 안 뜸, 방화벽, 잘못된 `VERIFY_TARGETS` | 드릴 VM 콘솔에서 서비스 확인. 드릴 환경은 자동 정리됨 |
| `dr-server-list에 없는 VM` / `값이 비어 있는 VM` | 보호 그룹 구성 이상 | 콘솔에서 해당 VM의 보호 상태 확인 |
| `실행 불가 - 미검증: ['failover']` | failover/failback 미구현 | 정상 (안전장치) |
| `이미 실행 중입니다` (종료 코드 3) | 같은 폴더에서 이미 실행 중 | `logs/latest.log` 확인. 비정상 종료로 남은 `logs/.adr.lock.d`는 삭제 |
| 배포 후 `endpoints.json`이 예전 내용 | 구버전 deploy.sh | 1.0.0부터 새 버전으로 교체(이전 파일은 `.backup/`) |

## 웹훅·알림

| 증상 | 원인 | 조치 |
|---|---|---|
| 웹훅이 시작 안 됨 | `WEBHOOK_TOKEN` 16자 미만 | `openssl rand -hex 24` 값으로 설정 |
| `401` | 토큰 불일치 | 호출 쪽 토큰 확인 |
| `403 허용 안 된 동작` | `WEBHOOK_ALLOWED`에 없음 | 필요한 동작만 추가 |
| 외부에서 접속 안 됨 | 방화벽 | `firewall-cmd --add-port=8780/tcp` (관리망만) |
| 알림이 안 옴 | URL·형식 | 로그의 `[notify]` 줄 확인, `NOTIFY_FORMAT` 확인 |

## 진단 명령 모음

```bash
cd /opt/sangfor-scp/04-adr-drill
./run.sh status                               # 계획 상태
cat logs/last-result.json                     # 마지막 결과
tail -100 logs/latest.log                     # 마지막 로그
../01-scp-connect-check/run.sh --console-login
../01-scp-connect-check/run.sh --get /admin/view/dr-rp-list -o /tmp/rp.json   # 원본 응답 저장
```
