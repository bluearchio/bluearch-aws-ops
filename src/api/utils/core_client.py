"""Client helpers for the local bluearch-aws-core runtime."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import requests


DEFAULT_CORE_URL = "http://127.0.0.1:8094"
DEFAULT_CORE_PORT = 8094
DEFAULT_TOKEN_PATH = Path.home() / ".bluearch-core" / "runtime" / "api-token"
# Release-owned product requirement. Bump this only when the BlueArch CLI starts
# using a bluearch-aws-core API or behavior that older core versions do not support.
DEFAULT_MINIMUM_CORE_VERSION = "0.2.6"
MINIMUM_CORE_VERSION = os.environ.get("BLUEARCH_MINIMUM_CORE_VERSION", DEFAULT_MINIMUM_CORE_VERSION)
PROD_CORE_INSTALL_URL = "brew install bluearchio/tap/bluearch-aws-core"
DEV_CORE_INSTALL_URL = "pipx install -e ../bluearch-aws-core"


class CoreRuntimeError(RuntimeError):
    """Raised when the required local core runtime is unavailable."""


def get_core_url() -> str:
    return os.environ.get("BLUEARCH_CORE_URL", DEFAULT_CORE_URL).rstrip("/")


def get_core_browser_url(hostname: str | None = None) -> str:
    configured = os.environ.get("BLUEARCH_CORE_PUBLIC_URL")
    if configured:
        return configured.rstrip("/")
    if hostname in ("localhost", "127.0.0.1"):
        return f"http://{hostname}:{DEFAULT_CORE_PORT}"
    return get_core_url()


def get_service_token_path() -> Path:
    return Path(os.environ.get("BLUEARCH_CORE_TOKEN_PATH", str(DEFAULT_TOKEN_PATH))).expanduser()


def read_service_token() -> str:
    token_path = get_service_token_path()
    try:
        return token_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise CoreRuntimeError(
            f"bluearch-aws-core service token was not found at {token_path}. "
            "Start bluearch-aws-core first with `bluearch-aws-core start --daemon`."
        ) from exc


def request_core(method: str, path: str, *, service_token: bool = True, timeout: float = 5.0, **kwargs) -> Any:
    response = request_core_response(method, path, service_token=service_token, timeout=timeout, **kwargs)
    if not response.content:
        return None
    return response.json()


def request_core_response(
    method: str,
    path: str,
    *,
    service_token: bool = True,
    timeout: float = 5.0,
    raise_for_status: bool = True,
    **kwargs,
):
    headers = dict(kwargs.pop("headers", {}) or {})
    if service_token:
        headers["Authorization"] = f"Bearer {read_service_token()}"
    url = f"{get_core_url()}{path}"
    try:
        response = requests.request(method, url, headers=headers, timeout=timeout, **kwargs)
    except requests.RequestException as exc:
        raise CoreRuntimeError(f"bluearch-aws-core is not reachable at {get_core_url()}: {exc}") from exc
    if raise_for_status and response.status_code >= 400:
        raise CoreRuntimeError(f"bluearch-aws-core request failed: {response.status_code} {response.text}")
    return response


def check_core_dependency(app_name: str = "bluearch", minimum_version: str | None = None) -> dict[str, Any]:
    minimum_version = minimum_version or MINIMUM_CORE_VERSION
    try:
        status = request_core(
            "GET",
            f"/api/v1/core/dependency/status?app={app_name}&minimum_version={minimum_version}",
            service_token=False,
            timeout=2.0,
        )
    except CoreRuntimeError:
        health = request_core("GET", "/api/v1/core/health", service_token=False, timeout=2.0)
        version = health.get("version", "unknown")
        compatible = _is_development_version(version) or _version_tuple(version) >= _version_tuple(minimum_version)
        status = {
            "app": app_name,
            "core_installed": True,
            "core_running": True,
            "compatible": compatible,
            "core_version": version,
            "minimum_required_core_version": minimum_version,
            "message": "BlueArch Core is running." if compatible else "BlueArch Core is too old.",
        }
    if not status.get("compatible"):
        raise CoreRuntimeError(_format_core_update_message(app_name, status, minimum_version))
    return status


def _find_core_executable() -> str | None:
    """Return the public Core executable without launching legacy aliases."""
    configured = os.environ.get("BLUEARCH_CORE_BINARY")
    if configured:
        return configured if not _is_legacy_core_executable(configured) else None
    discovered = shutil.which("bluearch-aws-core")
    return discovered if discovered and not _is_legacy_core_executable(discovered) else None


def _is_legacy_core_executable(path: str) -> bool:
    legacy_names = {"bluearch", "bluearch-core"}
    try:
        return Path(path).name in legacy_names or Path(os.path.realpath(path)).name in legacy_names
    except OSError:
        return True


def get_installed_core_version() -> str | None:
    """Return the installed bluearch-aws-core binary version, if it exists."""
    binary = _find_core_executable()
    if not binary:
        return None
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return None
    output = f"{result.stdout}\n{result.stderr}"
    return _extract_version(output)


def core_version_satisfies(version: str | None, minimum_version: str | None = None) -> bool:
    if not version:
        return False
    minimum_version = minimum_version or MINIMUM_CORE_VERSION
    return _is_development_version(version) or _version_tuple(version) >= _version_tuple(minimum_version)


def core_install_url(development: bool = False) -> str:
    configured = os.environ.get("BLUEARCH_CORE_INSTALL_URL")
    if configured:
        return configured
    return DEV_CORE_INSTALL_URL if development else PROD_CORE_INSTALL_URL


def _extract_version(text: str) -> str | None:
    match = re.search(r"v?\d+\.\d+\.\d+(?:[-+][A-Za-z0-9_.-]+)?", text or "")
    if match:
        return match.group(0).lstrip("v")
    sha_match = re.search(r"\b[0-9a-f]{7,40}\b", text or "", re.IGNORECASE)
    return sha_match.group(0) if sha_match else None


def _format_core_update_message(app_name: str, status: dict[str, Any], minimum_version: str) -> str:
    core_version = status.get("core_version") or "unknown"
    app_label = app_name.replace("-", " ")
    return (
        f"bluearch-aws-core {core_version} is too old for {app_label}. "
        f"Required version: >= {minimum_version}. "
        "Install or update BlueArch Core with your installer, or with Homebrew: "
        "`brew install bluearchio/tap/bluearch-aws-core`; then restart it with "
        "`bluearch-aws-core start --daemon`."
    )


def _version_tuple(version: str) -> tuple[int, int, int]:
    cleaned = str(version).lstrip("v").split("-", 1)[0]
    values = []
    for part in cleaned.split(".")[:3]:
        try:
            values.append(int(part))
        except ValueError:
            values.append(0)
    while len(values) < 3:
        values.append(0)
    return tuple(values)


def _is_development_version(version: str) -> bool:
    value = str(version or "").strip()
    return value.upper() in {"LOCAL", "DEVELOPMENT"} or bool(re.fullmatch(r"[0-9a-f]{7,40}", value, re.IGNORECASE))
