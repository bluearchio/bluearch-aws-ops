#!/usr/bin/env bash
set -euo pipefail

APP_NAME="BlueArch AWS Ops"
REPO="bluearchio/bluearch-aws-ops"
BINARY_NAME="bluearch-aws-ops"
ASSET_NAME="bluearch-aws-ops-linux-x86_64.tar.gz"
VERSION="${BLUEARCH_VERSION:-latest}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/bin}"

CORE_APP_NAME="BlueArch AWS Core"
CORE_REPO="bluearchio/bluearch-aws-core"
CORE_BINARY_NAME="bluearch-aws-core"
CORE_ASSET_NAME="bluearch-aws-core-linux-x86_64.tar.gz"
CORE_VERSION="${BLUEARCH_CORE_VERSION:-latest}"
CORE_INSTALL_POLICY="${BLUEARCH_INSTALL_CORE:-missing}"
TEMP_DIRS=()

cleanup() {
  local path
  for path in "${TEMP_DIRS[@]}"; do
    rm -rf "$path"
  done
}
trap cleanup EXIT

log() {
  printf '[bluearch] %s\n' "$*"
}

warn() {
  printf '[bluearch] warning: %s\n' "$*" >&2
}

fail() {
  printf '[bluearch] error: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

release_base_url() {
  local repo="$1"
  local version="$2"
  local project="${repo##*/}"
  local dist_base="${BLUEARCH_DIST_BASE_URL:-https://dist.bluearch.io}"
  printf '%s/releases/%s/%s' "${dist_base%/}" "$project" "$version"
}

download_file() {
  local url="$1"
  local output="$2"
  local token="${GITHUB_TOKEN:-${GH_TOKEN:-}}"
  if [[ -n "$token" && "$url" == https://github.com/* ]]; then
    curl -fsSL -H "Authorization: Bearer ${token}" "$url" -o "$output"
  else
    curl -fsSL "$url" -o "$output"
  fi
}

verify_checksum() {
  local checksums_file="$1"
  local asset_name="$2"
  local selected_file="$3"
  local matching_lines
  local match_count
  local digest
  local filename
  local extra

  matching_lines="$(awk -v asset="$asset_name" '$2 == asset { print }' "$checksums_file")"
  match_count="$(printf '%s\n' "$matching_lines" | awk 'NF { count += 1 } END { print count + 0 }')"
  [[ "$match_count" -eq 1 ]] || fail "SHA256SUMS must contain exactly one row for ${asset_name}"
  read -r digest filename extra <<< "$matching_lines"
  [[ -z "${extra:-}" && "$filename" == "$asset_name" && "$digest" =~ ^[0-9A-Fa-f]{64}$ ]] || \
    fail "SHA256SUMS contained an invalid row for ${asset_name}"

  printf '%s  %s\n' "$digest" "$asset_name" > "$selected_file"
  (cd "$(dirname "$selected_file")" && sha256sum -c "$(basename "$selected_file")")
}

install_release() {
  local app_name="$1"
  local repo="$2"
  local version="$3"
  local asset_name="$4"
  local binary_name="$5"
  local base_url
  local tmp_dir
  local archive_members
  local archive_member_count

  base_url="$(release_base_url "$repo" "$version")"
  tmp_dir="$(mktemp -d)"
  TEMP_DIRS+=("$tmp_dir")

  log "Downloading ${app_name} (${version})..."
  download_file "${base_url}/${asset_name}" "${tmp_dir}/${asset_name}"
  download_file "${base_url}/SHA256SUMS" "${tmp_dir}/SHA256SUMS" || \
    fail "Could not download required SHA256SUMS"
  verify_checksum "${tmp_dir}/SHA256SUMS" "$asset_name" "${tmp_dir}/SHA256SUMS.selected"

  archive_members="$(tar -tzf "${tmp_dir}/${asset_name}")"
  archive_member_count="$(printf '%s\n' "$archive_members" | awk 'NF { count += 1 } END { print count + 0 }')"
  if [[ "$archive_member_count" -ne 1 || "$archive_members" != "$binary_name" ]]; then
    fail "Archive must contain exactly one top-level ${binary_name}"
  fi

  mkdir -p "${tmp_dir}/extract"
  tar -xzf "${tmp_dir}/${asset_name}" -C "${tmp_dir}/extract" --no-same-owner --no-same-permissions

  local extracted_binary="${tmp_dir}/extract/${binary_name}"
  [[ -f "$extracted_binary" && ! -L "$extracted_binary" ]] || \
    fail "Archive payload is not one regular top-level ${binary_name}"

  mkdir -p "$INSTALL_DIR"
  install -m 0755 "$extracted_binary" "${INSTALL_DIR}/${binary_name}"
  log "Installed ${binary_name} to ${INSTALL_DIR}/${binary_name}"
}

binary_available() {
  command -v "$1" >/dev/null 2>&1 || [[ -x "${INSTALL_DIR}/$1" ]]
}

case "$(uname -s)" in
  Linux) ;;
  *) fail "This installer supports Linux only. On macOS, run 'brew trust --formula bluearchio/tap/bluearch-aws-core' and 'brew trust --formula bluearchio/tap/bluearch-aws-ops', then install bluearchio/tap/bluearch-aws-ops." ;;
esac

case "$(uname -m)" in
  x86_64|amd64) ;;
  *) fail "Unsupported architecture: $(uname -m). Current release assets support linux-x86_64." ;;
esac

require_command curl
require_command tar
require_command sha256sum
require_command install

case "$CORE_INSTALL_POLICY" in
  always)
    install_release "$CORE_APP_NAME" "$CORE_REPO" "$CORE_VERSION" "$CORE_ASSET_NAME" "$CORE_BINARY_NAME"
    ;;
  missing)
    if ! binary_available "$CORE_BINARY_NAME"; then
      install_release "$CORE_APP_NAME" "$CORE_REPO" "$CORE_VERSION" "$CORE_ASSET_NAME" "$CORE_BINARY_NAME"
    fi
    ;;
  skip)
    ;;
  *) fail "Invalid BLUEARCH_INSTALL_CORE value: ${CORE_INSTALL_POLICY}. Use missing, always, or skip." ;;
esac

install_release "$APP_NAME" "$REPO" "$VERSION" "$ASSET_NAME" "$BINARY_NAME"

if ! command -v "$BINARY_NAME" >/dev/null 2>&1; then
  case ":$PATH:" in
    *":$INSTALL_DIR:"*) ;;
    *) warn "${INSTALL_DIR} is not on PATH. Add it with: export PATH=\"${INSTALL_DIR}:\$PATH\"" ;;
  esac
fi

log "Start core with: ${CORE_BINARY_NAME} start --daemon"
log "Run the CLI with: ${BINARY_NAME} --help"
