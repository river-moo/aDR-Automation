#!/usr/bin/env bash
# 태스크 설치 스크립트 - 압축 푼 폴더에서 ./install.sh
# - python3(3.7+) 확인, 없으면 OS 패키지 관리자로 설치 시도
# - 함께 들어있는 wheels/를 vendor/에 풀어서 pip·인터넷 없이 의존성 구성
# - .env.example -> .env 생성 (이미 있으면 유지)
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
. ./task.conf

say() { printf '\033[1;34m[install]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[install]\033[0m %s\n' "$*" >&2; exit 1; }

# ---- 1. python3
find_python() {
  for p in python3 python3.12 python3.11 python3.10 python3.9 python3.8 python3.7; do
    if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys; sys.exit(0 if sys.version_info >= (3,7) else 1)' 2>/dev/null; then
      command -v "$p"; return 0
    fi
  done
  return 1
}
PY="$(find_python || true)"
if [ -z "$PY" ]; then
  say "python3(3.7+)가 없어 설치를 시도합니다"
  [ "$(id -u)" -eq 0 ] || die "root 권한이 필요합니다: sudo ./install.sh"
  if command -v dnf >/dev/null; then dnf install -y python3
  elif command -v yum >/dev/null; then yum install -y python3
  elif command -v apt-get >/dev/null; then apt-get update && apt-get install -y python3
  elif command -v zypper >/dev/null; then zypper -n install python3
  else die "패키지 관리자를 찾지 못했습니다. python3를 직접 설치하세요"; fi
  PY="$(find_python)" || die "python3 설치 실패 (폐쇄망이면 OS ISO 저장소를 연결하세요)"
fi
say "python: $PY ($("$PY" -V 2>&1))"

# ---- 2. 의존성 (vendor/)
if [ "${NEEDS_DEPS:-0}" = "1" ]; then
  ARCH="$(uname -m)"; OS="$(uname -s)"
  say "의존성 구성 (arch=$ARCH, 오프라인 wheel)"
  rm -rf vendor && mkdir -p vendor
  "$PY" - "$ARCH" "$OS" <<'PYEOF'
import glob, sys, zipfile
arch, osname = sys.argv[1], sys.argv[2]
picked = []
for w in sorted(glob.glob("wheels/*.whl")):
    name = w.rsplit("/", 1)[-1]
    if "manylinux" in name and (osname != "Linux" or arch not in name):
        continue  # 다른 OS/아키텍처용 바이너리
    zipfile.ZipFile(w).extractall("vendor")
    picked.append(name)
print("\n".join("  - " + p for p in picked))
if not any(p.startswith("pycryptodome") for p in picked):
    print("  - pycryptodome 바이너리 없음(%s/%s) -> 내장 순수 파이썬 RSA로 동작 (기능 동일)" % (osname, arch))
PYEOF
  PYTHONPATH="$DIR/vendor:$DIR/lib" "$PY" -S -c 'import requests, urllib3; print("  requests", requests.__version__, "/ urllib3", urllib3.__version__)' \
    || die "의존성 로드 실패"
fi

# ---- 3. .env
if [ ! -f .env ]; then
  cp .env.example .env
  say ".env 생성됨 -> 값 수정 필요: vi $DIR/.env"
else
  say ".env 유지 (기존 값 사용)"
  # 새 버전에서 추가된 설정 키는 기본값으로 뒤에 붙임 (기존 값은 건드리지 않음)
  added="$(awk -F= 'NR==FNR { if ($0 ~ /^[A-Z_][A-Z0-9_]*=/) have[$1]=1; next }
                   $0 ~ /^[A-Z_][A-Z0-9_]*=/ && !($1 in have) { print }' .env .env.example)"
  if [ -n "$added" ]; then
    { echo ""; echo "# ---- $(cat VERSION 2>/dev/null) 업데이트로 추가된 설정 (설명은 .env.example 참고)"; echo "$added"; } >> .env
    say "새 설정 키 추가됨: $(echo "$added" | cut -d= -f1 | tr '\n' ' ')"
  fi
fi
chmod 600 .env
chmod +x run.sh main.py 2>/dev/null || true
echo "PY=\"$PY\"" > .python
say "완료. 실행: $DIR/run.sh --help"
