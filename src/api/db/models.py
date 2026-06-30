"""Legacy PynamoDB model stubs — replaced by SQLAlchemy in database/models.py.

These classes exist only for import compatibility with legacy code that
references `from db.models import AccountsAndRegion, Recommendation`.
They are NOT used for data storage — all data goes through SQLAlchemy.
"""

from utils.logger_config import log


class AccountsAndRegion:
    """Stub — use database.models.Account instead."""

    def __init__(self, **kwargs):
        self.account_id = kwargs.get("account_id", "")
        self.account_name = kwargs.get("account_name", "")
        self.regions = kwargs.get("regions", "")

    @classmethod
    def setup_table(cls):
        log.debug("AccountsAndRegion.setup_table() — no-op (SQLite is primary)")

    @classmethod
    def scan(cls, *args, **kwargs):
        return []

    @classmethod
    def query(cls, *args, **kwargs):
        return []

    @classmethod
    def get(cls, *args, **kwargs):
        raise LookupError("Use database.models.Account with SQLAlchemy")

    def save(self, *args, **kwargs):
        log.debug("AccountsAndRegion.save() — no-op (SQLite is primary)")

    @classmethod
    def get_attributes(cls):
        return {"account_id": None, "account_name": None, "regions": None}


class Recommendation:
    """Stub — use database.models.Recommendation instead."""

    def __init__(self, **kwargs):
        self.unique_id = kwargs.get("unique_id", "")
        self.recommendation_type = kwargs.get("recommendation_type", "")
        self.region_name = kwargs.get("region_name", "")
        self.account_id = kwargs.get("account_id", "")
        self.account_name = kwargs.get("account_name", "")
        self.last_updated = kwargs.get("last_updated")
        self.attributes = kwargs.get("attributes", {})

    @classmethod
    def setup_table(cls):
        log.debug("Recommendation.setup_table() — no-op (SQLite is primary)")

    @classmethod
    def scan(cls, *args, **kwargs):
        return []

    @classmethod
    def query(cls, *args, **kwargs):
        return []

    def save(self, *args, **kwargs):
        log.debug("Recommendation.save() — no-op (SQLite is primary)")
