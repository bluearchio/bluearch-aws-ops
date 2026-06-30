"""Environment variable configuration and data directory paths.

All BlueArch CLI paths and settings are centralized here.
"""

import os
from typing import Optional


# ---------------------------------------------------------------------------
# Data directories
# ---------------------------------------------------------------------------

def get_bluearch_home() -> str:
    """Root config directory. Override with BLUEARCH_HOME env var."""
    return os.environ.get("BLUEARCH_HOME", os.path.join(os.path.expanduser("~"), ".bluearch"))


def get_data_dir() -> str:
    """SQLite database directory."""
    return os.path.join(get_bluearch_home(), "data")


def get_cache_dir() -> str:
    """Diskcache directory."""
    return os.path.join(get_bluearch_home(), "cache")


def get_config_dir() -> str:
    """Local session config directory."""
    return os.path.join(os.path.expanduser("~"), ".config", "bluearch-cli")


def get_license_key_file() -> str:
    """Path to the optional local activation file."""
    return os.path.join(get_bluearch_home(), "license.key")


def get_db_path() -> str:
    """Full path to the SQLite database."""
    return os.path.join(get_data_dir(), "bluearch.db")


# ---------------------------------------------------------------------------
# Environment variables
# ---------------------------------------------------------------------------

def get_aws_profile() -> Optional[str]:
    """AWS profile override. BLUEARCH_PROFILE takes precedence over AWS_PROFILE."""
    return os.environ.get("BLUEARCH_PROFILE") or os.environ.get("AWS_PROFILE")


def is_debug() -> bool:
    """Debug mode flag."""
    return os.environ.get("BLUEARCH_DEBUG", "").lower() in ("1", "true", "yes")


def get_license_key() -> Optional[str]:
    """License key from env var."""
    return os.environ.get("BLUEARCH_LICENSE_KEY")
