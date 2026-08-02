#!/usr/bin/env bash
set -euo pipefail

ZIP_PATH="${1:-}"
PUBLIC_BINARY_NAME="${2:-}"
EXPECTED_VERSION="${3:-}"

if [[ -z "$ZIP_PATH" || -z "$PUBLIC_BINARY_NAME" || -z "$EXPECTED_VERSION" ]]; then
  echo "usage: verify_macos_artifact.sh ZIP_PATH PUBLIC_BINARY_NAME EXPECTED_VERSION" >&2
  exit 2
fi
[[ -f "$ZIP_PATH" ]] || { echo "missing artifact: $ZIP_PATH" >&2; exit 1; }
[[ "$PUBLIC_BINARY_NAME" != */* ]] || { echo "binary name must not contain a path" >&2; exit 1; }

members="$(zipinfo -1 "$ZIP_PATH")"
member_count="$(printf '%s\n' "$members" | awk 'NF { count += 1 } END { print count + 0 }')"
if [[ "$member_count" -ne 1 || "$members" != "$PUBLIC_BINARY_NAME" ]]; then
  echo "archive must contain exactly one top-level $PUBLIC_BINARY_NAME" >&2
  exit 1
fi

VERIFY_DIR="$(mktemp -d)"
trap 'rm -rf "$VERIFY_DIR"' EXIT
ditto -x -k "$ZIP_PATH" "$VERIFY_DIR"
BINARY_PATH="$VERIFY_DIR/$PUBLIC_BINARY_NAME"
[[ -f "$BINARY_PATH" && -x "$BINARY_PATH" && ! -L "$BINARY_PATH" ]] || {
  echo "archive payload is not one regular executable $PUBLIC_BINARY_NAME" >&2
  exit 1
}

codesign --verify --deep --strict --verbose=2 "$BINARY_PATH"
codesign -vvvv \
  -R="notarized" \
  --check-notarization \
  "$BINARY_PATH"
ARCHITECTURES="$(lipo -archs "$BINARY_PATH")"
[[ "$ARCHITECTURES" == "arm64" ]] || {
  echo "expected an arm64-only binary, found: $ARCHITECTURES" >&2
  exit 1
}
VERSION_OUTPUT="$("$BINARY_PATH" --version)"
VERSION_LINE="${VERSION_OUTPUT%%$'\n'*}"
[[ "$VERSION_LINE" == "$PUBLIC_BINARY_NAME $EXPECTED_VERSION" ]] || {
  echo "artifact version identity must be: $PUBLIC_BINARY_NAME $EXPECTED_VERSION" >&2
  exit 1
}
"$BINARY_PATH" --help >/dev/null
"$BINARY_PATH" scan --help >/dev/null
