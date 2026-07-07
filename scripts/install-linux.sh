#!/usr/bin/env bash
set -euo pipefail

APP_NAME="BlueArch AWS Ops"
REPO="bluearchio/bluearch-aws-ops"
BINARY_NAME="bluearch"
ASSET_NAME="bluearch-linux-x86_64.tar.gz"
VERSION="${BLUEARCH_VERSION:-latest}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/bin}"

CORE_APP_NAME="BlueArch AWS Core"
CORE_REPO="bluearchio/bluearch-aws-core"
CORE_BINARY_NAME="bluearch-core"
CORE_ASSET_NAME="bluearch-core-linux-x86_64.tar.gz"
CORE_VERSION="${BLUEARCH_CORE_VERSION:-latest}"
CORE_INSTALL_POLICY="${BLUEARCH_INSTALL_CORE:-missing}"

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

  awk -v asset="$asset_name" '$2 == asset { print }' "$checksums_file" > "$selected_file"
  if [[ ! -s "$selected_file" ]]; then
    warn "SHA256SUMS did not contain ${asset_name}; continuing without checksum verification"
    return
  fi

  sha256sum -c "$selected_file"
}

install_release() {
  local app_name="$1"
  local repo="$2"
  local version="$3"
  local asset_name="$4"
  local binary_name="$5"
  local base_url
  local tmp_dir

  base_url="$(release_base_url "$repo" "$version")"
  tmp_dir="$(mktemp -d)"

  log "Downloading ${app_name} (${version})..."
  download_file "${base_url}/${asset_name}" "${tmp_dir}/${asset_name}"

  if download_file "${base_url}/SHA256SUMS" "${tmp_dir}/SHA256SUMS"; then
    (cd "$tmp_dir" && verify_checksum "SHA256SUMS" "$asset_name" "SHA256SUMS.selected")
  else
    warn "Could not download SHA256SUMS; continuing without checksum verification"
  fi

  mkdir -p "${tmp_dir}/extract"
  tar -xzf "${tmp_dir}/${asset_name}" -C "${tmp_dir}/extract"

  local extracted_binary="${tmp_dir}/extract/${binary_name}"
  if [[ ! -f "$extracted_binary" ]]; then
    extracted_binary="$(find "${tmp_dir}/extract" -type f -name "$binary_name" | head -n 1)"
  fi
  [[ -n "${extracted_binary:-}" && -f "$extracted_binary" ]] || fail "Archive did not contain ${binary_name}"

  mkdir -p "$INSTALL_DIR"
  install -m 0755 "$extracted_binary" "${INSTALL_DIR}/${binary_name}"
  rm -rf "$tmp_dir"
  log "Installed ${binary_name} to ${INSTALL_DIR}/${binary_name}"
}

binary_available() {
  command -v "$1" >/dev/null 2>&1 || [[ -x "${INSTALL_DIR}/$1" ]]
}

case "$(uname -s)" in
  Linux) ;;
  *) fail "This installer supports Linux only. On macOS, use: brew install bluearchio/tap/bluearch-aws-ops" ;;
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
