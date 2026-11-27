# aDR-Automation · Sangfor SCP aDR 드릴 자동화

Sangfor **SCP 6.11.3 + aDR** 환경에서 DR 드릴을 **명령어 한 번**으로 돌립니다.
드릴 시작 → 완료 대기 → DR 쪽 서비스 확인 → 테스트 종료 → 상태 Ready 정리까지 사람 손 없이 진행돼요.

```bash
./trigger.sh drill          # 이 한 줄이면 끝 (cron·systemd·Jenkins·웹훅도 전부 이 파일을 호출)
```

- 공식 OpenAPI에는 드릴 실행 API가 없어서, 콘솔(4430)이 쓰는 내부 API를 분석해 사용합니다. **SCP 6.11.3 실장비에서 검증 완료** (2026-11-28)
- 태스크마다 `tar.gz`/`zip` 하나로 배포돼요. 리눅스에 풀고 `./install.sh`만 실행하면 됩니다. **pip·인터넷 불필요**
- 환경마다 다른 값은 전부 `.env` 한 파일에 있어요. 코드는 고칠 필요가 없습니다

## 문서

| 문서 | 내용 |
|---|---|
| [docs/STEP-BY-STEP.md](docs/STEP-BY-STEP.md) | **처음부터 끝까지 단계별 실행** (빌드 → 설치 → 점검 → dry-run → 실행) |
| [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md) | **환경이 바뀔 때 고칠 값** 전체 목록 |
| [docs/TRIGGERS.md](docs/TRIGGERS.md) | **트리거 방법** (수동, ssh, cron, systemd timer, Jenkins, Ansible, 웹훅) |
| [docs/API-MAP.md](docs/API-MAP.md) | 사용하는 OpenAPI / 콘솔 내부 API, 상태값, 로그인 흐름 |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | 오류 메시지별 원인과 조치 |
| [CHANGELOG.md](CHANGELOG.md) | 버전별 변경 사항 |
| [docs/aDR-Drill-Automation-Guide-v1.0.0.docx](docs/aDR-Drill-Automation-Guide-v1.0.0.docx) | **종합 정리 Word 문서** (전체 내용을 한 문서로) |

## 태스크

| # | 태스크 | 하는 일 | SCP 변경 |
|---|---|---|---|
| 01 | [scp-connect-check](tasks/01-scp-connect-check) | 접속·인증(OpenAPI, 콘솔 로그인) 점검 | 없음 |
| 02 | [har-capture](tasks/02-har-capture) | 콘솔 HAR에서 내부 API 추출 (SCP 버전이 바뀌어 API를 다시 찾을 때) | 없음 |
| 03 | [adr-precheck](tasks/03-adr-precheck) | DR 정책·보호 VM 점검 리포트 | 없음 |
| 04 | [adr-drill](tasks/04-adr-drill) | **드릴 / 테스트 종료 / 상태 정리**, 트리거·웹훅·알림 | **있음** |

평소 운영에 필요한 건 **01(처음 한 번) + 04**입니다.

## 3분 요약

```bash
# 1) 빌드 (Mac 또는 리눅스, 저장소에서)
./scripts/build.sh

# 2) 실행 서버로 배포 + 설치 (기본 /opt/sangfor-scp)
./scripts/deploy.sh root@<실행서버IP> 01 04

# 3) 실행 서버에서 설정 (두 폴더 모두)
vi /opt/sangfor-scp/01-scp-connect-check/.env     # SCP_HOST, SCP_AK, SCP_SK, SCP_USER, SCP_PASS
vi /opt/sangfor-scp/04-adr-drill/.env             # 위와 같은 값 + ADR_PLAN

# 4) 점검 → 미리보기 → 실행
/opt/sangfor-scp/01-scp-connect-check/run.sh --console-login
/opt/sangfor-scp/04-adr-drill/run.sh list
/opt/sangfor-scp/04-adr-drill/run.sh drill                 # dry-run (아무것도 안 바뀜)
/opt/sangfor-scp/04-adr-drill/trigger.sh drill             # 실제 실행
```

## 지원 환경

| 항목 | 지원 |
|---|---|
| 실행 서버 OS | Rocky/RHEL 8·9, CentOS 7, Debian 11·12, Ubuntu 20.04+ (최소 설치 OS 포함). macOS도 실행 가능 (python3 필요) |
| CPU | x86_64, aarch64 (그 외 아키텍처도 순수 파이썬 RSA로 동작) |
| Python | 3.7 이상 (없으면 `install.sh`가 dnf/yum/apt/zypper로 설치 시도) |
| 네트워크 | 실행 서버 → SCP **443**(OpenAPI), **4430**(콘솔). 인터넷 불필요 |
| SCP | 6.11.3에서 검증. 다른 버전은 `docs/API-MAP.md`의 재확인 절차 참고 |

## 빌드 · 배포

```bash
./scripts/build.sh                          # dist/에 태스크별 tar.gz, zip, SHA256SUMS
./scripts/build.sh 04                       # 일부만
./scripts/deploy.sh root@HOST               # 전체 배포
./scripts/deploy.sh root@HOST 04            # 04만 갱신 (.env, logs, reports 보존)
DEST=/srv/adr ./scripts/deploy.sh root@HOST # 설치 경로 변경
```

업데이트 때 새 설정 키가 생기면 `install.sh`가 기존 `.env` 뒤에 기본값으로 자동 추가합니다(기존 값은 유지).

## 저장소 구조

```
common/      공통 코드 (scp_client.py, adr_common.py, install.sh, run.sh, env.example)
tasks/NN-*/  태스크별 main.py, README.md, task.conf, env.extra (+ 04: endpoints.json, trigger.sh, webhook.py, systemd/, cron.example)
wheels/      오프라인 의존성 (requirements.txt에 버전 고정)
scripts/     build.sh, deploy.sh
docs/        운영 문서
```

## 보안

- `.env`, 로그, HAR, `dist/`는 `.gitignore`로 커밋되지 않습니다. **AK/SK·비밀번호는 저장소에 넣지 마세요**
- `.env`는 설치 시 `chmod 600`. 실행 계정만 읽을 수 있게 두세요
- 웹훅을 켜면 `WEBHOOK_TOKEN`을 긴 임의 값으로, 접근은 관리망에서만 허용하세요
- failover/failback은 아직 API 미확인이라 **실행이 막혀 있습니다** (안전장치)
