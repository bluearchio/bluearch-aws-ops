#!/usr/bin/env bash

set -euo pipefail

BINARY_NAME="${BINARY_NAME:-bluearch-aws-ops}"
SOURCE_ROOT="${SOURCE_ROOT:-src/api}"
ENTRY_IMPORT="${ENTRY_IMPORT:-bluearch}"
APP_OBJECT="${APP_OBJECT:-run}"
if [ -z "${ONEFILE_TEMPDIR:-}" ]; then
  ONEFILE_TEMPDIR="{HOME}/.bluearch-aws-ops/bin"
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENTRY_FILE="${BINARY_NAME//-/_}_nuitka_entry.py"

cd "$PROJECT_ROOT"
export PYTHONPATH="$SOURCE_ROOT${PYTHONPATH:+:$PYTHONPATH}"

echo "========================================="
echo "$BINARY_NAME macOS production build"
echo "Source root: $SOURCE_ROOT"
echo "Nuitka + LTO"
echo "========================================="

echo "Cleaning previous build artifacts..."
rm -rf dist build "$ENTRY_FILE" *.build *.dist *.onefile-build
mkdir -p dist

if [ -d "frontend" ] && [ -f "frontend/package.json" ]; then
  echo "Building frontend..."
  (
    cd frontend
    npm ci --prefer-offline 2>/dev/null || npm install
    npm run build
  )
fi

echo "Creating temporary CLI entry point..."
cat > "$ENTRY_FILE" <<PY
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "${SOURCE_ROOT}"))
from ${ENTRY_IMPORT} import ${APP_OBJECT}

if __name__ == "__main__":
    ${APP_OBJECT}()
PY

cleanup() {
  rm -f "$ENTRY_FILE"
}
trap cleanup EXIT

EXTRA_DATA_FLAGS=()
for rel_path in templates integrations web/static; do
  if [ -d "$SOURCE_ROOT/$rel_path" ]; then
    EXTRA_DATA_FLAGS+=("--include-data-dir=$SOURCE_ROOT/$rel_path=$rel_path")
    echo "[OK] Including $SOURCE_ROOT/$rel_path"
  fi
done

python -m nuitka --version

python -m nuitka \
  --standalone \
  --onefile \
  --output-filename="$BINARY_NAME" \
  --output-dir=dist \
  --onefile-tempdir-spec="$ONEFILE_TEMPDIR" \
  --onefile-no-compression \
  --include-package=aws \
  --include-package=cli \
  --include-package=commons \
  --include-package=database \
  --include-package=db \
  --include-package=modules \
  --include-package=routes \
  --include-package=utils \
  --include-package=web \
  --include-package=shellingham \
  --include-package-data=rich \
  --include-package-data=pydantic \
  --include-package-data=pydantic_core \
  "${EXTRA_DATA_FLAGS[@]}" \
  --follow-imports \
  --lto=yes \
  --assume-yes-for-downloads \
  --show-progress \
  "$ENTRY_FILE"

if [ ! -x "dist/$BINARY_NAME" ]; then
  echo "ERROR: expected binary not found at dist/$BINARY_NAME" >&2
  exit 1
fi

chmod 755 "dist/$BINARY_NAME"
"dist/$BINARY_NAME" --version
echo "[OK] Built dist/$BINARY_NAME"
