"""SQLite backend configuration — PRAGMAs, engine creation, and utilities."""

import os
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.pool import NullPool
from utils.logger_config import log


DEFAULT_DB_DIR = os.path.join(os.path.expanduser("~"), ".bluearch", "data")
DEFAULT_DB_NAME = "bluearch.db"
CORE_DB_PATH = os.path.join(os.path.expanduser("~"), ".bluearch-core", "data", "core.db")


def get_db_path(db_dir=None, db_name=None):
    """Return the full path to the SQLite database file."""
    if db_dir is None and db_name is None:
        return os.environ.get("BLUEARCH_CORE_DB_PATH", CORE_DB_PATH)
    db_dir = db_dir or DEFAULT_DB_DIR
    db_name = db_name or DEFAULT_DB_NAME
    return os.path.join(db_dir, db_name)


def ensure_db_directory(db_path):
    """Create the database directory if it doesn't exist."""
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)


def _set_sqlite_pragmas(dbapi_conn, connection_record):
    """Set SQLite PRAGMAs on every new connection for performance and safety."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA mmap_size=30000000000")
    cursor.close()


def create_sqlite_engine(db_path=None):
    """Create a SQLAlchemy engine configured for SQLite.

    Uses NullPool (no connection pooling) which is the correct choice for
    SQLite — connections are lightweight and pooling causes threading issues.
    """
    db_path = db_path or get_db_path()
    ensure_db_directory(db_path)

    engine = create_engine(
        f"sqlite:///{db_path}",
        poolclass=NullPool,
        connect_args={
            "check_same_thread": False,
            "timeout": 30.0,
        },
        echo=False,
    )

    # Register PRAGMA setup on every new connection
    event.listen(engine, "connect", _set_sqlite_pragmas)

    log.debug(f"SQLite engine created: {db_path}")
    return engine
