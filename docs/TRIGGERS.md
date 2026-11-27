# 트리거하는 방법

모든 트리거는 결국 **`trigger.sh` 한 파일**을 부릅니다. 그래서 어떤 방법을 써도 동작·잠금·로그·알림이 똑같아요.

```
 수동 / ssh / cron / systemd timer / Jenkins / Ansible / 웹훅(HTTP)
                         │
                         ▼
              trigger.sh drill  ── 잠금(동시 실행 방지) · 로그 · 결과 JSON
                         │
                         ▼
              run.sh drill --execute
        점검 → 드릴 시작 → 완료 대기 → 서비스 확인 → 테스트 종료 → Ready
                         │
                         ▼
              알림 (NOTIFY_WEBHOOK) + logs/last-result.json
```

| 방법 | 언제 | 사람 필요 |
|---|---|---|
| 1. 수동 실행 | 시연, 첫 실행 | 예 |
| 2. 원격 ssh 한 줄 | 내 PC에서 바로 | 예 |
| 3. cron | 정기 드릴 (가장 단순) | 아니오 |
| 4. systemd timer | 정기 드릴 (권장: 로그·재시작·놓친 실행 관리) | 아니오 |
| 5. Jenkins / GitLab CI | 변경관리 승인 후 실행, 이력 관리 | 승인만 |
| 6. Ansible | 여러 사이트 일괄 | 아니오 |
| 7. 웹훅(HTTP) | 모니터링 경보, 메신저 봇, 휴대폰 단축어 | 버튼 한 번 |

사용 가능한 동작: `drill`(전체) · `cleanup`(테스트 종료+정리) · `clear`(상태만 Ready) · `status` · `list`

---

## 1. 수동 실행

```bash
cd /opt/sangfor-scp/04-adr-drill
./trigger.sh drill                  # ADR_PLAN 계획
./trigger.sh drill -p 다른계획       # 계획 지정
./run.sh drill --execute --step     # 단계마다 Enter (시연용)
```

## 2. 원격 ssh 한 줄 (내 PC → 실행 서버)

```bash
ssh root@<실행서버IP> /opt/sangfor-scp/04-adr-drill/trigger.sh drill
ssh root@<실행서버IP> /opt/sangfor-scp/04-adr-drill/trigger.sh status
ssh root@<실행서버IP> tail -f /opt/sangfor-scp/04-adr-drill/logs/latest.log    # 진행 보기
```
비밀번호 없이 쓰려면 한 번만: `ssh-copy-id root@<실행서버IP>`

ssh가 끊겨도 계속 돌게 하려면:
```bash
ssh root@<실행서버IP> 'nohup /opt/sangfor-scp/04-adr-drill/trigger.sh drill >/dev/null 2>&1 &'
```

## 3. cron

```bash
crontab -e
```
```cron
# 매월 첫째 토요일 02:00 (cron은 "일"과 "요일"을 OR로 처리해서 날짜는 date로 검사)
0 2 * * 6  [ "$(date +\%d)" -le 07 ] && TRIGGER_SOURCE=cron /opt/sangfor-scp/04-adr-drill/trigger.sh drill >/dev/null 2>&1
# 매주 일요일 03:00
0 3 * * 0  TRIGGER_SOURCE=cron /opt/sangfor-scp/04-adr-drill/trigger.sh drill >/dev/null 2>&1
```
예시 파일: `cron.example`. 결과는 `logs/`와 알림으로 확인.

## 4. systemd timer (권장)

```bash
cd /opt/sangfor-scp/04-adr-drill
cp systemd/adr-drill.service systemd/adr-drill.timer /etc/systemd/system/
vi /etc/systemd/system/adr-drill.timer          # OnCalendar 일정 수정
systemctl daemon-reload
systemctl enable --now adr-drill.timer
```
| 하고 싶은 것 | 명령 |
|---|---|
| 다음 실행 시각 | `systemctl list-timers adr-drill.timer` |
| 지금 바로 한 번 | `systemctl start adr-drill` |
| 실행 기록 | `journalctl -u adr-drill -n 100` |
| 정기 실행 끄기 | `systemctl disable --now adr-drill.timer` |

`OnCalendar` 예: `Sat *-*-01..07 02:00:00`(매월 첫째 토 02시) · `Sun 03:00`(매주 일) · `*-*-15 01:00`(매월 15일)
설치 경로가 `/opt/sangfor-scp`가 아니면 `.service`의 경로 두 곳을 고치세요.

## 5. Jenkins / GitLab CI

실행 서버를 에이전트로 쓰거나, ssh로 호출합니다. 종료 코드가 그대로 빌드 결과가 됩니다(0 성공).

**Jenkins (Pipeline)**
```groovy
pipeline {
  agent any
  parameters { choice(name: 'ACTION', choices: ['drill', 'cleanup', 'clear'], description: 'aDR 동작') }
  stages {
    stage('aDR') {
      steps {
        input message: "aDR ${params.ACTION} 실행할까요?"      // 승인 단계 (필요 없으면 삭제)
        sh "ssh root@<실행서버IP> TRIGGER_SOURCE=jenkins-${env.BUILD_NUMBER} /opt/sangfor-scp/04-adr-drill/trigger.sh ${params.ACTION}"
      }
    }
  }
}
```

**GitLab CI**
```yaml
adr-drill:
  when: manual
  script:
    - ssh root@<실행서버IP> TRIGGER_SOURCE=gitlab-$CI_PIPELINE_ID /opt/sangfor-scp/04-adr-drill/trigger.sh drill
```

## 6. Ansible

```yaml
- hosts: adr_runners          # 실행 서버들 (사이트별)
  tasks:
    - name: aDR 드릴
      command: /opt/sangfor-scp/04-adr-drill/trigger.sh drill
      environment: { TRIGGER_SOURCE: ansible }
      register: r
      failed_when: r.rc not in [0]
      async: 10800             # 최대 3시간
      poll: 30
```

## 7. 웹훅 (HTTP 요청 한 번)

실행 서버에 작은 HTTP 수신기(`webhook.py`, 표준 라이브러리만 사용)를 띄워 둡니다.

**켜기**
```bash
cd /opt/sangfor-scp/04-adr-drill
echo "WEBHOOK_TOKEN=$(openssl rand -hex 24)" >> .env      # 또는 vi로 직접
grep WEBHOOK_TOKEN .env                                   # 토큰 확인 (호출하는 쪽에 등록)
cp systemd/adr-webhook.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now adr-webhook
firewall-cmd --add-port=8780/tcp --permanent && firewall-cmd --reload   # 필요 시, 관리망만
```
(테스트로 잠깐 띄우기: `./run.sh --webhook`)

**호출**
```bash
TOKEN=<WEBHOOK_TOKEN>
curl -X POST -H "Authorization: Bearer $TOKEN" http://<실행서버IP>:8780/run/drill
curl -X POST -H "Authorization: Bearer $TOKEN" -d '{"plan":"aDR-Auto-SCP-Test"}' http://<실행서버IP>:8780/run/drill
curl -H "Authorization: Bearer $TOKEN" http://<실행서버IP>:8780/status
curl http://<실행서버IP>:8780/health
```
| 주소 | 설명 | 응답 |
|---|---|---|
| `POST /run/<동작>` | 실행 접수 후 바로 응답 (백그라운드 실행) | `202` 접수 · `401` 토큰 · `403` 허용 안 된 동작 · `409` 이미 실행 중 |
| `GET /status` | 실행 중 여부 + 마지막 결과 | `200` |
| `GET /health` | 수신기 살아있는지 (토큰 불필요) | `200` |

토큰은 `Authorization: Bearer`, `X-ADR-Token` 헤더, 또는 헤더를 못 넣는 도구용 `?token=` 중 하나로 보냅니다(로그에는 가려짐).

**어디서 부를 수 있나**
- 모니터링(Zabbix, Grafana, Prometheus Alertmanager): 경보 동작에 웹훅 URL 등록
- 사내 메신저 봇(Mattermost/Slack 슬래시 명령): 명령 → 웹훅 URL
- 휴대폰: iOS 단축어 "URL 내용 가져오기"(방법 POST, 헤더 Authorization) → 홈 화면 버튼
- 다른 서버/스크립트: `curl` 한 줄

**보안 수칙**: 토큰은 16자 이상 임의 값 · 관리망에서만 접근(방화벽 또는 `WEBHOOK_BIND=<관리망IP>`) · `WEBHOOK_ALLOWED`에 failover/failback 넣지 않기 · 외부망에서 부를 땐 VPN이나 HTTPS 리버스 프록시 뒤에 두기

---

## 결과 받기 (알림)

`.env`에 `NOTIFY_WEBHOOK`을 넣으면 성공·실패·실행 거부 모두 메시지가 옵니다.
```
✅ aDR drill [aDR-Auto-SCP-Test] 완료
단계: drill_start → verify → drill_cleanup → clear_state
소요 11분 32초 · adr-runner
```
| `NOTIFY_FORMAT` | `NOTIFY_WEBHOOK` |
|---|---|
| `slack` | Slack Incoming Webhook URL |
| `mattermost` | Mattermost Incoming Webhook URL |
| `teams` | Teams Incoming Webhook(커넥터) URL |
| `telegram` | `https://api.telegram.org/bot<토큰>/sendMessage` + `NOTIFY_CHAT_ID` |
| `generic` | 아무 URL (`{"ok":true,"text":"..."}` POST) |

## 안전장치 (어떤 트리거든 공통)

- 같은 폴더에서 동시에 두 번 돌지 않음 (두 번째는 종료 코드 3)
- 계획이 ready가 아니면 시작하지 않고 알림 (다른 DR 작업 중이면 건드리지 않음)
- 서비스 확인이 실패해도 드릴 환경은 정리
- 작업 실패·타임아웃이면 즉시 중단하고 알림. 이후 `./trigger.sh cleanup`으로 정리
- failover/failback은 막혀 있음
