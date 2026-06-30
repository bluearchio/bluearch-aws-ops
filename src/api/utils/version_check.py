"""Non-blocking startup version check with 24-hour cache.

Reads a cached version-check.json file from ~/.bluearch/ and prints a notice
if a newer version is available. Never blocks startup -- if the cache file is
missing, stale, or unreadable, this is silently skipped.

The cache file is written by the explicit ``bluearch --version`` flow
(see cli/version.py) or by a background refresh triggered here.
"""

import json
import os
import time
import threading
from typing import Optional

from utils.config import get_bluearch_home

_CACHE_FILENAME = "version-check.json"
_CACHE_MAX_AGE_SECONDS = 86400  # 24 hours


def _get_cache_path() -> str:
    return os.path.join(get_bluearch_home(), _CACHE_FILENAME)


def _read_cache() -> Optional[dict]:
    """Read the cached version check result. Returns None on any failure."""
    path = _get_cache_path()
    try:
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception:
        return None


def _write_cache(latest_version: str, current_version: str) -> None:
    """Persist the version check result to disk."""
    path = _get_cache_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = {
            "latest_version": latest_version,
            "current_version": current_version,
            "checked_at": time.time(),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except Exception:
        pass


def _fetch_latest_version(current_version: str) -> Optional[str]:
    """Call the releases endpoint and cache the result. Returns latest version or None."""
    try:
        import requests
        from aws.misc.version_controller import BASE_URL

        endpoint = f"{BASE_URL}/get-updates"
        response = requests.post(
            endpoint,
            headers={"Content-Type": "application/json"},
            json={"version": current_version},
            timeout=3,
        )
        response.raise_for_status()
        data = response.json()
        updates = data.get("updates")
        if updates and isinstance(updates, list) and len(updates) > 0:
            # The API returns newer versions in ascending order — pick the true max.
            def _parse(v: str) -> tuple:
                v = str(v or "").lstrip("v").strip()
                parts = []
                for segment in v.split("."):
                    try:
                        parts.append(int(segment))
                    except ValueError:
                        parts.append(0)
                return tuple(parts)

            latest = max(
                (u.get("version", "") for u in updates if u.get("version")),
                key=_parse,
                default="",
            )
            if latest:
                _write_cache(latest, current_version)
                return latest
        else:
            # No updates available -- cache current as latest
            _write_cache(current_version, current_version)
    except Exception:
        pass
    return None


def _background_refresh(current_version: str) -> None:
    """Refresh the cache in a background thread (fire-and-forget)."""
    thread = threading.Thread(
        target=_fetch_latest_version,
        args=(current_version,),
        daemon=True,
    )
    thread.start()


def _is_newer(latest: str, current: str) -> bool:
    """Simple version comparison. Handles vX.Y.Z and X.Y.Z formats."""
    def parse(v: str) -> tuple:
        v = v.lstrip("v").strip()
        parts = []
        for segment in v.split("."):
            try:
                parts.append(int(segment))
            except ValueError:
                parts.append(0)
        return tuple(parts)

    if current == "LOCAL":
        # Development build -- never nag
        return False

    try:
        return parse(latest) > parse(current)
    except Exception:
        return False


def check_for_update_notice() -> None:
    """Print a one-line update notice if a newer version is cached.

    This function is designed to be called on every CLI invocation. It will
    never block, never raise, and never print anything unless there is a
    genuinely newer version cached locally.
    """
    try:
        from aws.misc.version_controller import CURRENT_VERSION
        current = CURRENT_VERSION

        cache = _read_cache()
        if cache is None:
            # No cache yet -- kick off a background fetch for next time
            _background_refresh(current)
            return

        checked_at = cache.get("checked_at", 0)
        age = time.time() - checked_at

        if age > _CACHE_MAX_AGE_SECONDS:
            # Stale cache -- refresh in background, don't print stale data
            _background_refresh(current)
            return

        latest = cache.get("latest_version", "")
        if latest and _is_newer(latest, current):
            from rich.console import Console
            console = Console(stderr=True)
            console.print(
                f"[dim]Update available: [cyan]v{latest.lstrip('v')}[/cyan] "
                f"(current: v{current.lstrip('v')}). "
                f"Run [cyan]bluearch update[/cyan] to upgrade.[/dim]"
            )
    except Exception:
        # Never let a version check break the CLI
        pass
