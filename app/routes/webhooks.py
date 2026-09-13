"""Meta webhook verification plus durable inbound and status persistence."""

from __future__ import annotations

import hmac
import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.config import MAX_WEBHOOK_BODY_BYTES, Settings
from app.db import create_session_maker
from app.models import (
    Conversation,
    Job,
    Message,
    MessageAuthor,
    MessageDirection,
    MessageStatus,
)
from app.ownership import apply_explicit_handoff_in_transaction, conversation_advisory_lock
from app.policy import explicit_handoff_reason
from app.schemas import HandoffReason
from app.whatsapp import (
    InboundMessageEvent,
    StatusEvent,
    WebhookPayloadError,
    normalize_webhook_payload,
    verify_webhook_signature,
)

router = APIRouter()


def _error(status_code: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"code": code, "detail": detail})


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _database_engine(request: Request) -> AsyncEngine:
    return request.app.state.database_engine


def _verify_token(settings: Settings) -> str | None:
    if settings.whatsapp_verify_token is None:
        return None
    return settings.whatsapp_verify_token.get_secret_value()


def _app_secret(settings: Settings) -> str | None:
    if settings.whatsapp_app_secret is None:
        return None
    return settings.whatsapp_app_secret.get_secret_value()


@router.get("/webhooks/whatsapp")
async def verify_webhook(request: Request):
    """Return Meta's challenge only for the configured verification token and subscribe mode."""

    settings = _settings(request)
    challenge = request.query_params.get("hub.challenge")
    supplied_token = request.query_params.get("hub.verify_token")
    expected_token = _verify_token(settings)
    if (
        request.query_params.get("hub.mode") != "subscribe"
        or challenge is None
        or expected_token is None
        or not hmac.compare_digest(supplied_token or "", expected_token)
    ):
        return _error(403, "webhook_verification_rejected", "Webhook verification was rejected")
    return PlainTextResponse(challenge)


@router.post("/webhooks/whatsapp")
async def receive_webhook(request: Request) -> JSONResponse:
    """Verify raw Meta bytes before parsing and durably process every supported event."""

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > MAX_WEBHOOK_BODY_BYTES:
                return _error(413, "webhook_too_large", "Webhook request is too large")
        except ValueError:
            return _error(400, "invalid_webhook_request", "Webhook request is invalid")

    body = await _read_limited_body(request)
    if body is None:
        return _error(413, "webhook_too_large", "Webhook request is too large")

    app_secret = _app_secret(_settings(request))
    if app_secret is None or not verify_webhook_signature(
        body, request.headers.get("x-hub-signature-256"), app_secret
    ):
        return _error(401, "invalid_webhook_signature", "Webhook signature is invalid")

    try:
        payload = json.loads(body)
        inbound_events, status_events = normalize_webhook_payload(payload)
    except (json.JSONDecodeError, WebhookPayloadError):
        return _error(400, "invalid_webhook_payload", "Webhook payload is invalid")

    engine = _database_engine(request)
    try:
        for event in inbound_events:
            await persist_inbound_event(engine, event)
        for event in status_events:
            await apply_status_event(engine, event)
    except SQLAlchemyError:
        return _error(
            503, "webhook_persistence_failed", "Webhook persistence is temporarily unavailable"
        )
    return JSONResponse(content={"status": "ok"})


async def _read_limited_body(request: Request) -> bytes | None:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_WEBHOOK_BODY_BYTES:
            return None
    return bytes(body)


async def persist_inbound_event(engine: AsyncEngine, event: InboundMessageEvent) -> bool:
    """Persist one customer inbound and its job atomically; duplicates are acknowledged."""

    session_maker = create_session_maker(engine)
    async with session_maker() as lookup_session:
        conversation_id = await lookup_session.scalar(
            select(Conversation.id).where(Conversation.wa_id == event.wa_id)
        )

    if conversation_id is None:
        return await _persist_new_conversation_event(engine, event)

    async with conversation_advisory_lock(engine, conversation_id):
        return await _persist_for_conversation(engine, event, conversation_id)


async def _persist_new_conversation_event(engine: AsyncEngine, event: InboundMessageEvent) -> bool:
    """Create a new conversation and event in one transaction, handling the create race once."""

    session_maker = create_session_maker(engine)
    try:
        async with session_maker() as session:
            async with session.begin():
                conversation = Conversation(wa_id=event.wa_id, latest_inbound_at=event.occurred_at)
                session.add(conversation)
                await session.flush()
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(:conversation_id)"),
                    {"conversation_id": conversation.id},
                )
                await _store_inbound_and_job(session, conversation, event)
        return True
    except IntegrityError:
        return await _persist_after_integrity_error(engine, event)


async def _persist_for_conversation(
    engine: AsyncEngine,
    event: InboundMessageEvent,
    conversation_id: int,
) -> bool:
    session_maker = create_session_maker(engine)
    try:
        async with session_maker() as session:
            async with session.begin():
                conversation = await session.scalar(
                    select(Conversation).where(Conversation.id == conversation_id).with_for_update()
                )
                if conversation is None:
                    raise SQLAlchemyError("conversation disappeared during inbound persistence")
                await _store_inbound_and_job(session, conversation, event)
        return True
    except IntegrityError:
        return await _persist_after_integrity_error(engine, event)


async def _persist_after_integrity_error(engine: AsyncEngine, event: InboundMessageEvent) -> bool:
    """Acknowledge only a confirmed provider-message duplicate; otherwise retain the failure."""

    session_maker = create_session_maker(engine)
    async with session_maker() as session:
        duplicate = await session.scalar(
            select(Message.id).where(Message.provider_message_id == event.provider_message_id)
        )
    if duplicate is not None:
        return False

    async with session_maker() as session:
        conversation_id = await session.scalar(
            select(Conversation.id).where(Conversation.wa_id == event.wa_id)
        )
    if conversation_id is None:
        raise SQLAlchemyError("inbound persistence conflict was not a duplicate")
    async with conversation_advisory_lock(engine, conversation_id):
        return await _persist_for_conversation(engine, event, conversation_id)


async def _store_inbound_and_job(
    session: AsyncSession,
    conversation: Conversation,
    event: InboundMessageEvent,
) -> None:
    if event.occurred_at > conversation.latest_inbound_at:
        conversation.latest_inbound_at = event.occurred_at
    message = Message(
        conversation_id=conversation.id,
        provider_message_id=event.provider_message_id,
        direction=MessageDirection.INBOUND.value,
        author=MessageAuthor.CUSTOMER.value,
        body=event.body,
        media_type=event.media_type,
        status=MessageStatus.RECEIVED.value,
        provider_timestamp=event.occurred_at,
    )
    session.add(message)
    await session.flush()

    handoff_reason = explicit_handoff_reason(event.body) if event.body is not None else None
    if handoff_reason is None and (event.was_truncated or event.media_type is not None):
        handoff_reason = HandoffReason.MISSING_INFORMATION
    if handoff_reason is not None:
        apply_explicit_handoff_in_transaction(conversation, handoff_reason)

    session.add(
        Job(
            conversation_id=conversation.id,
            inbound_message_id=message.id,
            captured_version=conversation.version,
        )
    )
    await session.flush()


async def apply_status_event(engine: AsyncEngine, event: StatusEvent) -> None:
    """Apply a non-regressing Meta status to its exact outbound message and create no job."""

    session_maker = create_session_maker(engine)
    async with session_maker() as session:
        async with session.begin():
            message = await session.scalar(
                select(Message)
                .where(
                    Message.provider_message_id == event.provider_message_id,
                    Message.direction == MessageDirection.OUTBOUND.value,
                )
                .with_for_update()
            )
            if message is None or not _status_transition_allowed(message.status, event.status):
                return
            message.status = event.status
            if event.error_code is not None:
                message.error_code = event.error_code
            if event.occurred_at is not None:
                message.provider_timestamp = event.occurred_at


def _status_transition_allowed(current: str, incoming: str) -> bool:
    if incoming == current:
        return False
    if current in {MessageStatus.READ.value, MessageStatus.CANCELLED.value}:
        return False
    if current == MessageStatus.DELIVERED.value:
        return incoming == MessageStatus.READ.value
    if current == MessageStatus.ACCEPTED.value:
        return incoming in {
            MessageStatus.DELIVERED.value,
            MessageStatus.READ.value,
            MessageStatus.FAILED.value,
        }
    if current == MessageStatus.SENDING.value:
        return incoming in {
            MessageStatus.ACCEPTED.value,
            MessageStatus.DELIVERED.value,
            MessageStatus.READ.value,
            MessageStatus.FAILED.value,
        }
    return False
