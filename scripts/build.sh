#!/usr/bin/env bash
# 태스크별 배포 패키지 생성: dist/<task>.tar.gz, dist/<task>.zip, dist/SHA256SUMS
#   ./scripts/build.sh            # 전체
#   ./scripts/build.sh 01 03      # 일부 (번호 접두어)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST="$ROOT/dist"
VERSION="$(cat "$ROOT/VERSION")"
mkdir -p "$DIST"

build_one() {
  local src="$1" name; name="$(basename "$src")"
  ( . "$src/task.conf"
    local stage="$DIST/.stage/$name"
    rm -rf "$stage" && mkdir -p "$stage/lib"
    cp "$src/main.py" "$src/README.md" "$src/task.conf" "$stage/"
    [ -f "$src/endpoints.json" ] && cp "$src/endpoints.json" "$stage/"
    for f in $COMMON; do cp "$ROOT/common/$f" "$stage/lib/"; done
    cp "$ROOT/common/install.sh" "$ROOT/common/run.sh" "$stage/"
    if [ "$NEEDS_SCP" = "1" ]; then
      cat "$ROOT/common/env.example" > "$stage/.env.example"
      [ -f "$src/env.extra" ] && cat "$src/env.extra" >> "$stage/.env.example"
    else
      echo "# 이 태스크는 설정값이 필요 없습니다" > "$stage/.env.example"
      mkdir -p "$stage/har" "$stage/out"
    fi
    if [ "$NEEDS_DEPS" = "1" ]; then
      mkdir -p "$stage/wheels" && cp "$ROOT"/wheels/*.whl "$ROOT/wheels/requirements.txt" "$stage/wheels/"
    fi
    echo "$VERSION" > "$stage/VERSION"
    chmod +x "$stage/install.sh" "$stage/run.sh" "$stage/main.py"
    ( cd "$DIST/.stage"
      tar --owner=0 --group=0 -czf "$DIST/$name.tar.gz" "$name"
      rm -f "$DIST/$name.zip"; zip -qr "$DIST/$name.zip" "$name" )
    echo "  $name.tar.gz / .zip"
  )
}

echo "build v$VERSION"
for t in "$ROOT"/tasks/*/; do
  t="${t%/}"; n="$(basename "$t")"
  if [ $# -gt 0 ]; then
    match=0; for p in "$@"; do [[ "$n" == "$p"* ]] && match=1; done
    [ $match = 1 ] || continue
  fi
  build_one "$t"
done
rm -rf "$DIST/.stage"
( cd "$DIST" && sha256sum *.tar.gz *.zip > SHA256SUMS )
echo "-> $DIST"
