"""Open-source feature availability helpers.

The public build has no hosted license service. All local features are enabled
and these helpers remain only to keep existing command imports stable.
"""

from pathlib import Path
from typing import Optional, Tuple

from licensing.features import Tier


def get_current_tier() -> Tier:
    return Tier.ENTERPRISE


def get_license_info() -> Optional[dict]:
    return {"tier": Tier.ENTERPRISE.value, "customer": "local"}


def is_feature_allowed(feature: str) -> bool:
    return True


def save_license_key(token: str) -> Path:
    path = Path.home() / ".bluearch" / "public-build-no-license-required"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Commercial activation is not required for the open-source build.\n", encoding="utf-8")
    return path


def validate_license_token(token: str) -> Tuple[Tier, Optional[dict]]:
    return Tier.ENTERPRISE, get_license_info()


def reset_cache() -> None:
    return None
