#!/usr/bin/env bash
# 빌드한 패키지를 리눅스 서버로 복사하고 설치까지 실행
#   ./scripts/deploy.sh root@192.168.0.240                 # 전체 태스크 -> /opt/sangfor-scp
#   ./scripts/deploy.sh root@192.168.0.240 01 03           # 일부
#   DEST=/srv/scp ./scripts/deploy.sh root@10.0.0.5 04     # 설치 경로 변경
# 기존 .env, endpoints.json, reports/ 는 보존한다.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:?사용법: deploy.sh user@host [태스크번호...]}"; shift
DEST="${DEST:-/opt/sangfor-scp}"

[ -d "$ROOT/dist" ] || "$ROOT/scripts/build.sh"
pkgs=()
for f in "$ROOT"/dist/*.tar.gz; do
  n="$(basename "$f" .tar.gz)"
  if [ $# -gt 0 ]; then
    m=0; for p in "$@"; do [[ "$n" == "$p"* ]] && m=1; done; [ $m = 1 ] || continue
  fi
  pkgs+=("$f")
done
[ ${#pkgs[@]} -gt 0 ] || { echo "보낼 패키지가 없습니다"; exit 1; }

ssh "$TARGET" "mkdir -p '$DEST/.incoming'"
scp "${pkgs[@]}" "$TARGET:$DEST/.incoming/"
ssh "$TARGET" "bash -s" <<EOF
set -e
cd '$DEST'
for t in .incoming/*.tar.gz; do
  n=\$(basename "\$t" .tar.gz)
  if [ -d "\$n" ]; then
    mkdir -p ".backup/\$n-\$(date +%Y%m%d%H%M%S)"
    for keep in .env endpoints.json reports har out; do
      [ -e "\$n/\$keep" ] && cp -a "\$n/\$keep" ".backup/\$n-\$(date +%Y%m%d%H%M%S)/" || true
    done
    keepdir=\$(ls -dt .backup/\$n-* | head -1)
  else
    keepdir=""
  fi
  tar xzf "\$t"
  if [ -n "\$keepdir" ]; then cp -a "\$keepdir"/. "\$n"/; fi
  ( cd "\$n" && ./install.sh )
done
rm -rf .incoming
echo "설치 위치: $DEST"
EOF
