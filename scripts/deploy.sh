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
# 최소 설치 OS 대응: tar가 없으면 설치 시도, 안 되면 python3 tarfile로 풀기
extract() {
  if command -v tar >/dev/null 2>&1; then tar xzf "\$1"; return; fi
  for pm in dnf yum apt-get zypper; do
    if command -v \$pm >/dev/null 2>&1; then
      echo "[deploy] tar가 없어 \$pm 으로 설치합니다"
      case \$pm in apt-get) apt-get install -y tar ;; zypper) zypper -n install tar ;; *) \$pm install -y tar ;; esac >/dev/null 2>&1 || true
      break
    fi
  done
  if command -v tar >/dev/null 2>&1; then tar xzf "\$1"
  elif command -v python3 >/dev/null 2>&1; then python3 -m tarfile -e "\$1" .
  else echo "[deploy] tar도 python3도 없습니다. 'dnf install -y tar python3' 후 다시 실행하세요" >&2; exit 1; fi
}
for t in .incoming/*.tar.gz; do
  n=\$(basename "\$t" .tar.gz)
  if [ -d "\$n" ]; then
    keepdir=".backup/\$n-\$(date +%Y%m%d%H%M%S)"
    mkdir -p "\$keepdir"
    for keep in .env endpoints.json reports har out; do
      if [ -e "\$n/\$keep" ]; then cp -a "\$n/\$keep" "\$keepdir/"; fi
    done
  else
    keepdir=""
  fi
  extract "\$t"
  if [ -n "\$keepdir" ]; then cp -a "\$keepdir"/. "\$n"/; fi
  ( cd "\$n" && ./install.sh )
done
rm -rf .incoming
echo "설치 위치: $DEST"
EOF
