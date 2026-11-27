# Task 01 · SCP 접속·인증 점검

**요약**: 이 리눅스에서 SCP OpenAPI가 정상으로 불리는지 확인합니다. TCP 연결 → 인증(AK/SK 또는 토큰) → 버전 → 리소스 풀 → DR 정책 API 순서로 점검해요. 다른 태스크를 쓰기 전에 가장 먼저 돌리세요. 읽기만 하고 아무것도 바꾸지 않습니다.

## 설치·실행

```bash
tar xzf 01-scp-connect-check.tar.gz && cd 01-scp-connect-check
./install.sh          # python 확인, 의존성(오프라인) 구성, .env 생성
vi .env               # 아래 "수정할 값" 입력
./run.sh              # 점검
./run.sh --raw        # 응답 원문까지 출력
```

## 환경별로 수정할 값 (`.env`)

| 값 | 언제 바꾸나 | 예시 |
|---|---|---|
| `SCP_HOST` | **항상**. SCP 관리 IP (포트가 443이 아니면 `https://IP:PORT`) | `192.168.0.210` |
| `SCP_AK`, `SCP_SK` | **항상** (EC2 인증). SCP 기술지원에서 발급 | |
| `SCP_AUTH` | AK/SK 없이 계정으로 쓸 때 `token` | `auto` |
| `SCP_USER`, `SCP_PASS` | `SCP_AUTH=token`일 때만 | `admin` |
| `SCP_EC2_SIGN_QUERY` | 점검 결과가 `0`으로 바꾸라고 할 때 | `1` |
| `SCP_EC2_REGION`, `SCP_EC2_SERVICE` | 인증만 계속 실패할 때 본사에 값 확인 | `cn-south-1`, `sdk-api` |
| `SCP_VERIFY_TLS` | SCP에 정식 인증서가 있을 때 `1` | `0` |

## 실패할 때

- **TCP 실패**: 방화벽에서 이 서버 → SCP 443 허용 여부, `SCP_HOST` 확인
- **401/403**: AK/SK 오타, 또는 **시간 차이**. EC2 서명은 시각에 민감하니 `chronyc tracking` / `timedatectl`로 NTP를 맞추세요
- **버전은 OK인데 리소스 풀만 실패**: 쿼리 서명 문제. 스크립트가 자동 재시도하고 `SCP_EC2_SIGN_QUERY=0` 여부를 알려줍니다
- **DR 정책 조회 실패**: SCP 6.11.1 미만이거나 aDR 라이선스·권한이 없는 경우
