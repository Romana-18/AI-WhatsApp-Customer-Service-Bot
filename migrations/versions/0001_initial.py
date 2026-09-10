"""Create the initial KAALEX application schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "employees",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(password_hash) > 0",
            name="ck_employees_password_hash_not_blank",
        ),
        sa.CheckConstraint(
            "char_length(btrim(username)) > 0",
            name="ck_employees_username_not_blank",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_employees"),
        sa.UniqueConstraint("username", name="uq_employees_username"),
    )

    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("csrf_token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(csrf_token_hash) > 0",
            name="ck_sessions_csrf_token_hash_not_blank",
        ),
        sa.CheckConstraint(
            "char_length(token_hash) > 0",
            name="ck_sessions_token_hash_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            name="fk_sessions_employee_id_employees",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
        sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
    )
    op.create_index(
        "ix_sessions_employee_expires_at",
        "sessions",
        ["employee_id", "expires_at"],
        unique=False,
    )

    op.create_table(
        "conversations",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=False, start=1),
            nullable=False,
        ),
        sa.Column("wa_id", sa.Text(), nullable=False),
        sa.Column("contact_name", sa.Text(), nullable=True),
        sa.Column("business_field", sa.Text(), nullable=True),
        sa.Column("preferred_contact_time", sa.Text(), nullable=True),
        sa.Column("project_details", sa.Text(), nullable=True),
        sa.Column("alternative_phone", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), server_default=sa.text("'bot'"), nullable=False),
        sa.Column("version", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("assigned_employee_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("handoff_reason", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "collection_asked",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "collection_stopped",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("latest_inbound_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(collection_asked) = 'array'",
            name="ck_conversations_collection_asked_array",
        ),
        sa.CheckConstraint("id > 0", name="ck_conversations_id_positive"),
        sa.CheckConstraint(
            "state IN ('bot', 'waiting', 'human')",
            name="ck_conversations_state_valid",
        ),
        sa.CheckConstraint(
            "summary IS NULL OR char_length(summary) <= 2000",
            name="ck_conversations_summary_length",
        ),
        sa.CheckConstraint("version >= 0", name="ck_conversations_version_nonnegative"),
        sa.CheckConstraint(
            "char_length(btrim(wa_id)) > 0",
            name="ck_conversations_wa_id_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_employee_id"],
            ["employees.id"],
            name="fk_conversations_assigned_employee_id_employees",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
        sa.UniqueConstraint("wa_id", name="uq_conversations_wa_id"),
    )
    op.create_index(
        "ix_conversations_latest_inbound_at",
        "conversations",
        ["latest_inbound_at"],
        unique=False,
    )
    op.create_index(
        "ix_conversations_state_updated_at",
        "conversations",
        ["state", "updated_at"],
        unique=False,
    )

    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("provider_message_id", sa.Text(), nullable=True),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("author", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("media_type", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("client_request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("trigger_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("provider_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "author IN ('customer', 'bot', 'employee', 'system')",
            name="ck_messages_author_valid",
        ),
        sa.CheckConstraint(
            "body IS NULL OR "
            "(direction = 'inbound' AND char_length(body) <= 8000) OR "
            "(direction = 'outbound' AND char_length(body) <= 3000)",
            name="ck_messages_body_length",
        ),
        sa.CheckConstraint(
            "direction IN ('inbound', 'outbound')",
            name="ck_messages_direction_valid",
        ),
        sa.CheckConstraint(
            "status IN ('received', 'pending', 'sending', 'accepted', 'delivered', "
            "'read', 'failed', 'unknown', 'cancelled')",
            name="ck_messages_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_messages_conversation_id_conversations",
        ),
        sa.ForeignKeyConstraint(
            ["trigger_message_id"],
            ["messages.id"],
            name="fk_messages_trigger_message_id_messages",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_messages"),
        sa.UniqueConstraint("client_request_id", name="uq_messages_client_request_id"),
        sa.UniqueConstraint("provider_message_id", name="uq_messages_provider_message_id"),
    )
    op.create_index(
        "ix_messages_conversation_created_at",
        "messages",
        ["conversation_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "uq_messages_bot_trigger_message_id",
        "messages",
        ["trigger_message_id"],
        unique=True,
        postgresql_where=sa.text(
            "author = 'bot' AND direction = 'outbound' AND trigger_message_id IS NOT NULL"
        ),
    )

    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("inbound_message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "enqueue_sequence",
            sa.BigInteger(),
            sa.Identity(always=False, start=1),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("captured_version", sa.BigInteger(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_jobs_attempt_count_nonnegative",
        ),
        sa.CheckConstraint(
            "captured_version IS NULL OR captured_version >= 0",
            name="ck_jobs_captured_version_nonnegative",
        ),
        sa.CheckConstraint(
            "enqueue_sequence > 0",
            name="ck_jobs_enqueue_sequence_positive",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed', 'cancelled')",
            name="ck_jobs_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_jobs_conversation_id_conversations",
        ),
        sa.ForeignKeyConstraint(
            ["inbound_message_id"],
            ["messages.id"],
            name="fk_jobs_inbound_message_id_messages",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_jobs"),
        sa.UniqueConstraint("enqueue_sequence", name="uq_jobs_enqueue_sequence"),
        sa.UniqueConstraint("inbound_message_id", name="uq_jobs_inbound_message_id"),
    )
    op.create_index(
        "ix_jobs_claimable",
        "jobs",
        ["status", "available_at", "enqueue_sequence"],
        unique=False,
    )
    op.create_index(
        "ix_jobs_conversation_sequence",
        "jobs",
        ["conversation_id", "enqueue_sequence"],
        unique=False,
    )
    op.create_index(
        "uq_jobs_one_running_per_conversation",
        "jobs",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )


def downgrade() -> None:
    op.drop_index("uq_jobs_one_running_per_conversation", table_name="jobs")
    op.drop_index("ix_jobs_conversation_sequence", table_name="jobs")
    op.drop_index("ix_jobs_claimable", table_name="jobs")
    op.drop_table("jobs")

    op.drop_index("uq_messages_bot_trigger_message_id", table_name="messages")
    op.drop_index("ix_messages_conversation_created_at", table_name="messages")
    op.drop_table("messages")

    op.drop_index("ix_conversations_state_updated_at", table_name="conversations")
    op.drop_index("ix_conversations_latest_inbound_at", table_name="conversations")
    op.drop_table("conversations")

    op.drop_index("ix_sessions_employee_expires_at", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("employees")
