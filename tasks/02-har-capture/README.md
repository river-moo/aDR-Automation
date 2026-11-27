# Task 02 · 콘솔 내부 API 캡처 정리

**요약**: SCP 웹 콘솔에서 aDR 동작(드릴 시작·정리, Failover 등)을 할 때 브라우저가 보내는 요청을 HAR 파일로 저장하고, 거기서 API 호출만 뽑아 정리합니다. 공식 OpenAPI(6.11.3)에는 DR 정책 **조회**만 있고 실행 API는 없어서, Task 04에 넣을 엔드포인트를 이렇게 찾아요. SCP에 접속하지 않고, 외부 패키지도 필요 없습니다.

## 설치·실행

```bash
tar xzf 02-har-capture.tar.gz && cd 02-har-capture
./install.sh
./run.sh har/02_drill_start.har -k protect,drill,disaster,recover -o out/02_drill_start.md
```

결과물 (`-o` 지정 시):
- `out/02_drill_start.md` — 사람이 읽는 카탈로그 (토큰·비밀번호 자동 마스킹)
- `out/02_drill_start.json` — 같은 내용 JSON
- `out/02_drill_start.endpoints-candidates.json` — **Task 04 `endpoints.json`에 옮겨 붙일 후보** (POST/PUT/DELETE만)

## 캡처 절차 (랩에서, Chrome)

1. SCP 콘솔 로그인 → F12 → **Network** → `Preserve log` 체크, 필터 `Fetch/XHR`
2. 동작을 하나씩 실행하고, 끝날 때마다 우클릭 → *Save all as HAR with content* → 목록 지우기(🚫)
   - `01_policy_view.har` DR 정책 상세 열기
   - `02_drill_start.har` DR 드릴 시작 → 완료까지 대기
   - `03_drill_status.har` 드릴 진행 화면 새로고침
   - `04_drill_cleanup.har` 드릴 정리
   - (랩이면) `05_failover.har`, `06_failback.har`
3. HAR을 이 폴더의 `har/`에 복사하고 위 명령 실행
4. 카탈로그에서 **인증 헤더** 항목 확인: `Authorization: Token`이면 그대로 사용 가능, 쿠키만 있으면 콘솔 세션 전용 API라 Task 04에 쿠키 인증을 추가해야 함

## 환경별로 수정할 값

없습니다. `-k`(키워드)만 동작에 맞게 바꾸세요.

## 주의

원본 HAR에는 세션 토큰이 그대로 들어 있어요. 공유는 마스킹된 `.md`/`.json`만 하고, 원본 `.har`은 정리 후 지우세요.
