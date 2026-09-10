"""T02 PostgreSQL schema, migration, constraint, and transaction tests."""

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.config import Settings
from app.db import create_database_engine, create_session_maker, session_scope
from app.models import Conversation, Job, Message

ROOT = Path(__file__).resolve().parents[1]
APPLICATION_TABLES = {"employees", "sessions", "conversations", "messages", "jobs"}
ALL_T02_TABLES = APPLICATION_TABLES | {"alembic_version"}


def _safe_target_evidence(application_url: URL, test_url: URL) -> dict[str, str]:
    return {
        "application_database": application_url.database or "",
        "test_target": f"{test_url.host}/{test_url.database}",
    }


def _safe_test_target() -> tuple[URL, dict[str, str]]:
    settings = Settings()
    if settings.test_database_url is None:
        pytest.fail("TEST_DATABASE_URL is required for PostgreSQL integration tests")

    application_url = make_url(str(settings.database_url))
    test_url = make_url(str(settings.test_database_url))
    if application_url == test_url:
        pytest.fail("Refusing destructive tests: TEST_DATABASE_URL matches DATABASE_URL")
    if test_url.host != "test-db" or test_url.database != "kaalex_test":
        pytest.fail("Refusing destructive tests: expected the Docker test-db/kaalex_test database")
    return test_url, _safe_target_evidence(application_url, test_url)


def _alembic_config(test_url: URL) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection_url"] = test_url
    return config


def _table_names(test_url: URL) -> set[str]:
    engine = create_engine(test_url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def migrated_test_database() -> Iterator[dict[str, object]]:
    test_url, safe_evidence = _safe_test_target()
    config = _alembic_config(test_url)

    command.downgrade(config, "base")
    empty_tables = _table_names(test_url)
    assert APPLICATION_TABLES.isdisjoint(empty_tables)

    command.upgrade(config, "head")
    first_upgrade_tables = _table_names(test_url)
    command.upgrade(config, "head")
    second_upgrade_tables = _table_names(test_url)

    command.downgrade(config, "base")
    downgraded_tables = _table_names(test_url)
    command.upgrade(config, "head")
    reupgraded_tables = _table_names(test_url)

    evidence: dict[str, object] = {
        **safe_evidence,
        "empty_tables": empty_tables,
        "first_upgrade_tables": first_upgrade_tables,
        "second_upgrade_tables": second_upgrade_tables,
        "downgraded_tables": downgraded_tables,
        "reupgraded_tables": reupgraded_tables,
    }
    yield evidence

    command.upgrade(config, "head")


@pytest_asyncio.fixture
async def database_engine(
    migrated_test_database: dict[str, object],
) -> AsyncIterator[AsyncEngine]:
    test_url, _ = _safe_test_target()
    engine = create_database_engine(test_url)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(database_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    maker = create_session_maker(database_engine)
    try:
        async with session_scope(maker) as session:
            yield session
    finally:
        async with database_engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE TABLE jobs, messages, conversations, sessions, employees "
                    "RESTART IDENTITY CASCADE"
                )
            )


async def _conversation(session: AsyncSession, wa_id: str | None = None) -> Conversation:
    conversation = Conversation(
        wa_id=wa_id or f"synthetic-{uuid.uuid4()}",
        latest_inbound_at=datetime.now(UTC),
    )
    session.add(conversation)
    await session.flush()
    return conversation


async def _inbound_message(
    session: AsyncSession,
    conversation: Conversation,
    provider_message_id: str | None = None,
) -> Message:
    message = Message(
        conversation_id=conversation.id,
        provider_message_id=provider_message_id,
        direction="inbound",
        author="customer",
        body="Synthetic inbound test message",
        status="received",
    )
    session.add(message)
    await session.flush()
    return message


def test_empty_upgrade_repeat_downgrade_and_reupgrade(
    migrated_test_database: dict[str, object],
) -> None:
    assert APPLICATION_TABLES.isdisjoint(migrated_test_database["empty_tables"])
    assert migrated_test_database["first_upgrade_tables"] == ALL_T02_TABLES
    assert migrated_test_database["second_upgrade_tables"] == ALL_T02_TABLES
    assert APPLICATION_TABLES.isdisjoint(migrated_test_database["downgraded_tables"])
    assert migrated_test_database["reupgraded_tables"] == ALL_T02_TABLES


def test_migration_contains_required_columns_constraints_and_indexes(
    migrated_test_database: dict[str, object],
) -> None:
    test_url, _ = _safe_test_target()
    engine = create_engine(test_url)
    try:
        inspector = inspect(engine)
        assert set(inspector.get_table_names()) == ALL_T02_TABLES

        conversation_columns = {
            column["name"]: column for column in inspector.get_columns("conversations")
        }
        job_columns = {column["name"]: column for column in inspector.get_columns("jobs")}
        message_columns = {column["name"]: column for column in inspector.get_columns("messages")}

        assert conversation_columns["id"]["identity"]["start"] == 1
        assert job_columns["enqueue_sequence"]["identity"]["start"] == 1
        assert conversation_columns["latest_inbound_at"]["type"].timezone is True
        assert message_columns["provider_timestamp"]["type"].timezone is True
        assert conversation_columns["collection_asked"]["type"].__class__.__name__ == "JSONB"

        job_indexes = {index["name"] for index in inspector.get_indexes("jobs")}
        message_indexes = {index["name"] for index in inspector.get_indexes("messages")}
        assert "uq_jobs_one_running_per_conversation" in job_indexes
        assert "ix_jobs_claimable" in job_indexes
        assert "uq_messages_bot_trigger_message_id" in message_indexes
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_application_and_test_databases_are_separate(
    database_engine: AsyncEngine,
    migrated_test_database: dict[str, object],
) -> None:
    assert migrated_test_database["application_database"] == "kaalex"
    async with database_engine.connect() as connection:
        database_name = await connection.scalar(text("SELECT current_database()"))
    assert database_name == "kaalex_test"


def test_safe_database_evidence_excludes_password() -> None:
    password = "synthetic-password-that-must-not-leak"
    application_url = make_url("postgresql+psycopg://app:app-secret@db/kaalex")
    test_url = make_url(f"postgresql+psycopg://test:{password}@test-db/kaalex_test")

    evidence = _safe_target_evidence(application_url, test_url)

    assert evidence == {
        "application_database": "kaalex",
        "test_target": "test-db/kaalex_test",
    }
    assert password not in str(test_url)
    assert password not in repr(test_url)
    assert password not in repr(evidence)


def test_sqlite_engine_is_refused() -> None:
    with pytest.raises(ValueError, match="SQLite is not supported"):
        create_database_engine("sqlite+aiosqlite:///synthetic.db")


@pytest.mark.asyncio
async def test_session_maker_creates_separate_sessions(database_engine: AsyncEngine) -> None:
    maker = create_session_maker(database_engine)
    async with session_scope(maker) as first_session:
        async with session_scope(maker) as second_session:
            assert first_session is not second_session


@pytest.mark.asyncio
async def test_duplicate_wa_id_is_rejected(db_session: AsyncSession) -> None:
    await _conversation(db_session, "synthetic-duplicate-wa-id")
    await db_session.commit()

    db_session.add(
        Conversation(
            wa_id="synthetic-duplicate-wa-id",
            latest_inbound_at=datetime.now(UTC),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_duplicate_provider_message_id_is_rejected(db_session: AsyncSession) -> None:
    conversation = await _conversation(db_session)
    await _inbound_message(db_session, conversation, "synthetic-provider-id")
    await db_session.commit()

    db_session.add(
        Message(
            conversation_id=conversation.id,
            provider_message_id="synthetic-provider-id",
            direction="inbound",
            author="customer",
            body="Synthetic duplicate provider message",
            status="received",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_duplicate_client_request_id_is_rejected(db_session: AsyncSession) -> None:
    conversation = await _conversation(db_session)
    request_id = uuid.uuid4()
    db_session.add(
        Message(
            conversation_id=conversation.id,
            direction="outbound",
            author="employee",
            body="Synthetic employee message",
            status="pending",
            client_request_id=request_id,
        )
    )
    await db_session.commit()

    db_session.add(
        Message(
            conversation_id=conversation.id,
            direction="outbound",
            author="employee",
            body="Synthetic duplicate browser request",
            status="pending",
            client_request_id=request_id,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_duplicate_job_inbound_message_id_is_rejected(db_session: AsyncSession) -> None:
    conversation = await _conversation(db_session)
    inbound = await _inbound_message(db_session, conversation)
    db_session.add(Job(conversation_id=conversation.id, inbound_message_id=inbound.id))
    await db_session.commit()

    db_session.add(Job(conversation_id=conversation.id, inbound_message_id=inbound.id))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_foreign_keys_reject_orphan_records(db_session: AsyncSession) -> None:
    db_session.add(
        Message(
            conversation_id=9_999_999,
            direction="inbound",
            author="customer",
            body="Synthetic orphan",
            status="received",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_invalid_conversation_state_is_rejected(db_session: AsyncSession) -> None:
    db_session.add(
        Conversation(
            wa_id="synthetic-invalid-state",
            state="invalid",
            latest_inbound_at=datetime.now(UTC),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_invalid_message_status_is_rejected(db_session: AsyncSession) -> None:
    conversation = await _conversation(db_session)
    db_session.add(
        Message(
            conversation_id=conversation.id,
            direction="inbound",
            author="customer",
            body="Synthetic invalid status",
            status="invalid",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_invalid_job_status_is_rejected(db_session: AsyncSession) -> None:
    conversation = await _conversation(db_session)
    inbound = await _inbound_message(db_session, conversation)
    db_session.add(
        Job(
            conversation_id=conversation.id,
            inbound_message_id=inbound.id,
            status="invalid",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_only_one_running_job_per_conversation(db_session: AsyncSession) -> None:
    conversation = await _conversation(db_session)
    first_inbound = await _inbound_message(db_session, conversation)
    second_inbound = await _inbound_message(db_session, conversation)
    db_session.add_all(
        [
            Job(
                conversation_id=conversation.id,
                inbound_message_id=first_inbound.id,
                status="running",
            ),
            Job(
                conversation_id=conversation.id,
                inbound_message_id=second_inbound.id,
                status="running",
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_only_one_bot_output_per_trigger_message(db_session: AsyncSession) -> None:
    conversation = await _conversation(db_session)
    inbound = await _inbound_message(db_session, conversation)
    db_session.add_all(
        [
            Message(
                conversation_id=conversation.id,
                direction="outbound",
                author="bot",
                body="Synthetic bot reply one",
                status="pending",
                trigger_message_id=inbound.id,
            ),
            Message(
                conversation_id=conversation.id,
                direction="outbound",
                author="bot",
                body="Synthetic bot reply two",
                status="pending",
                trigger_message_id=inbound.id,
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_inbound_and_job_transaction_roll_back_together(db_session: AsyncSession) -> None:
    conversation = await _conversation(db_session)
    await db_session.commit()
    conversation_id = conversation.id

    inbound = Message(
        conversation_id=conversation_id,
        provider_message_id="synthetic-rollback-provider-id",
        direction="inbound",
        author="customer",
        body="Synthetic rollback message",
        status="received",
    )

    with pytest.raises(RuntimeError, match="synthetic transaction failure"):
        async with db_session.begin():
            db_session.add(inbound)
            await db_session.flush()
            db_session.add(Job(conversation_id=conversation_id, inbound_message_id=inbound.id))
            await db_session.flush()
            raise RuntimeError("synthetic transaction failure")

    message_count = await db_session.scalar(
        select(func.count()).select_from(Message).where(Message.conversation_id == conversation_id)
    )
    job_count = await db_session.scalar(
        select(func.count()).select_from(Job).where(Job.conversation_id == conversation_id)
    )
    assert message_count == 0
    assert job_count == 0


@pytest.mark.asyncio
async def test_enqueue_sequence_increases_deterministically(db_session: AsyncSession) -> None:
    conversation = await _conversation(db_session)
    inbound_messages = [await _inbound_message(db_session, conversation) for _ in range(3)]
    jobs = [
        Job(conversation_id=conversation.id, inbound_message_id=message.id)
        for message in inbound_messages
    ]
    db_session.add_all(jobs)
    await db_session.flush()

    assigned_sequences = [job.enqueue_sequence for job in jobs]
    stored_sequences = list(
        (
            await db_session.scalars(
                select(Job.enqueue_sequence)
                .where(Job.conversation_id == conversation.id)
                .order_by(Job.enqueue_sequence)
            )
        ).all()
    )

    assert assigned_sequences == sorted(assigned_sequences)
    assert len(set(assigned_sequences)) == 3
    assert stored_sequences == assigned_sequences
