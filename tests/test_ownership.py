"""T03 PostgreSQL ownership, version, and advisory-lock integration tests."""

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.config import Settings
from app.db import create_database_engine, create_session_maker
from app.models import Conversation, Employee, Job, Message
from app.ownership import (
    InvalidOwnershipTransitionError,
    OwnershipConflictError,
    apply_explicit_handoff_in_transaction,
    automation_result_is_current,
    conversation_advisory_lock,
    queue_handoff,
    read_ownership,
    release_to_bot,
    stop_collection,
    take_over,
)
from app.schemas import AutomatedAction, HandoffReason

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def ownership_test_url() -> Iterator[URL]:
    settings = Settings()
    if settings.test_database_url is None:
        pytest.fail("TEST_DATABASE_URL is required for ownership integration tests")

    application_url = make_url(str(settings.database_url))
    test_url = make_url(str(settings.test_database_url))
    if test_url.host != "test-db" or test_url.database != "kaalex_test":
        pytest.fail("Refusing ownership tests outside test-db/kaalex_test")
    if application_url.host == test_url.host and application_url.database == test_url.database:
        pytest.fail("Refusing ownership tests against the application database")

    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection_url"] = test_url
    command.upgrade(config, "head")
    yield test_url


@pytest_asyncio.fixture(scope="module")
async def ownership_engine(ownership_test_url: URL) -> AsyncIterator[AsyncEngine]:
    engine = create_database_engine(ownership_test_url)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def clean_database(ownership_engine: AsyncEngine) -> AsyncIterator[None]:
    async with ownership_engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE TABLE jobs, messages, conversations, sessions, employees "
                "RESTART IDENTITY CASCADE"
            )
        )
    yield
    async with ownership_engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE TABLE jobs, messages, conversations, sessions, employees "
                "RESTART IDENTITY CASCADE"
            )
        )


async def _employee_and_conversation(
    engine: AsyncEngine,
    *,
    state: str = "bot",
    version: int = 0,
) -> tuple[uuid.UUID, int]:
    session_maker = create_session_maker(engine)
    async with session_maker() as session:
        employee = Employee(
            username=f"synthetic-employee-{uuid.uuid4()}",
            password_hash="synthetic-password-hash",
        )
        conversation = Conversation(
            wa_id=f"synthetic-wa-{uuid.uuid4()}",
            state=state,
            version=version,
            latest_inbound_at=datetime.now(UTC),
        )
        session.add_all([employee, conversation])
        await session.commit()
        return employee.id, conversation.id


async def _queued_job(session: AsyncSession, conversation_id: int, captured_version: int) -> Job:
    inbound = Message(
        conversation_id=conversation_id,
        provider_message_id=f"synthetic-provider-{uuid.uuid4()}",
        direction="inbound",
        author="customer",
        body="Synthetic inbound",
        status="received",
    )
    session.add(inbound)
    await session.flush()
    job = Job(
        conversation_id=conversation_id,
        inbound_message_id=inbound.id,
        captured_version=captured_version,
    )
    session.add(job)
    await session.flush()
    return job


@pytest.mark.asyncio
async def test_explicit_handoff_queues_before_collection_and_is_idempotent(
    ownership_engine: AsyncEngine,
) -> None:
    _, conversation_id = await _employee_and_conversation(ownership_engine, version=4)

    waiting = await queue_handoff(
        ownership_engine,
        conversation_id,
        HandoffReason.HUMAN_REQUEST,
        expected_version=4,
    )
    assert waiting.state == "waiting"
    assert waiting.version == 5
    assert waiting.handoff_reason is HandoffReason.HUMAN_REQUEST
    assert not waiting.collection_stopped

    repeated = await queue_handoff(
        ownership_engine,
        conversation_id,
        HandoffReason.PRICING,
        expected_version=5,
    )
    assert repeated.version == 5
    assert repeated.handoff_reason is HandoffReason.HUMAN_REQUEST


@pytest.mark.asyncio
async def test_inbound_transaction_can_capture_new_waiting_version(
    ownership_engine: AsyncEngine,
) -> None:
    _, conversation_id = await _employee_and_conversation(ownership_engine, version=3)
    session_maker = create_session_maker(ownership_engine)

    async with conversation_advisory_lock(ownership_engine, conversation_id):
        async with session_maker.begin() as session:
            conversation = await session.scalar(
                select(Conversation).where(Conversation.id == conversation_id)
            )
            assert conversation is not None
            assert apply_explicit_handoff_in_transaction(conversation, HandoffReason.HUMAN_REQUEST)
            job = await _queued_job(session, conversation_id, conversation.version)
            job_id = job.id

    async with session_maker() as session:
        stored_job = await session.scalar(select(Job).where(Job.id == job_id))
        assert stored_job is not None
        assert stored_job.captured_version == 4

    waiting = await read_ownership(ownership_engine, conversation_id)
    assert waiting.state == "waiting"
    assert waiting.version == 4


@pytest.mark.asyncio
async def test_collection_refusal_stays_waiting_and_stops_questions(
    ownership_engine: AsyncEngine,
) -> None:
    _, conversation_id = await _employee_and_conversation(ownership_engine)
    waiting = await queue_handoff(ownership_engine, conversation_id, HandoffReason.MEETING)

    refused = await stop_collection(
        ownership_engine,
        conversation_id,
        expected_version=waiting.version,
    )
    assert refused.state == "waiting"
    assert refused.version == waiting.version
    assert refused.collection_stopped
    assert not automation_result_is_current(refused, waiting.version, AutomatedAction.COLLECT)
    assert automation_result_is_current(
        refused, waiting.version, AutomatedAction.HANDOFF_ACKNOWLEDGEMENT
    )


@pytest.mark.asyncio
async def test_waiting_takeover_release_versions_never_revalidate_old_output(
    ownership_engine: AsyncEngine,
) -> None:
    employee_id, conversation_id = await _employee_and_conversation(ownership_engine, version=8)
    captured_bot_version = 8

    waiting = await queue_handoff(
        ownership_engine,
        conversation_id,
        HandoffReason.PRICING,
        expected_version=captured_bot_version,
    )
    assert waiting.version == 9

    human = await take_over(
        ownership_engine,
        conversation_id,
        employee_id,
        expected_version=waiting.version,
    )
    assert human.state == "human"
    assert human.version == 10
    assert human.assigned_employee_id == employee_id
    assert not automation_result_is_current(human, captured_bot_version, AutomatedAction.REPLY)

    session_maker = create_session_maker(ownership_engine)
    async with session_maker() as session:
        queued_job = await _queued_job(session, conversation_id, waiting.version)
        queued_job_id = queued_job.id
        pending_bot_message = Message(
            conversation_id=conversation_id,
            direction="outbound",
            author="bot",
            body="Synthetic pending pre-release output",
            status="pending",
            trigger_message_id=queued_job.inbound_message_id,
        )
        session.add(pending_bot_message)
        await session.commit()
        pending_bot_message_id = pending_bot_message.id

    released = await release_to_bot(
        ownership_engine,
        conversation_id,
        expected_version=human.version,
    )
    assert released.state == "bot"
    assert released.version == 11
    assert released.assigned_employee_id is None
    assert not automation_result_is_current(released, captured_bot_version, AutomatedAction.REPLY)
    assert not automation_result_is_current(released, waiting.version, AutomatedAction.REPLY)

    async with session_maker() as session:
        stored_job = await session.scalar(select(Job).where(Job.id == queued_job_id))
        stored_message = await session.scalar(
            select(Message).where(Message.id == pending_bot_message_id)
        )
        assert stored_job is not None
        assert stored_job.status == "cancelled"
        assert stored_message is not None
        assert stored_message.status == "cancelled"


@pytest.mark.asyncio
async def test_takeover_from_bot_increments_version(
    ownership_engine: AsyncEngine,
) -> None:
    employee_id, conversation_id = await _employee_and_conversation(ownership_engine)
    human = await take_over(
        ownership_engine,
        conversation_id,
        employee_id,
        expected_version=0,
    )
    assert human.state == "human"
    assert human.version == 1


@pytest.mark.asyncio
async def test_stale_expected_version_is_rejected_without_refresh(
    ownership_engine: AsyncEngine,
) -> None:
    employee_id, conversation_id = await _employee_and_conversation(ownership_engine, version=8)

    with pytest.raises(OwnershipConflictError, match="expected 7, current 8"):
        await take_over(
            ownership_engine,
            conversation_id,
            employee_id,
            expected_version=7,
        )

    unchanged = await read_ownership(ownership_engine, conversation_id)
    assert unchanged.state == "bot"
    assert unchanged.version == 8
    assert unchanged.assigned_employee_id is None


@pytest.mark.asyncio
async def test_invalid_transition_is_rejected(
    ownership_engine: AsyncEngine,
) -> None:
    _, conversation_id = await _employee_and_conversation(ownership_engine)
    with pytest.raises(InvalidOwnershipTransitionError):
        await release_to_bot(ownership_engine, conversation_id, expected_version=0)


@pytest.mark.asyncio
async def test_two_connections_serialize_takeover_with_send_gate_lock(
    ownership_engine: AsyncEngine,
) -> None:
    employee_id, conversation_id = await _employee_and_conversation(
        ownership_engine, state="waiting", version=1
    )

    async with conversation_advisory_lock(ownership_engine, conversation_id) as gate_connection:
        gate_backend = await gate_connection.scalar(text("SELECT pg_backend_pid()"))
        async with ownership_engine.connect() as independent_connection:
            independent_backend = await independent_connection.scalar(
                text("SELECT pg_backend_pid()")
            )
            acquired = await independent_connection.scalar(
                text("SELECT pg_try_advisory_lock(:conversation_id)"),
                {"conversation_id": conversation_id},
            )
        assert gate_backend != independent_backend
        assert acquired is False

        takeover = asyncio.create_task(
            take_over(
                ownership_engine,
                conversation_id,
                employee_id,
                expected_version=1,
            )
        )
        await asyncio.sleep(0.2)
        assert not takeover.done()

    human = await asyncio.wait_for(takeover, timeout=2)
    assert human.state == "human"
    assert human.version == 2


@pytest.mark.asyncio
async def test_no_lock_or_transaction_is_held_during_simulated_ai_wait(
    ownership_engine: AsyncEngine,
) -> None:
    _, conversation_id = await _employee_and_conversation(ownership_engine)
    started = asyncio.Event()
    finish = asyncio.Event()

    async def simulated_generation() -> None:
        snapshot = await read_ownership(ownership_engine, conversation_id)
        assert snapshot.state == "bot"
        started.set()
        await finish.wait()

    generation = asyncio.create_task(simulated_generation())
    await asyncio.wait_for(started.wait(), timeout=2)
    try:
        async with asyncio.timeout(2):
            async with conversation_advisory_lock(ownership_engine, conversation_id):
                pass
    finally:
        finish.set()
        await generation


@pytest.mark.asyncio
async def test_advisory_lock_is_released_after_exception(
    ownership_engine: AsyncEngine,
) -> None:
    _, conversation_id = await _employee_and_conversation(ownership_engine)

    with pytest.raises(RuntimeError, match="synthetic lock-body failure"):
        async with conversation_advisory_lock(ownership_engine, conversation_id):
            raise RuntimeError("synthetic lock-body failure")

    async with asyncio.timeout(2):
        async with conversation_advisory_lock(ownership_engine, conversation_id):
            pass
