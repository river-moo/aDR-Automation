#!/usr/bin/env bash
# 무인 실행용 트리거 - cron, systemd timer, Jenkins, Ansible, ssh, webhook.py 가 모두 이 파일을 호출
#   ./trigger.sh drill                 # .env의 ADR_PLAN으로 드릴 전체 (시작→확인→정리→Ready)
#   ./trigger.sh cleanup               # 테스트 종료 + 상태 정리
#   ./trigger.sh clear                 # 상태만 Ready로
#   ./trigger.sh drill -p 다른계획      # 계획 지정
# - 같은 폴더에서 동시에 두 번 실행되지 않게 잠금 (이미 실행 중이면 종료 코드 3)
# - 실행 로그: logs/YYYYmmdd-HHMMSS-<동작>.log (LOG_KEEP_DAYS 지나면 삭제), 결과: logs/last-result.json
# - 종료 코드: 0 성공 / 1 점검 실패·거부 / 2 오류 / 3 이미 실행 중 / 130 중단
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACTION="${1:?사용법: trigger.sh drill|cleanup|clear|status|list [옵션]}"; shift

envval() {  # .env에서 값 하나 읽기 (source 하지 않음 - 비밀번호 특수문자 안전)
  local v; v="$(grep -E "^$1=" "${SCP_ENV_FILE:-$DIR/.env}" 2>/dev/null | tail -1 | cut -d= -f2-)"
  v="${v%\"}"; v="${v#\"}"; printf '%s' "${v:-$2}"
}
LOG_DIR="$(envval LOG_DIR "$DIR/logs")"
KEEP="$(envval LOG_KEEP_DAYS 30)"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/$(date +%Y%m%d-%H%M%S)-$ACTION.log"

case "$ACTION" in
  list|status) exec "$DIR/run.sh" "$ACTION" "$@" ;;
  drill|cleanup|clear|failover|failback) ;;
  *) echo "알 수 없는 동작: $ACTION" >&2; exit 1 ;;
esac

# 잠금
LOCK="$LOG_DIR/.adr.lock"
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK"
  flock -n 9 || { echo "[trigger] 이미 실행 중입니다 ($LOCK)" | tee -a "$LOG"; exit 3; }
else
  mkdir "$LOCK.d" 2>/dev/null || { echo "[trigger] 이미 실행 중입니다 ($LOCK.d)" | tee -a "$LOG"; exit 3; }
  trap 'rmdir "$LOCK.d" 2>/dev/null' EXIT
fi

{
  echo "[trigger] $(date '+%F %T') $ACTION 시작 (호출: ${TRIGGER_SOURCE:-manual}, 사용자: $(id -un), 호스트: $(hostname))"
  "$DIR/run.sh" "$ACTION" --execute "$@" < /dev/null
  rc=$?
  echo "[trigger] $(date '+%F %T') $ACTION 종료 코드 $rc"
  exit $rc
} 2>&1 | tee -a "$LOG"
rc=${PIPESTATUS[0]}
ln -sf "$(basename "$LOG")" "$LOG_DIR/latest.log" 2>/dev/null || true
find "$LOG_DIR" -name '*.log' -type f -mtime +"$KEEP" -delete 2>/dev/null || true
exit "$rc"
