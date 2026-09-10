"""Relational schema for durable conversations, messages, and worker jobs."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ConversationState(StrEnum):
    BOT = "bot"
    WAITING = "waiting"
    HUMAN = "human"


class MessageDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MessageAuthor(StrEnum):
    CUSTOMER = "customer"
    BOT = "bot"
    EMPLOYEE = "employee"
    SYSTEM = "system"


class MessageStatus(StrEnum):
    RECEIVED = "received"
    PENDING = "pending"
    SENDING = "sending"
    ACCEPTED = "accepted"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    UNKNOWN = "unknown"
    CANCELLED = "cancelled"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Employee(Base):
    __tablename__ = "employees"
    __table_args__ = (
        UniqueConstraint("username", name="uq_employees_username"),
        CheckConstraint("char_length(btrim(username)) > 0", name="username_not_blank"),
        CheckConstraint("char_length(password_hash) > 0", name="password_hash_not_blank"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class EmployeeSession(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
        CheckConstraint("char_length(token_hash) > 0", name="token_hash_not_blank"),
        CheckConstraint("char_length(csrf_token_hash) > 0", name="csrf_token_hash_not_blank"),
        Index("ix_sessions_employee_expires_at", "employee_id", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    csrf_token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("wa_id", name="uq_conversations_wa_id"),
        CheckConstraint("id > 0", name="id_positive"),
        CheckConstraint("char_length(btrim(wa_id)) > 0", name="wa_id_not_blank"),
        CheckConstraint("state IN ('bot', 'waiting', 'human')", name="state_valid"),
        CheckConstraint("version >= 0", name="version_nonnegative"),
        CheckConstraint("summary IS NULL OR char_length(summary) <= 2000", name="summary_length"),
        CheckConstraint("jsonb_typeof(collection_asked) = 'array'", name="collection_asked_array"),
        Index("ix_conversations_state_updated_at", "state", "updated_at"),
        Index("ix_conversations_latest_inbound_at", "latest_inbound_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(start=1), primary_key=True)
    wa_id: Mapped[str] = mapped_column(Text, nullable=False)
    contact_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_field: Mapped[str | None] = mapped_column(Text, nullable=True)
    preferred_contact_time: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    alternative_phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=ConversationState.BOT.value,
        server_default=text("'bot'"),
    )
    version: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    assigned_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id"),
        nullable=True,
    )
    handoff_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    collection_asked: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    collection_stopped: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    latest_inbound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("provider_message_id", name="uq_messages_provider_message_id"),
        UniqueConstraint("client_request_id", name="uq_messages_client_request_id"),
        CheckConstraint("direction IN ('inbound', 'outbound')", name="direction_valid"),
        CheckConstraint(
            "author IN ('customer', 'bot', 'employee', 'system')",
            name="author_valid",
        ),
        CheckConstraint(
            "status IN ('received', 'pending', 'sending', 'accepted', 'delivered', "
            "'read', 'failed', 'unknown', 'cancelled')",
            name="status_valid",
        ),
        CheckConstraint(
            "body IS NULL OR "
            "(direction = 'inbound' AND char_length(body) <= 8000) OR "
            "(direction = 'outbound' AND char_length(body) <= 3000)",
            name="body_length",
        ),
        Index("ix_messages_conversation_created_at", "conversation_id", "created_at", "id"),
        Index(
            "uq_messages_bot_trigger_message_id",
            "trigger_message_id",
            unique=True,
            postgresql_where=text(
                "author = 'bot' AND direction = 'outbound' AND trigger_message_id IS NOT NULL"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("conversations.id"),
        nullable=False,
    )
    provider_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    trigger_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    provider_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("inbound_message_id", name="uq_jobs_inbound_message_id"),
        UniqueConstraint("enqueue_sequence", name="uq_jobs_enqueue_sequence"),
        CheckConstraint("enqueue_sequence > 0", name="enqueue_sequence_positive"),
        CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed', 'cancelled')",
            name="status_valid",
        ),
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        CheckConstraint(
            "captured_version IS NULL OR captured_version >= 0",
            name="captured_version_nonnegative",
        ),
        Index("ix_jobs_claimable", "status", "available_at", "enqueue_sequence"),
        Index("ix_jobs_conversation_sequence", "conversation_id", "enqueue_sequence"),
        Index(
            "uq_jobs_one_running_per_conversation",
            "conversation_id",
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("conversations.id"),
        nullable=False,
    )
    inbound_message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id"),
        nullable=False,
    )
    enqueue_sequence: Mapped[int] = mapped_column(
        BigInteger,
        Identity(start=1),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=JobStatus.QUEUED.value,
        server_default=text("'queued'"),
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claim_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    captured_version: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
