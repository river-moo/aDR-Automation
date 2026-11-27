# sangfor-scp-automation

Sangfor SCP OpenAPI 기반 자동화 모음입니다. 기준 문서는 **SCP 6.11.3 OpenAPI (P20260430)** 예요.
태스크마다 독립 패키지(`tar.gz` / `zip`)로 빌드되고, 리눅스에 풀어서 `./install.sh`만 실행하면 됩니다.
python 의존성은 패키지 안에 wheel로 들어 있어서 **pip이나 인터넷 없이** 설치돼요.

## 태스크

| # | 태스크 | 하는 일 | SCP 변경 | 필요한 것 |
|---|---|---|---|---|
| 01 | [scp-connect-check](tasks/01-scp-connect-check) | 접속·인증·버전·리소스 풀·DR 정책 API 점검 | 없음 | AK/SK |
| 02 | [har-capture](tasks/02-har-capture) | 콘솔 HAR에서 내부 API 추출 → Task 04용 후보 생성 | 없음 | HAR 파일 |
| 03 | [adr-precheck](tasks/03-adr-precheck) | DR 정책·보호 VM 점검 리포트 (cron 가능) | 없음 | AK/SK |
| 04 | [adr-drill](tasks/04-adr-drill) | 드릴 / 정리 / Failover / Failback 실행 | **있음** | AK/SK + 캡처한 endpoints.json |

권장 순서: **01 → 03 → 02(랩에서 캡처) → 04(dry-run → 랩 실행)**

## OpenAPI 6.11.3에서 확인한 aDR 범위

| 기능 | 공식 API |
|---|---|
| DR 정책 목록·구성 | `GET /janus/20240725/protections` (6.11.1+) |
| 보호 VM | `GET /janus/20220725/servers?in_protection=1&protection_id=` |
| 작업 진행률 | `GET /janus/20180725/tasks/{task_id}` |
| 드릴 시작·정리, Failover, Failback | **없음** → Task 02로 캡처해서 Task 04에 등록 |

## 빌드 · 배포

```bash
./scripts/build.sh                          # dist/에 태스크별 tar.gz, zip, SHA256SUMS
./scripts/build.sh 01 03                    # 일부만
./scripts/deploy.sh root@192.168.0.240      # 서버로 복사 + 설치 (/opt/sangfor-scp)
./scripts/deploy.sh root@192.168.0.240 04   # 한 태스크만 갱신 (.env, endpoints.json, reports 보존)
DEST=/srv/scp ./scripts/deploy.sh root@HOST # 설치 경로 변경
```

수동 설치:
```bash
scp dist/01-scp-connect-check.tar.gz root@192.168.0.240:/opt/
ssh root@192.168.0.240
cd /opt && tar xzf 01-scp-connect-check.tar.gz && cd 01-scp-connect-check
./install.sh && vi .env && ./run.sh
```

## 환경이 바뀔 때 고칠 곳 한눈에 보기

| 파일 | 값 | 01 | 02 | 03 | 04 |
|---|---|:-:|:-:|:-:|:-:|
| `.env` | `SCP_HOST` (SCP IP) | ● | | ● | ● |
| `.env` | `SCP_AK`, `SCP_SK` | ● | | ● | ● |
| `.env` | `SCP_EC2_SIGN_QUERY` (01 점검 결과에 따라) | ○ | | ○ | ○ |
| `.env` | `SCP_AUTH=token` + `SCP_USER`/`SCP_PASS` (AK/SK 없을 때) | ○ | | ○ | ○ |
| `.env` | `REPORT_DIR` | | | ○ | |
| `.env` | `VERIFY_TARGETS` (DR 쪽 서비스 IP:포트) | | | | ● |
| `.env` | `TASK_TIMEOUT` | | | | ○ |
| `endpoints.json` | 캡처한 path / body / `verified` | | | | ● |

● 항상 수정 · ○ 필요할 때만. 값의 의미와 예시는 각 태스크 README에 있어요.

## 지원 환경

- Linux x86_64 / aarch64, Python 3.7+ (없으면 `install.sh`가 dnf/yum/apt/zypper로 설치 시도)
- Rocky/RHEL 8·9, CentOS 7, Debian 11·12, Ubuntu 20.04+ 기준. urllib3를 1.26 계열로 고정해서 OpenSSL 1.0.2 OS에서도 동작
- 실행 시 `python -S`로 OS 파이썬 패키지와 격리

## 저장소 구조

```
common/      공통 코드 (scp_client.py, adr_common.py, install.sh, run.sh, env.example)
tasks/NN-*/  태스크별 main.py, README.md, task.conf, env.extra, endpoints.json
wheels/      오프라인 의존성 (requirements.txt에 버전 고정)
scripts/     build.sh, deploy.sh
```

`.env`, HAR, 리포트, `dist/`는 `.gitignore`로 커밋되지 않습니다. **AK/SK·비밀번호는 저장소에 넣지 마세요.**
