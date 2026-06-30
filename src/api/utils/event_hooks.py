"""Local event hook no-ops for the open-source build."""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable


def track_event(*_args: Any, **_kwargs: Any) -> None:
    return None


def emit_event(*_args: Any, **_kwargs: Any) -> None:
    return None


def passthrough_decorator(func: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    return wrapper
