"""Core-backed database compatibility layer.

bluearch-core owns the SQLite database. This module preserves the small
SQLAlchemy-shaped surface still used by legacy helpers while routing reads and
writes through core storage APIs instead of opening a product-local database.
"""

from __future__ import annotations

import operator
import time
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.sql.elements import (
    BinaryExpression,
    BooleanClauseList,
    False_,
    Grouping,
    Null,
    True_,
    UnaryExpression,
)

from utils.core_client import CoreRuntimeError, request_core
from utils.core_storage import create_record, delete_record, format_datetime, list_all_records, update_record
from utils.logger_config import log


MODEL_COLLECTIONS: dict[str, tuple[str, str]] = {
    "resources": ("core", "resources"),
    "resource_relationships": ("core", "resource-relationships"),
    "account_status": ("core", "account-status"),
    "account_context": ("core", "account-context"),
    "assume_role_configurations": ("core", "assume-role-configurations"),
    "scan_history": ("core", "scan-history"),
    "scan_jobs": ("core", "scan-jobs"),
    "notification_events": ("core", "notification-events"),
    "recommendations": ("bluearch", "recommendations"),
    "recommendation_notes": ("bluearch", "recommendation-notes"),
    "alarms": ("bluearch", "alarms"),
    "alarm_events": ("bluearch", "alarm-events"),
    "alarm_configurations": ("bluearch", "alarm-configurations"),
    "remediation_logs": ("bluearch", "remediation-logs"),
    "log_scans": ("bluearch", "log-scans"),
    "log_findings": ("bluearch", "log-findings"),
    "chat_conversations": ("bluearch", "chat-conversations"),
    "chat_messages": ("bluearch", "chat-messages"),
    "system_executions": ("bluearch", "system-executions"),
}


class CoreRow:
    def __init__(self, payload: dict[str, Any], *, model: type, session: "CoreStorageSession", namespace: str, collection: str):
        object.__setattr__(self, "_model", model)
        object.__setattr__(self, "_session", session)
        object.__setattr__(self, "_namespace", namespace)
        object.__setattr__(self, "_collection", collection)
        object.__setattr__(self, "_dirty", False)
        for key, value in payload.items():
            object.__setattr__(self, key, value)
        object.__setattr__(self, "record_key", payload.get("record_key") or payload.get("id"))

    def __setattr__(self, key: str, value: Any) -> None:
        object.__setattr__(self, key, value)
        if not key.startswith("_"):
            object.__setattr__(self, "_dirty", True)
            self._session.mark_dirty(self)

    def __getattr__(self, key: str) -> Any:
        if key in {column.key for column in inspect(self._model).columns}:
            return None
        if hasattr(self._model, key):
            return getattr(self._model, key)
        raise AttributeError(key)

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in vars(self).items() if not key.startswith("_")}


class ScalarResult:
    def __init__(self, value: Any):
        self._value = value

    def scalar(self) -> Any:
        return self._value

    def fetchone(self) -> tuple[Any]:
        return (self._value,)


class CoreQuery:
    def __init__(self, session: "CoreStorageSession", entity: Any):
        self.session = session
        self.entity = entity
        self.model = _model_from_entity(entity)
        self.criteria: list[Any] = []
        self.order_expr: Any = None
        self._limit: int | None = None

    def filter(self, *criteria: Any) -> "CoreQuery":
        self.criteria.extend(criteria)
        return self

    def filter_by(self, **kwargs: Any) -> "CoreQuery":
        for key, value in kwargs.items():
            self.criteria.append(("eq", key, value))
        return self

    def order_by(self, *expressions: Any) -> "CoreQuery":
        self.order_expr = expressions[0] if expressions else None
        return self

    def limit(self, value: int) -> "CoreQuery":
        self._limit = value
        return self

    def all(self) -> list[CoreRow]:
        namespace, collection = _storage_for_model(self.model)
        rows = [
            CoreRow(record, model=self.model, session=self.session, namespace=namespace, collection=collection)
            for record in list_all_records(namespace, collection)
        ]
        for criterion in self.criteria:
            rows = [row for row in rows if _matches(row, criterion)]
        if self.order_expr is not None:
            key, descending = _order_key(self.order_expr)
            rows.sort(key=lambda row: _sortable_value(getattr(row, key, None)), reverse=descending)
        if self._limit is not None:
            rows = rows[: self._limit]
        return rows

    def first(self) -> CoreRow | None:
        rows = self.limit(1).all()
        return rows[0] if rows else None

    def count(self) -> int:
        return len(self.all())


class CoreStorageSession:
    def __init__(self):
        self._new: list[Any] = []
        self._dirty: dict[int, CoreRow] = {}
        self._deleted: dict[int, CoreRow] = {}

    def query(self, entity: Any) -> CoreQuery:
        return CoreQuery(self, entity)

    def add(self, obj: Any) -> None:
        self._new.append(obj)

    def delete(self, obj: Any) -> None:
        if isinstance(obj, CoreRow):
            self._deleted[id(obj)] = obj

    def mark_dirty(self, obj: CoreRow) -> None:
        self._dirty[id(obj)] = obj

    def commit(self) -> None:
        for obj in list(self._new):
            namespace, collection = _storage_for_model(obj.__class__)
            created = create_record(namespace, collection, _payload_from_model_object(obj))
            for key, value in created.items():
                setattr(obj, key, value)
            self._new.remove(obj)

        for row in list(self._dirty.values()):
            if id(row) not in self._deleted:
                update_record(row._namespace, row._collection, row.to_dict(), row.to_dict())
        self._dirty.clear()

        for row in list(self._deleted.values()):
            delete_record(row._namespace, row._collection, row.to_dict())
        self._deleted.clear()

    def flush(self) -> None:
        self.commit()

    def rollback(self) -> None:
        self._new.clear()
        self._dirty.clear()
        self._deleted.clear()

    def close(self) -> None:
        self.rollback()

    def execute(self, statement: Any) -> ScalarResult:
        if str(statement).strip().lower() == "select 1":
            return ScalarResult(1)
        return ScalarResult(0)


class DatabaseManager:
    _instance = None
    _lock = Lock()

    def __new__(cls, *args, **kwargs) -> "DatabaseManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        self._last_health_check = 0.0
        self._health_check_interval = 30

    def initialize(self, db_path: str | None = None) -> None:
        request_core("GET", "/api/v1/core/health", service_token=True, timeout=5.0)
        self._initialized = True
        log.debug("DatabaseManager connected to bluearch-core")

    @property
    def engine(self):
        raise RuntimeError("bluearch-core owns the database engine; use core APIs instead")

    @property
    def session_factory(self):
        raise RuntimeError("bluearch-core owns database sessions; use get_db_session compatibility only")

    def create_tables(self) -> None:
        request_core("POST", "/api/v1/core/db/migrate", service_token=True, timeout=30.0)

    def get_session(self) -> CoreStorageSession:
        if not self._initialized:
            self.initialize()
        return CoreStorageSession()

    def reset(self) -> None:
        self._initialized = False

    def health_check(self, force: bool = False) -> dict[str, Any]:
        current_time = time.time()
        if not force and (current_time - self._last_health_check) < self._health_check_interval:
            return {"status": "skipped", "message": "Health check rate limited"}
        self._last_health_check = current_time
        try:
            return request_core("GET", "/api/v1/core/health", service_token=True, timeout=5.0)
        except CoreRuntimeError as exc:
            return {"status": "error", "message": str(exc)}


def _model_from_entity(entity: Any) -> type:
    if isinstance(entity, type):
        return entity
    entity_class = getattr(entity, "class_", None)
    if entity_class is not None:
        return entity_class
    parent = getattr(getattr(entity, "property", None), "parent", None)
    if parent is not None and getattr(parent, "class_", None) is not None:
        return parent.class_
    raise RuntimeError(f"Unsupported query entity: {entity!r}")


def _storage_for_model(model: type) -> tuple[str, str]:
    table_name = getattr(model, "__tablename__", "")
    storage = MODEL_COLLECTIONS.get(table_name)
    if not storage:
        raise RuntimeError(f"No bluearch-core storage collection registered for {model.__name__}")
    return storage


def _payload_from_model_object(obj: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for column in inspect(obj.__class__).columns:
        value = getattr(obj, column.key, None)
        if value is not None:
            payload[column.key] = _json_safe(value)
    return payload


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return format_datetime(value)
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    return value


def _matches(row: CoreRow, criterion: Any) -> bool:
    if isinstance(criterion, tuple) and len(criterion) == 3:
        _, key, value = criterion
        return _compare(getattr(row, key, None), value, operator.eq)
    if isinstance(criterion, Grouping):
        return _matches(row, criterion.element)
    if isinstance(criterion, BooleanClauseList):
        op_name = getattr(criterion.operator, "__name__", "")
        if op_name == "or_":
            return any(_matches(row, clause) for clause in criterion.clauses)
        return all(_matches(row, clause) for clause in criterion.clauses)
    if isinstance(criterion, BinaryExpression):
        key = _field_name(criterion.left)
        row_value = getattr(row, key, None)
        right_value = _literal_value(criterion.right)
        op_name = getattr(criterion.operator, "__name__", "")
        if op_name == "eq":
            return _compare(row_value, right_value, operator.eq)
        if op_name == "ne":
            return _compare(row_value, right_value, operator.ne)
        if op_name == "lt":
            return _compare(row_value, right_value, operator.lt)
        if op_name == "le":
            return _compare(row_value, right_value, operator.le)
        if op_name == "gt":
            return _compare(row_value, right_value, operator.gt)
        if op_name == "ge":
            return _compare(row_value, right_value, operator.ge)
        if op_name == "is_":
            return row_value is None if right_value is None else row_value is right_value
        if op_name == "is_not":
            return row_value is not None if right_value is None else row_value is not right_value
        if op_name == "in_op":
            return row_value in (right_value or [])
        if op_name == "like_op":
            return _like(row_value, str(right_value or ""))
    return bool(criterion)


def _field_name(expression: Any) -> str:
    return getattr(expression, "key", None) or getattr(expression, "name", None) or str(expression).split(".")[-1]


def _literal_value(expression: Any) -> Any:
    if isinstance(expression, Null):
        return None
    if isinstance(expression, True_):
        return True
    if isinstance(expression, False_):
        return False
    return getattr(expression, "value", expression)


def _compare(left: Any, right: Any, comparison) -> bool:
    left_value, right_value = _comparable_values(left, right)
    try:
        return bool(comparison(left_value, right_value))
    except TypeError:
        return False


def _comparable_values(left: Any, right: Any) -> tuple[Any, Any]:
    if isinstance(right, datetime) or _looks_datetime(left):
        return _to_datetime(left), _to_datetime(right)
    return left, right


def _looks_datetime(value: Any) -> bool:
    return isinstance(value, str) and "T" in value and ("+" in value or value.endswith("Z"))


def _to_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _like(value: Any, pattern: str) -> bool:
    text = str(value or "")
    if pattern.startswith("%") and pattern.endswith("%"):
        return pattern.strip("%") in text
    if pattern.startswith("%"):
        return text.endswith(pattern[1:])
    if pattern.endswith("%"):
        return text.startswith(pattern[:-1])
    return text == pattern


def _order_key(expression: Any) -> tuple[str, bool]:
    if isinstance(expression, UnaryExpression):
        return _field_name(expression.element), getattr(expression.modifier, "__name__", "") == "desc_op"
    if isinstance(expression, InstrumentedAttribute):
        return expression.key, False
    return _field_name(expression), False


def _sortable_value(value: Any) -> Any:
    parsed = _to_datetime(value)
    if parsed is not None:
        return parsed
    return value if value is not None else ""


db_manager = DatabaseManager()


@contextmanager
def get_db_session() -> Generator[CoreStorageSession, None, None]:
    session = db_manager.get_session()
    try:
        yield session
        session.commit()
    except (SystemExit, KeyboardInterrupt):
        session.rollback()
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
