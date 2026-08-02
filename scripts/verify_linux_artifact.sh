#!/usr/bin/env bash
set -euo pipefail

ARCHIVE_PATH="${1:-}"
PUBLIC_BINARY_NAME="${2:-}"
EXPECTED_VERSION="${3:-}"

if [[ -z "$ARCHIVE_PATH" || -z "$PUBLIC_BINARY_NAME" || -z "$EXPECTED_VERSION" ]]; then
  echo "usage: verify_linux_artifact.sh ARCHIVE_PATH PUBLIC_BINARY_NAME EXPECTED_VERSION" >&2
  exit 2
fi
[[ -f "$ARCHIVE_PATH" ]] || { echo "missing artifact: $ARCHIVE_PATH" >&2; exit 1; }
[[ "$PUBLIC_BINARY_NAME" != */* ]] || { echo "binary name must not contain a path" >&2; exit 1; }

mapfile -t members < <(tar -tzf "$ARCHIVE_PATH")
if [[ "${#members[@]}" -ne 1 || "${members[0]}" != "$PUBLIC_BINARY_NAME" ]]; then
  echo "archive must contain exactly one top-level $PUBLIC_BINARY_NAME" >&2
  exit 1
fi

VERIFY_DIR="$(mktemp -d)"
trap 'rm -rf "$VERIFY_DIR"' EXIT
tar -xzf "$ARCHIVE_PATH" -C "$VERIFY_DIR" --no-same-owner --no-same-permissions
BINARY_PATH="$VERIFY_DIR/$PUBLIC_BINARY_NAME"
[[ -f "$BINARY_PATH" && -x "$BINARY_PATH" && ! -L "$BINARY_PATH" ]] || {
  echo "archive payload is not one regular executable $PUBLIC_BINARY_NAME" >&2
  exit 1
}

file "$BINARY_PATH" | grep -Eq 'x86-64|x86_64'
VERSION_OUTPUT="$("$BINARY_PATH" --version)"
[[ "$VERSION_OUTPUT" == "$PUBLIC_BINARY_NAME $EXPECTED_VERSION" ]] || {
  echo "artifact version identity must be: $PUBLIC_BINARY_NAME $EXPECTED_VERSION" >&2
  exit 1
}
"$BINARY_PATH" --help >/dev/null
"$BINARY_PATH" scan --help >/dev/null
