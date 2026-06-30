"""SQLAlchemy ORM models for the BlueArch CLI.

The Resource model uses the EXACT same schema as the Tag Manager CLI so both
CLIs can read/write the same shared database at ~/.bluearch/data/bluearch.db.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (

    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    Float,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


# ---------------------------------------------------------------------------
# Helpers (matching tag-manager patterns)
# ---------------------------------------------------------------------------

def UUID_Column(**kwargs):
    """UUID primary key stored as a 36-char string (SQLite-compatible)."""
    return Column(
        String(36),
        default=lambda: str(uuid.uuid4()),
        **kwargs,
    )


def _iso_utc(dt):
    """Serialize a DB datetime as ISO-8601 with an explicit UTC offset.

    SQLite stores tz-aware datetimes as naive UTC, so rows come back
    without a tzinfo. JS `new Date()` parses such strings as *local*
    time (ES2015+), which produces negative elapsed times for non-UTC
    users. Always emit the offset so clients get it right.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def Array_Column(**kwargs):
    """JSON column for storing arrays in SQLite."""
    return Column(JSON, **kwargs)


# ---------------------------------------------------------------------------
# Shared Resource model (identical to tag-manager-cli)
# ---------------------------------------------------------------------------

class Resource(Base):
    """AWS resources discovered and tracked.

    Schema is shared with Tag Manager CLI — both CLIs read/write this table.
    """

    __tablename__ = "resources"

    # Primary key
    id = UUID_Column(primary_key=True)

    # Resource identification
    resource_arn = Column(String(1024), nullable=False, unique=True, index=True)
    resource_type = Column(String(100), nullable=False, index=True)
    service_name = Column(String(50), nullable=False, index=True)
    region = Column(String(50), nullable=False, index=True)
    account_id = Column(String(12), nullable=False, index=True)
    resource_id = Column(String(256), nullable=False)

    # Creator information (from CloudTrail)
    created_by = Column(String(256), index=True)
    created_at = Column(DateTime(timezone=True))

    # Discovery metadata
    discovered_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    last_scanned_at = Column(DateTime(timezone=True), default=func.now())

    # Current tags and metadata
    current_tags = Column(JSON)
    metadata_json = Column("metadata", JSON)

    # Lifecycle management (used by Tag Manager CLI)
    expires_at = Column(DateTime(timezone=True), index=True)
    lifecycle_state = Column(String(50), default="active", index=True)
    delete_after = Column(DateTime(timezone=True), index=True)
    protected = Column(Boolean, default=False, index=True)

    # Lifecycle tracking
    warned_at = Column(DateTime(timezone=True))
    warning_count = Column(Integer, default=0)
    lifecycle_policy_id = Column(String(36), nullable=True)

    # TTL source tracking
    ttl_source = Column(String(50))
    ttl_tag_key = Column(String(256))
    owner_email = Column(String(256), index=True)
    grace_period_ends_at = Column(DateTime(timezone=True), index=True)

    # Policy source tracking (hybrid policy system)
    policy_source = Column(String(50), index=True)
    org_policy_id = Column(String(100))
    org_policy_name = Column(String(255))

    # Compliance tracking (for AWS Org Tag Policies)
    compliance_status = Column(String(50), index=True)
    missing_tags = Column(JSON)
    invalid_tags = Column(JSON)
    last_compliance_check = Column(DateTime(timezone=True))

    # Relationships (BlueArch-side)
    recommendations = relationship(
        "Recommendation", back_populates="resource", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_resource_type_region", "resource_type", "region"),
        Index("idx_service_created_at", "service_name", "created_at"),
        Index("idx_created_by", "created_by"),
        Index("idx_last_scanned", "last_scanned_at"),
        Index("idx_lifecycle_state_expires", "lifecycle_state", "expires_at"),
        Index("idx_expires_protected", "expires_at", "protected"),
        Index("idx_delete_after_state", "delete_after", "lifecycle_state"),
        Index("idx_lifecycle_policy", "lifecycle_policy_id"),
    )


# ---------------------------------------------------------------------------
# BlueArch-specific models
# ---------------------------------------------------------------------------

class Account(Base):
    """AWS account status and configuration for multi-account operations.

    Matches Tag Manager CLI's AccountStatus model for shared DB compatibility.
    """

    __tablename__ = "account_status"

    id = UUID_Column(primary_key=True)

    # Account identification
    account_id = Column(String(12), nullable=False, unique=True, index=True)
    account_name = Column(String(255), nullable=False)
    account_email = Column(String(255))
    organizational_unit_id = Column(String(100), index=True)
    organizational_unit_path = Column(String(500))

    # Account status
    account_status = Column("status", String(50), nullable=False, default="ACTIVE", index=True)
    is_management_account = Column(Boolean, default=False)
    is_delegated_admin = Column(Boolean, default=False)

    # Multi-account configuration
    enabled_for_discovery = Column(Boolean, default=False, nullable=False, index=True)
    enabled_for_tagging = Column(Boolean, default=False, nullable=False, index=True)
    role_name = Column(String(100), default="BlueArchCLIRole")
    role_arn = Column(String(1024))

    # Access validation
    last_access_check = Column(DateTime(timezone=True))
    access_check_status = Column(String(50))  # SUCCESS, FAILED, NOT_TESTED
    access_check_error = Column(Text)

    # Discovery statistics
    last_discovery_at = Column(DateTime(timezone=True))
    total_resources_discovered = Column(Integer, default=0)
    last_discovery_duration_seconds = Column(Integer)

    # Legacy field — kept for backward compat with existing BlueArch code
    regions = Column(JSON)

    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
    enabled_at = Column(DateTime(timezone=True))
    disabled_at = Column(DateTime(timezone=True))

    metadata_json = Column("metadata", JSON)

    __table_args__ = (
        Index("idx_account_status_enabled", "enabled_for_discovery", "enabled_for_tagging"),
        Index("idx_account_ou", "organizational_unit_id", "enabled_for_discovery"),
        Index("idx_account_status_updated", "status", "updated_at"),
        Index("idx_account_last_discovery", "last_discovery_at"),
    )


class AccountContext(Base):
    """Registered AWS account contexts for multi-account isolation.

    Matches Tag Manager CLI so both apps share this table.
    """

    __tablename__ = "account_context"

    id = UUID_Column(primary_key=True)
    account_id = Column(String(12), nullable=False, unique=True, index=True)
    account_alias = Column(String(256), nullable=True)
    aws_profile = Column(String(256), nullable=True)
    region = Column(String(50), nullable=True)
    user_arn = Column(String(256), nullable=True)
    is_current = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_account_context_current", "is_current"),
    )


class Recommendation(Base):
    """Recommendations generated by the BlueArch scan pipeline.

    Replaces the PynamoDB Recommendation model.
    """

    __tablename__ = "recommendations"

    id = UUID_Column(primary_key=True)
    unique_id = Column(String(64), nullable=False, unique=True, index=True)  # SHA256 hash
    recommendation_type = Column(String(100), nullable=False, index=True)
    region_name = Column(String(50), nullable=False, index=True)
    account_id = Column(String(12), nullable=False, index=True)
    account_name = Column(String(256))
    last_updated = Column(DateTime(timezone=True), default=func.now())
    attributes = Column(JSON)  # arbitrary recommendation-specific fields

    # FK to shared Resource (nullable — not all recommendations map to a resource)
    resource_id = Column(String(36), ForeignKey("resources.id"), nullable=True)
    resource = relationship("Resource", back_populates="recommendations")
    notes = relationship(
        "RecommendationNote",
        back_populates="recommendation",
        cascade="all, delete-orphan",
        order_by="RecommendationNote.created_at.desc()",
    )

    __table_args__ = (
        Index("idx_rec_type_account", "recommendation_type", "account_id"),
        Index("idx_rec_region", "region_name"),
    )


class RecommendationNote(Base):
    """Append-only note an operator attached to a recommendation.

    Lets teams capture *why a finding exists* and *what action is being
    taken* — customer-requested annotation that shows up in the dashboard
    alongside the recommendation.
    """

    __tablename__ = "recommendation_notes"

    id = UUID_Column(primary_key=True)
    recommendation_id = Column(
        String(36),
        ForeignKey("recommendations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    body = Column(Text, nullable=False)
    # Free-form author string (username / email / "system"). Web routes
    # populate this from the current user when available.
    author = Column(String(255))

    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        onupdate=func.now(),
    )

    recommendation = relationship("Recommendation", back_populates="notes")

    __table_args__ = (
        Index("idx_rec_note_rec_created", "recommendation_id", "created_at"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "recommendation_id": self.recommendation_id,
            "body": self.body,
            "author": self.author,
            "created_at": _iso_utc(self.created_at),
            "updated_at": _iso_utc(self.updated_at),
        }


class AlarmConfiguration(Base):
    """Local tracking of CloudWatch alarm state per recommendation type."""

    __tablename__ = "alarm_configurations"

    id = UUID_Column(primary_key=True)
    recommendation_type = Column(String(100), nullable=False, unique=True, index=True)
    enabled = Column(Boolean, default=False)
    threshold = Column(Integer, default=1)
    alarm_name = Column(String(256))
    last_triggered_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())


class Alarm(Base):
    """Custom alarms for tracking recommendations.

    Unlike the legacy AlarmConfiguration (which maps one-to-one onto a
    CloudWatch alarm per recommendation_type), this model supports richer
    criteria: multiple recommendation types, account and region filters,
    severity filters, plus notification targets.
    """

    __tablename__ = "alarms"

    id = UUID_Column(primary_key=True)
    name = Column(String(256), nullable=False)
    description = Column(Text)

    # Trigger source. Legacy rows may contain older values, but the active API
    # only creates recommendation alarms.
    trigger_type = Column(String(20), nullable=False, default="recommendation")

    # Filter criteria (all optional — empty list = match any)
    recommendation_types = Column(JSON, default=list)  # e.g. ["EC2_IDLE", "EBS_UNUSED"]
    resource_types = Column(JSON, default=list)  # e.g. ["ec2", "s3"]
    account_ids = Column(JSON, default=list)
    regions = Column(JSON, default=list)
    severity_filter = Column(String(50))  # optional: 'low', 'medium', 'high', 'critical'

    # Trigger when match count >= threshold
    threshold = Column(Integer, nullable=False, default=1)

    # Notification targets — list of {type: 'email'|'slack'|'sns', value: '...'}
    notification_targets = Column(JSON, default=list)

    # State
    enabled = Column(Boolean, default=True, nullable=False)
    last_evaluated_at = Column(DateTime(timezone=True))
    last_triggered_at = Column(DateTime(timezone=True))
    last_match_count = Column(Integer, default=0)
    trigger_count = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
    created_by = Column(String(256))  # user email / id


class AlarmEvent(Base):
    """History of individual alarm firings (audit trail)."""

    __tablename__ = "alarm_events"

    id = UUID_Column(primary_key=True)
    alarm_id = Column(String(36), ForeignKey("alarms.id", ondelete="CASCADE"), nullable=False, index=True)
    triggered_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    match_count = Column(Integer, nullable=False)
    match_sample = Column(JSON)  # small sample of matching resource_ids / finding_ids
    notification_sent = Column(Boolean, default=False)
    notification_error = Column(Text)

    __table_args__ = (
        Index("ix_alarm_events_alarm_triggered", "alarm_id", "triggered_at"),
    )


class NotificationEvent(Base):
    """Audit trail for product notifications sent by local CLI services."""

    __tablename__ = "notification_events"

    id = UUID_Column(primary_key=True)
    source = Column(String(100), nullable=False, index=True)
    event_key = Column(String(255), nullable=False)
    severity = Column(String(50), nullable=False, default="warning", index=True)
    title = Column(String(255), nullable=False)
    message = Column(Text)
    payload = Column(JSON)
    notification_sent = Column(Boolean, default=False)
    notification_error = Column(Text)
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    sent_at = Column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("source", "event_key", name="uq_notification_event_source_key"),
        Index("idx_notification_events_source_created", "source", "created_at"),
    )


class ScanHistory(Base):
    """Track scan executions for the --skip-scan feature."""

    __tablename__ = "scan_history"

    id = UUID_Column(primary_key=True)
    scan_mode = Column(String(20), nullable=False)  # local, cloud
    collected_by = Column(String(50), nullable=False)  # bluearch, tag-manager
    started_at = Column(DateTime(timezone=True), default=func.now())
    completed_at = Column(DateTime(timezone=True))
    status = Column(String(20), nullable=False, default="running")  # running, completed, failed
    accounts_scanned = Column(Integer, default=0)
    regions_scanned = Column(Integer, default=0)
    resources_found = Column(Integer, default=0)
    error_message = Column(Text)


# ---------------------------------------------------------------------------
# Cross-account role assumption
# ---------------------------------------------------------------------------

class AssumeRoleConfiguration(Base):
    """Cross-account role assumption configuration."""

    __tablename__ = "assume_role_configurations"

    id = UUID_Column(primary_key=True)
    account_id = Column(String(12), nullable=False, index=True)
    role_arn = Column(String(2048), nullable=False)
    role_name = Column(String(64), default="BlueArchCLIRole")
    external_id = Column(String(256))
    is_active = Column(Boolean, default=False, index=True)
    enabled = Column(Boolean, default=True)
    alias = Column(String(64))
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
    last_used_at = Column(DateTime(timezone=True))

    __table_args__ = (
        Index("idx_assume_role_account_active", "account_id", "is_active"),
        Index("idx_assume_role_active_enabled", "is_active", "enabled"),
    )


class EventSyncConfiguration(Base):
    """Event-driven resource sync queue configuration.

    Matches Tag Manager CLI so both apps share this table.
    Used for cloud scan mode (bluearch scan --cloud).
    """

    __tablename__ = "event_sync_configuration"

    id = Column(Integer, primary_key=True, autoincrement=True)

    account_id = Column(String(20), nullable=False, index=True)
    region = Column(String(30), nullable=False)

    queue_url = Column(String(512), nullable=False)
    queue_arn = Column(String(512), nullable=False)

    stack_name = Column(String(256), nullable=False)
    stack_id = Column(String(512))

    sync_status = Column("status", String(20), nullable=False, default="deploying", index=True)

    deployed_at = Column(DateTime(timezone=True))
    last_polled_at = Column(DateTime(timezone=True))
    last_event_at = Column(DateTime(timezone=True))

    messages_processed = Column(Integer, default=0)
    events_today = Column(Integer, default=0)
    events_today_reset_at = Column(DateTime(timezone=True))

    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_event_sync_status", "status"),
        Index("idx_event_sync_account_region", "account_id", "region"),
        Index("idx_event_sync_last_polled", "last_polled_at"),
    )


# ---------------------------------------------------------------------------
# System tracking models (shared with Tag Manager)
# ---------------------------------------------------------------------------

class SystemExecution(Base):
    """Track system task execution times for setup validation and health checks.

    Matches Tag Manager CLI so both apps share this table.
    """

    __tablename__ = "system_executions"

    id = UUID_Column(primary_key=True)
    task_name = Column(String(100), nullable=False, index=True)
    task_type = Column(String(50), nullable=False)
    last_execution_at = Column(DateTime(timezone=True))
    execution_status = Column(String(20))  # success, failed, running
    execution_duration_ms = Column(Integer)
    execution_details = Column(JSON)
    error_message = Column(Text)
    resources_processed = Column(Integer)
    triggered_by = Column(String(100))  # auto, manual, installation
    execution_context = Column(JSON)

    __table_args__ = (
        Index("idx_system_exec_type_status", "task_type", "execution_status"),
        Index("idx_system_exec_name", "task_name"),
    )


class PermissionCache(Base):
    """Cached IAM permission simulation results per account/principal.

    Matches Tag Manager CLI so both apps share this table.
    """

    __tablename__ = "permission_cache"

    account_id = Column(String(12), nullable=False, primary_key=True)
    user_arn = Column(String(256), nullable=False, primary_key=True)
    action = Column(String(128), nullable=False, primary_key=True)
    granted = Column(Boolean, nullable=False)
    checked_at = Column(DateTime(timezone=True), nullable=False, default=func.now())


class PermissionTier(Base):
    """Computed permission tier and feature availability per account/principal.

    Matches Tag Manager CLI so both apps share this table.
    """

    __tablename__ = "permission_tier"

    account_id = Column(String(12), nullable=False, primary_key=True)
    user_arn = Column(String(256), nullable=False, primary_key=True)
    tier = Column(String(20), nullable=False)
    features_json = Column(JSON, nullable=False)
    checked_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)


class ResourceRelationship(Base):
    """Tracks relationships between AWS resources for graph visualization.

    Matches Tag Manager CLI so both apps share this table.
    """

    __tablename__ = "resource_relationships"

    id = UUID_Column(primary_key=True)
    source_arn = Column(String(1024), nullable=False, index=True)
    target_arn = Column(String(1024), nullable=False, index=True)
    relationship_type = Column(String(50), nullable=False)
    source_type = Column(String(100))
    target_type = Column(String(100))
    region = Column(String(50))
    account_id = Column(String(12))
    metadata_json = Column("metadata", JSON)
    discovered_at = Column(DateTime(timezone=True), default=func.now())
    last_seen_at = Column(DateTime(timezone=True), default=func.now())

    __table_args__ = (
        Index("idx_rel_source", "source_arn"),
        Index("idx_rel_target", "target_arn"),
        Index("idx_rel_type", "relationship_type"),
    )


class ChatConversation(Base):
    """AI chat conversation session."""

    __tablename__ = 'chat_conversations'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String(256), nullable=False)
    model = Column(String(20), default='auto')
    message_count = Column(Integer, default=0)
    total_input_tokens = Column(Integer, default=0)
    total_output_tokens = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now())

    def __repr__(self):
        return f"<ChatConversation(id={self.id}, title={self.title[:30]})>"


class ChatMessage(Base):
    """Individual message in a chat conversation."""

    __tablename__ = 'chat_messages'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String(36), ForeignKey('chat_conversations.id'), nullable=False, index=True)
    role = Column(String(10), nullable=False)  # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    tool_calls = Column(Text, nullable=True)  # JSON array of tool call records
    tokens = Column(Text, nullable=True)  # JSON {input, output}
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())

    def __repr__(self):
        return f"<ChatMessage(id={self.id}, role={self.role}, conv={self.conversation_id})>"


class ScanJob(Base):
    """Scan job progress tracked in the shared DB.

    Both BlueArch and Tag Manager CLIs read/write this table so a scan
    started in one app shows progress in both. Replaces the old in-memory
    JobManager for scan jobs (non-scan jobs like event tracking still use
    the in-memory manager).
    """

    __tablename__ = "scan_jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # Which CLI started this job: "bluearch" or "tag-manager"
    source = Column(String(32), nullable=False, default="bluearch", index=True)
    # pending, running, completed, failed
    status = Column(String(20), nullable=False, default="pending", index=True)
    progress = Column(Integer, default=0)
    progress_message = Column(Text)
    progress_data = Column(JSON)
    message = Column(Text)
    result = Column(JSON)
    error = Column(Text)
    services = Column(JSON)  # list of services being scanned
    regions = Column(JSON)   # list of regions being scanned
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), index=True)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))

    __table_args__ = (
        Index("idx_scan_job_status_created", "status", "created_at"),
    )


# ---------------------------------------------------------------------------
# Log Analysis models
# ---------------------------------------------------------------------------

class LogScan(Base):
    """Tracks a single CloudWatch Logs scan execution."""

    __tablename__ = "log_scans"

    id = UUID_Column(primary_key=True)

    account_id = Column(String(12), index=True)
    region = Column(String(32), index=True)

    log_groups_scanned = Column(Integer, default=0)
    findings_count = Column(Integer, default=0)
    time_window_hours = Column(Integer, default=24)

    started_at = Column(DateTime(timezone=True), default=func.now())
    completed_at = Column(DateTime(timezone=True))

    status = Column(String(20), default="running", index=True)  # running, completed, failed
    error_message = Column(Text)

    findings = relationship("LogFinding", back_populates="scan", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_log_scan_account_region", "account_id", "region"),
        Index("idx_log_scan_status_started", "status", "started_at"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "account_id": self.account_id,
            "region": self.region,
            "log_groups_scanned": self.log_groups_scanned,
            "findings_count": self.findings_count,
            "time_window_hours": self.time_window_hours,
            "started_at": _iso_utc(self.started_at),
            "completed_at": _iso_utc(self.completed_at),
            "status": self.status,
            "error_message": self.error_message,
        }


class LogFinding(Base):
    """Individual error finding from a log scan."""

    __tablename__ = "log_findings"

    id = UUID_Column(primary_key=True)

    scan_id = Column(String(36), ForeignKey("log_scans.id"), index=True)

    log_group_name = Column(String(512), index=True)
    error_pattern = Column(String(512), index=True)
    severity = Column(String(20), index=True)  # critical, high, medium, low

    occurrence_count = Column(Integer, default=0)
    first_seen = Column(DateTime(timezone=True))
    last_seen = Column(DateTime(timezone=True))

    sample_message = Column(Text)

    # Resource linkage (nullable — findings may be unlinked)
    resource_id = Column(String(36), ForeignKey("resources.id"), nullable=True, index=True)
    resource_type = Column(String(100))
    service_name = Column(String(50))
    link_status = Column(String(20), default="unlinked", index=True)  # linked, unlinked

    status = Column(String(20), default="open", index=True)  # open, acknowledged, resolved

    ai_analysis = Column(Text)
    ai_analyzed_at = Column(DateTime(timezone=True))

    detected_at = Column(DateTime(timezone=True), default=func.now())

    scan = relationship("LogScan", back_populates="findings")

    __table_args__ = (
        Index("idx_log_finding_scan_severity", "scan_id", "severity"),
        Index("idx_log_finding_resource_status", "resource_id", "status"),
        Index("idx_log_finding_link_severity", "link_status", "severity"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "scan_id": self.scan_id,
            "log_group_name": self.log_group_name,
            "error_pattern": self.error_pattern,
            "severity": self.severity,
            "occurrence_count": self.occurrence_count,
            "first_seen": _iso_utc(self.first_seen),
            "last_seen": _iso_utc(self.last_seen),
            "sample_message": self.sample_message,
            "resource_id": self.resource_id,
            "resource_type": self.resource_type,
            "service_name": self.service_name,
            "link_status": self.link_status,
            "status": self.status,
            "ai_analysis": self.ai_analysis,
            "ai_analyzed_at": _iso_utc(self.ai_analyzed_at),
            "detected_at": _iso_utc(self.detected_at),
        }
