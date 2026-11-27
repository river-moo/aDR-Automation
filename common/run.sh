#!/usr/bin/env bash
# 태스크 실행 래퍼 - 어느 위치에서 실행해도 이 폴더의 .env, vendor/, lib/를 사용
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$DIR/.python" ] || { echo "먼저 $DIR/install.sh 를 실행하세요" >&2; exit 1; }
. "$DIR/.python"
export PYTHONPATH="$DIR/lib:$DIR/vendor${PYTHONPATH:+:$PYTHONPATH}"
export SCP_ENV_FILE="${SCP_ENV_FILE:-$DIR/.env}"
export PYTHONDONTWRITEBYTECODE=1
SCRIPT="$DIR/main.py"
if [ "${1:-}" = "--webhook" ] && [ -f "$DIR/webhook.py" ]; then SCRIPT="$DIR/webhook.py"; shift; fi
exec "$PY" -S "$SCRIPT" "$@"   # -S: OS에 깔린 파이썬 패키지와 섞이지 않게 격리
