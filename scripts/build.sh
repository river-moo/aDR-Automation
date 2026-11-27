#!/usr/bin/env bash
# 태스크별 배포 패키지 생성: dist/<task>.tar.gz, dist/<task>.zip, dist/SHA256SUMS
#   ./scripts/build.sh            # 전체
#   ./scripts/build.sh 01 03      # 일부 (번호 접두어)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST="$ROOT/dist"
VERSION="$(cat "$ROOT/VERSION")"
mkdir -p "$DIST"

# macOS(bsdtar) / Linux(GNU tar) 모두 지원
export COPYFILE_DISABLE=1            # macOS: ._ 메타파일이 tar에 섞이지 않게
if tar --version 2>/dev/null | grep -q GNU; then
  TAR_OWNER=(--owner=0 --group=0)
else
  TAR_OWNER=(--uid 0 --gid 0 --uname root --gname root)
fi
if command -v sha256sum >/dev/null; then SHA=(sha256sum); else SHA=(shasum -a 256); fi

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
      tar "${TAR_OWNER[@]}" -czf "$DIST/$name.tar.gz" "$name"
      rm -f "$DIST/$name.zip"; zip -qrX "$DIST/$name.zip" "$name" -x "*.DS_Store" )
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
( cd "$DIST" && "${SHA[@]}" *.tar.gz *.zip > SHA256SUMS )
echo "-> $DIST"
