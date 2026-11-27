# 변경 이력

## 1.0.0 (2026-11-28)

SCP 6.11.3 실장비에서 드릴 시작 → 테스트 종료 → 상태 정리 전 과정 검증 완료.

**추가**
- `trigger.sh`: 무인 실행용 단일 진입점 (잠금, 로그 파일, 보관 기간, 종료 코드)
- `webhook.py`: HTTP 요청으로 실행 (토큰 인증, 허용 동작 제한, `/status`, `/health`)
- 결과 알림: Slack · Mattermost · Teams · Telegram · 일반 웹훅 (`NOTIFY_WEBHOOK`)
- systemd service/timer, cron 예시
- 04 `--step`(단계마다 Enter), `status` 명령, `ADR_PLAN`(기본 계획), `logs/last-result.json`
- 순수 파이썬 RSA: pycryptodome 바이너리가 없는 OS/CPU(macOS, 기타 아키텍처)에서도 로그인 가능
- 업데이트 시 `.env`에 새 설정 키 자동 추가
- 문서: 단계별 실행, 환경별 변경값, 트리거, API 맵, 문제 해결

**변경**
- `env.example`의 `SCP_HOST`를 비움 (특정 환경 값 제거)
- `deploy.sh`: `endpoints.json`을 새 버전으로 교체하고 이전 파일은 `.backup/`에 보관. `logs/` 보존

## 0.x (2026-11)

- 01 접속·인증 점검, EC2 서명(6.11.3: 쿼리 미서명), 콘솔 로그인(`/ticket`, salt, RSA)
- 02 HAR 분석, 03 DR 정책 점검
- 04 콘솔 내부 API 분석(JS), 드릴 본문 자동 생성, 테스트 종료·상태 정리, `failed` 상태 대응
