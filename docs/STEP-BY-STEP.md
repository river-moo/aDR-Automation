# 단계별 실행 가이드

처음 받는 사람이 이 순서대로만 따라 하면 드릴이 돌아가도록 정리했습니다.
`<...>`는 환경마다 바꿀 값입니다. (예: `<SCP_IP>` = 192.168.0.210)

| 단계 | 하는 곳 | 내용 | SCP 변경 |
|---|---|---|---|
| 0 | - | 준비물 확인 | |
| 1 | 내 PC (Mac/리눅스) | 저장소 받기, 빌드 | |
| 2 | 내 PC → 실행 서버 | 배포·설치 | |
| 3 | 실행 서버 | `.env` 설정 | |
| 4 | 실행 서버 | 01 접속·로그인 점검 | 없음 |
| 5 | 실행 서버 | 04 계획 확인, dry-run | 없음 |
| 6 | 실행 서버 | 단계별 실행 (`--step`) | **있음** |
| 7 | 실행 서버 | 한 번에 실행 (`trigger.sh`) | **있음** |
| 8 | 실행 서버 | 트리거 등록 (cron / systemd / 웹훅) | |

---

## 0. 준비물

| 항목 | 확인 방법 |
|---|---|
| SCP 관리 IP, 콘솔 관리자 계정 (`admin` 등) | 콘솔 `https://<SCP_IP>:4430` 로그인 되는지 |
| OpenAPI AK/SK | SCP 콘솔 또는 기술지원에서 발급 |
| 실행 서버 (리눅스, root 또는 sudo) | `ssh root@<실행서버IP>` |
| 실행 서버 → SCP 443, 4430 통신 | 실행 서버에서 `curl -k https://<SCP_IP>:4430/login -o /dev/null -w '%{http_code}\n'` → `200` |
| aDR 복구 계획 1개 이상 (콘솔에서 Ready 상태) | 콘솔 DR → Recovery Plan |
| 실행 서버 시각 동기화 (AK/SK 서명이 시각에 민감) | `timedatectl` → `System clock synchronized: yes` |

## 1. 받기 · 빌드 (내 PC)

```bash
git clone https://github.com/river-moo/aDR-Automation.git
cd aDR-Automation
./scripts/build.sh
```
`dist/`에 `01-scp-connect-check.tar.gz` … `04-adr-drill.tar.gz`, `.zip`, `SHA256SUMS`가 생깁니다.

## 2. 배포 · 설치

**방법 A · 자동 (권장)**
```bash
./scripts/deploy.sh root@<실행서버IP> 01 04
```
복사 → 압축 해제 → `install.sh`까지 한 번에 합니다. 기본 경로 `/opt/sangfor-scp/`. tar가 없는 최소 설치 OS도 자동 처리해요.

**방법 B · 수동 (폐쇄망, USB 등)**
```bash
scp dist/04-adr-drill.tar.gz root@<실행서버IP>:/opt/
ssh root@<실행서버IP>
mkdir -p /opt/sangfor-scp && cd /opt/sangfor-scp
tar xzf /opt/04-adr-drill.tar.gz
cd 04-adr-drill && ./install.sh
```
tar가 없으면 `python3 -m tarfile -e /opt/04-adr-drill.tar.gz .` 또는 zip 파일 사용.

## 3. `.env` 설정 (실행 서버)

```bash
vi /opt/sangfor-scp/04-adr-drill/.env
```
**반드시 넣을 값 5개**:
```ini
SCP_HOST=<SCP_IP>
SCP_AK=<AK>
SCP_SK=<SK>
SCP_USER=<콘솔 관리자 계정>
SCP_PASS=<비밀번호>
```
**넣으면 편한 값**:
```ini
ADR_PLAN=<복구 계획 이름>              # 지정하면 -p 생략 가능, trigger.sh/웹훅 기본값
VERIFY_TARGETS=<DR쪽IP>:<포트>,...     # 드릴 VM이 뜬 뒤 확인할 서비스 (비우면 생략)
NOTIFY_WEBHOOK=<Slack/Teams 등 URL>    # 결과 알림 (비우면 생략)
```
01 폴더의 `.env`에도 같은 `SCP_*` 값을 넣으세요. 전체 값 설명은 [ENVIRONMENT.md](ENVIRONMENT.md).

## 4. 접속·로그인 점검 (01)

```bash
cd /opt/sangfor-scp/01-scp-connect-check
./run.sh                      # OpenAPI: TCP → 인증 → 버전 → 리소스 풀 → DR 정책
./run.sh --console-login      # 콘솔: 로그인 → 조회 → 쓰기(CSRF)
```
둘 다 `[PASS]`면 다음 단계로. 실패하면 메시지에 나온 값을 고치거나 [TROUBLESHOOTING.md](TROUBLESHOOTING.md) 참고.

## 5. 계획 확인 · 미리보기 (04, 변경 없음)

```bash
cd /opt/sangfor-scp/04-adr-drill
./run.sh list                         # 복구 계획 목록과 상태
./run.sh status                       # ADR_PLAN 계획의 현재 상태 (JSON)
./run.sh drill                        # dry-run: 실행 순서와 자동 생성될 드릴 본문만 출력
```
`list`에서 계획 상태가 **ready**여야 드릴을 시작할 수 있어요.

## 6. 단계별 실행 (처음 한 번, 시연·교육용)

```bash
./run.sh drill --execute --step
```
각 단계 전에 멈춥니다. `Enter` 진행 / `s` 건너뛰기 / `q` 중단.

| 순서 | 단계 | 콘솔에서 보이는 것 | 보통 걸리는 시간 |
|---|---|---|---|
| 1 | 드릴 시작 | Recovery Plan 상태 Testing → Tasks에 드릴 작업 | VM 수·용량에 따라 (랩 약 10분) |
| 2 | 서비스 확인 | (`VERIFY_TARGETS` 포트 접속) | 수 초 |
| 3 | 테스트 종료 | Cleanup 작업 → "Cleanup successful" | 약 1분 |
| 4 | 상태 정리 | 계획 상태 Ready | 수 초 |

중간에 멈추거나 끊겼다면:
```bash
./run.sh status                       # 지금 상태 확인
./run.sh cleanup --execute            # 테스트 종료 + Ready 정리
./run.sh clear --execute              # 상태만 Ready로 (이미 정리된 경우)
```

## 7. 한 번에 실행

```bash
./trigger.sh drill
```
`run.sh drill --execute`와 같은 동작에 **잠금(동시 실행 방지), 로그 파일, 결과 파일, 알림**이 붙습니다.

| 결과 | 위치 |
|---|---|
| 실행 로그 | `logs/YYYYmmdd-HHMMSS-drill.log`, 최신은 `logs/latest.log` |
| 마지막 결과 (JSON) | `logs/last-result.json` |
| 종료 코드 | `0` 성공 · `1` 점검 실패/거부 · `2` 오류 · `3` 이미 실행 중 · `130` 중단 |

## 8. 트리거 등록

정기 실행이나 외부 호출은 [TRIGGERS.md](TRIGGERS.md)를 보세요. 가장 흔한 두 가지:
```bash
# 정기 실행 (매월 첫째 토요일 02:00)
cp systemd/adr-drill.service systemd/adr-drill.timer /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now adr-drill.timer

# 내 PC에서 원격 실행
ssh root@<실행서버IP> /opt/sangfor-scp/04-adr-drill/trigger.sh drill
```
