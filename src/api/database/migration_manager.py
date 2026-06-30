"""Core-backed migration compatibility helpers.

bluearch-core owns all table definitions and migrations. These functions keep
legacy callers import-compatible while delegating migration work to core.
"""

from __future__ import annotations

from utils.core_client import request_core
from utils.logger_config import log


def ensure_tables(engine=None):
    """Ask bluearch-core to run its idempotent database migration."""
    request_core("POST", "/api/v1/core/db/migrate", service_token=True, timeout=30.0)
    log.debug("ensure_tables: delegated to bluearch-core")


def add_column_if_missing(engine, table_name, column_name, column_type):
    """Compatibility no-op; schema changes are owned by bluearch-core."""
    log.debug(
        "add_column_if_missing skipped for %s.%s; bluearch-core owns schema",
        table_name,
        column_name,
    )
    return False


def run_schema_updates(engine=None):
    """Ask bluearch-core to run its idempotent database migration."""
    ensure_tables(engine)


def initialize_database(engine=None):
    """Full database initialization delegated to bluearch-core."""
    ensure_tables(engine)
    log.debug("Database initialization delegated to bluearch-core")
