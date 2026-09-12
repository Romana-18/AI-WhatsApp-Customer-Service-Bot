"""Conversation ownership, optimistic versions, and PostgreSQL advisory locking."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from app.db import create_session_maker
from app.models import (
    Conversation,
    ConversationState,
    Job,
    JobStatus,
    Message,
    MessageAuthor,
    MessageDirection,
    MessageStatus,
)
from app.policy import automated_action_allowed
from app.schemas import AutomatedAction, HandoffReason, OwnershipSnapshot

MAX_ADVISORY_KEY = 2**63 - 1


class OwnershipError(RuntimeError):
    """Base error for ownership operations."""


class ConversationNotFoundError(OwnershipError):
    """Raised when an ownership target does not exist."""


class OwnershipConflictError(OwnershipError):
    """Raised when an expected conversation version is stale."""


class InvalidOwnershipTransitionError(OwnershipError):
    """Raised when the current state does not allow a transition."""


class AdvisoryLockError(OwnershipError):
    """Raised when the PostgreSQL session advisory gate cannot be used safely."""


async def _discard_connection(connection: AsyncConnection) -> None:
    try:
        await connection.invalidate()
    finally:
        await connection.close()


@asynccontextmanager
async def conversation_advisory_lock(
    engine: AsyncEngine, conversation_id: int
) -> AsyncIterator[AsyncConnection]:
    """Hold one PostgreSQL session lock on a dedicated autocommit connection."""

    if not 0 < conversation_id <= MAX_ADVISORY_KEY:
        raise ValueError("conversation_id must be a positive signed BIGINT")

    connection = await engine.connect()
    locked = False
    body_error: BaseException | None = None
    try:
        connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await connection.execute(
            text("SELECT pg_advisory_lock(:conversation_id)"),
            {"conversation_id": conversation_id},
        )
        locked = True
        yield connection
    except BaseException as exc:
        body_error = exc
        if not locked:
            await _discard_connection(connection)
        raise
    finally:
        if locked:
            try:
                released = await connection.scalar(
                    text("SELECT pg_advisory_unlock(:conversation_id)"),
                    {"conversation_id": conversation_id},
                )
                if released is not True:
                    raise AdvisoryLockError("PostgreSQL advisory lock was not held at release")
            except BaseException as exc:
                await _discard_connection(connection)
                if body_error is None:
                    raise AdvisoryLockError("PostgreSQL advisory lock release failed") from exc
            else:
                await connection.close()


def _snapshot(conversation: Conversation) -> OwnershipSnapshot:
    reason = (
        HandoffReason(conversation.handoff_reason)
        if conversation.handoff_reason is not None
        else None
    )
    return OwnershipSnapshot(
        conversation_id=conversation.id,
        state=ConversationState(conversation.state),
        version=conversation.version,
        assigned_employee_id=conversation.assigned_employee_id,
        handoff_reason=reason,
        collection_stopped=conversation.collection_stopped,
    )


async def _load_conversation(session: AsyncSession, conversation_id: int) -> Conversation:
    conversation = await session.scalar(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    if conversation is None:
        raise ConversationNotFoundError(f"conversation {conversation_id} was not found")
    return conversation


def _require_version(conversation: Conversation, expected_version: int | None) -> None:
    if expected_version is not None and conversation.version != expected_version:
        raise OwnershipConflictError(
            f"stale ownership version: expected {expected_version}, current {conversation.version}"
        )


async def read_ownership(engine: AsyncEngine, conversation_id: int) -> OwnershipSnapshot:
    """Read committed ownership without retaining a transaction or advisory lock."""

    session_maker = create_session_maker(engine)
    async with session_maker() as session:
        conversation = await _load_conversation(session, conversation_id)
        return _snapshot(conversation)


def apply_explicit_handoff_in_transaction(
    conversation: Conversation, reason: HandoffReason | str
) -> bool:
    """Apply the T05 inbound transition inside its caller-owned locked transaction."""

    if conversation.state != ConversationState.BOT.value:
        return False
    conversation.state = ConversationState.WAITING.value
    conversation.version += 1
    conversation.handoff_reason = HandoffReason(reason).value
    return True


async def queue_handoff(
    engine: AsyncEngine,
    conversation_id: int,
    reason: HandoffReason | str,
    *,
    expected_version: int | None = None,
) -> OwnershipSnapshot:
    """Immediately queue a bot-owned conversation; repeated requests are idempotent."""

    handoff_reason = HandoffReason(reason)
    async with conversation_advisory_lock(engine, conversation_id):
        session_maker = create_session_maker(engine)
        async with session_maker() as session:
            conversation = await _load_conversation(session, conversation_id)
            _require_version(conversation, expected_version)
            if apply_explicit_handoff_in_transaction(conversation, handoff_reason):
                await session.commit()
            return _snapshot(conversation)


async def take_over(
    engine: AsyncEngine,
    conversation_id: int,
    employee_id: uuid.UUID,
    *,
    expected_version: int,
) -> OwnershipSnapshot:
    """Serialize a bot/waiting to human transition and assign the sole employee."""

    async with conversation_advisory_lock(engine, conversation_id):
        session_maker = create_session_maker(engine)
        async with session_maker() as session:
            conversation = await _load_conversation(session, conversation_id)
            _require_version(conversation, expected_version)
            if conversation.state not in {
                ConversationState.BOT.value,
                ConversationState.WAITING.value,
            }:
                raise InvalidOwnershipTransitionError(
                    f"cannot take over conversation in state {conversation.state}"
                )
            conversation.state = ConversationState.HUMAN.value
            conversation.version += 1
            conversation.assigned_employee_id = employee_id
            await session.commit()
            return _snapshot(conversation)


async def release_to_bot(
    engine: AsyncEngine,
    conversation_id: int,
    *,
    expected_version: int,
) -> OwnershipSnapshot:
    """Serialize human release, increment version, and cancel queued pre-release jobs."""

    async with conversation_advisory_lock(engine, conversation_id):
        session_maker = create_session_maker(engine)
        async with session_maker() as session:
            conversation = await _load_conversation(session, conversation_id)
            _require_version(conversation, expected_version)
            if conversation.state != ConversationState.HUMAN.value:
                raise InvalidOwnershipTransitionError(
                    f"cannot release conversation in state {conversation.state}"
                )
            conversation.state = ConversationState.BOT.value
            conversation.version += 1
            conversation.assigned_employee_id = None
            conversation.handoff_reason = None
            await session.execute(
                update(Job)
                .where(
                    Job.conversation_id == conversation_id,
                    Job.status == JobStatus.QUEUED.value,
                )
                .values(status=JobStatus.CANCELLED.value)
            )
            await session.execute(
                update(Message)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.direction == MessageDirection.OUTBOUND.value,
                    Message.author == MessageAuthor.BOT.value,
                    Message.status == MessageStatus.PENDING.value,
                )
                .values(status=MessageStatus.CANCELLED.value)
            )
            await session.commit()
            return _snapshot(conversation)


async def stop_collection(
    engine: AsyncEngine,
    conversation_id: int,
    *,
    expected_version: int,
) -> OwnershipSnapshot:
    """Honor collection refusal without removing the conversation from the queue."""

    async with conversation_advisory_lock(engine, conversation_id):
        session_maker = create_session_maker(engine)
        async with session_maker() as session:
            conversation = await _load_conversation(session, conversation_id)
            _require_version(conversation, expected_version)
            if conversation.state != ConversationState.WAITING.value:
                raise InvalidOwnershipTransitionError(
                    "contact collection can stop only while waiting"
                )
            conversation.collection_stopped = True
            await session.commit()
            return _snapshot(conversation)


def automation_result_is_current(
    ownership: OwnershipSnapshot,
    captured_version: int,
    action: AutomatedAction | str,
) -> bool:
    """Reject stale or state-incompatible output without refreshing its version."""

    requested_action = AutomatedAction(action)
    if requested_action is AutomatedAction.COLLECT and ownership.collection_stopped:
        return False
    return ownership.version == captured_version and automated_action_allowed(
        ownership.state, requested_action
    )
