"""Local compatibility wrappers for the open-source build."""

from __future__ import annotations

import json
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional


class AuthWrapper:
    """Compatibility stub for removed hosted account authentication."""

    def is_subscribed_to_marketplace(self) -> bool:
        return True

    def get_api_key(self) -> Optional[str]:
        return None

    def validate_api_key(self) -> tuple[bool, str, Optional[str]]:
        return True, "No hosted API key is required for the open-source build.", None


class AuthSecretsWrapper:
    """Local file-backed secret storage used only for compatibility."""

    path = Path.home() / ".bluearch" / "local-secrets.json"

    def get_secret(self) -> Optional[str]:
        try:
            return self.path.read_text(encoding="utf-8")
        except OSError:
            return None

    def put_secret(self, secret_value: str) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(secret_value, encoding="utf-8")
        return True


class SlackSecretsWrapper(AuthSecretsWrapper):
    """Store user-provided Slack webhooks locally."""

    path = Path.home() / ".bluearch" / "slack-webhooks.json"

    def store_slack_webhook(self, webhook_url: str) -> bool:
        webhooks = self.get_slack_webhooks()
        if webhook_url not in webhooks:
            webhooks.append(webhook_url)
        return self.put_secret(json.dumps(webhooks))

    def delete_slack_webhook(self, webhook_url: str) -> bool:
        webhooks = [item for item in self.get_slack_webhooks() if item != webhook_url]
        return self.put_secret(json.dumps(webhooks))

    def get_slack_webhooks(self) -> list[str]:
        secret = self.get_secret()
        if not secret:
            return []
        try:
            value = json.loads(secret)
        except json.JSONDecodeError:
            return []
        return value if isinstance(value, list) else []


def premium(func: Callable | None = None, *, max_messages: int = 1):
    if func is None:
        return lambda wrapped: premium(wrapped, max_messages=max_messages)

    @wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        return func(*args, **kwargs)

    return wrapper
