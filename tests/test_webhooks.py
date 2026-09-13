"""T05 signed Meta webhook, durable persistence, and transport tests."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import func, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.config import MAX_INBOUND_TEXT_LENGTH, MAX_WEBHOOK_BODY_BYTES, Settings
from app.db import create_database_engine, create_session_maker, session_scope
from app.models import (
    Conversation,
    ConversationState,
    Job,
    Message,
    MessageStatus,
)
from app.ownership import automation_result_is_current, read_ownership
from app.routes import webhooks
from app.routes.webhooks import router
from app.schemas import AutomatedAction
from app.whatsapp import MetaSendOutcome, send_text_message

ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = "postgresql+psycopg://app_user:synthetic@db:5432/kaalex"
TEST_DATABASE_URL = "postgresql+psycopg://test_user:synthetic@test-db:5432/kaalex_test"
APP_SECRET = "synthetic-meta-app-secret"
VERIFY_TOKEN = "synthetic-meta-verify-token"


def _settings() -> Settings:
    return Settings(
        database_url=DATABASE_URL,
        test_database_url=TEST_DATABASE_URL,
        app_env="local",
        public_base_url="http://127.0.0.1:8000",
        huggingface_enabled=False,
        whatsapp_enabled=True,
        whatsapp_access_token="synthetic-access-token",
        whatsapp_phone_number_id="123456789",
        whatsapp_app_secret=APP_SECRET,
        whatsapp_verify_token=VERIFY_TOKEN,
        whatsapp_graph_version="v99.0",
    )


def _test_url() -> URL:
    settings = Settings()
    if settings.test_database_url is None:
        pytest.fail("TEST_DATABASE_URL is required for T05 PostgreSQL tests")
    test_url = make_url(str(settings.test_database_url))
    if test_url.host != "test-db" or test_url.database != "kaalex_test":
        pytest.fail("T05 tests require isolated Docker test-db/kaalex_test")
    return test_url


@pytest.fixture(scope="session", autouse=True)
def migrated_webhook_database() -> Iterator[None]:
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection_url"] = _test_url()
    command.upgrade(config, "head")
    yield


@pytest_asyncio.fixture
async def database_engine(migrated_webhook_database: None) -> AsyncIterator[AsyncEngine]:
    engine = create_database_engine(_test_url())
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(database_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    session_maker = create_session_maker(database_engine)
    try:
        async with session_scope(session_maker) as db_session:
            yield db_session
    finally:
        async with database_engine.begin() as connection:
            await connection.execute(
                text("TRUNCATE TABLE jobs, messages, conversations, sessions, employees CASCADE")
            )


@pytest_asyncio.fixture(autouse=True)
async def clean_webhook_database(database_engine: AsyncEngine) -> AsyncIterator[None]:
    async with database_engine.begin() as connection:
        await connection.execute(
            text("TRUNCATE TABLE jobs, messages, conversations, sessions, employees CASCADE")
        )
    yield
    async with database_engine.begin() as connection:
        await connection.execute(
            text("TRUNCATE TABLE jobs, messages, conversations, sessions, employees CASCADE")
        )


@pytest_asyncio.fixture
async def webhook_app(database_engine: AsyncEngine) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.settings = _settings()
    app.state.database_engine = database_engine
    return app


def _signature(body: bytes) -> str:
    digest = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _body(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode()


def _inbound(
    provider_message_id: str,
    wa_id: str,
    body: str,
    *,
    timestamp: str = "1760000000",
) -> dict[str, object]:
    return {
        "id": provider_message_id,
        "from": wa_id,
        "timestamp": timestamp,
        "type": "text",
        "text": {"body": body},
    }


def _payload(
    *messages: dict[str, object], statuses: list[dict[str, object]] | None = None
) -> dict[str, object]:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "synthetic-entry",
                "changes": [
                    {
                        "field": "messages",
                        "value": {"messages": list(messages), "statuses": statuses or []},
                    }
                ],
            }
        ],
    }


async def _post_webhook(client: httpx.AsyncClient, payload: dict[str, object]) -> httpx.Response:
    body = _body(payload)
    return await client.post(
        "/webhooks/whatsapp",
        content=body,
        headers={"X-Hub-Signature-256": _signature(body), "Content-Type": "application/json"},
    )


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


@pytest.mark.asyncio
async def test_verification_challenge_accepts_only_configured_token(webhook_app: FastAPI) -> None:
    async with _client(webhook_app) as client:
        accepted = await client.get(
            "/webhooks/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": VERIFY_TOKEN,
                "hub.challenge": "123",
            },
        )
        rejected = await client.get(
            "/webhooks/whatsapp",
            params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "123"},
        )

    assert accepted.status_code == 200
    assert accepted.text == "123"
    assert rejected.status_code == 403
    assert VERIFY_TOKEN not in rejected.text


@pytest.mark.asyncio
async def test_raw_hmac_rejects_wrong_signature_and_modified_body(webhook_app: FastAPI) -> None:
    payload = _payload(_inbound("wamid.signature", "201", "Hello"))
    body = _body(payload)
    modified_body = _body(_payload(_inbound("wamid.signature", "201", "Changed")))
    async with _client(webhook_app) as client:
        valid = await client.post(
            "/webhooks/whatsapp", content=body, headers={"X-Hub-Signature-256": _signature(body)}
        )
        wrong = await client.post(
            "/webhooks/whatsapp", content=body, headers={"X-Hub-Signature-256": "sha256=wrong"}
        )
        modified = await client.post(
            "/webhooks/whatsapp",
            content=modified_body,
            headers={"X-Hub-Signature-256": _signature(body)},
        )

    assert valid.status_code == 200
    assert wrong.status_code == modified.status_code == 401


@pytest.mark.asyncio
async def test_duplicate_delivery_creates_one_inbound_and_job(
    webhook_app: FastAPI, db_session: AsyncSession
) -> None:
    payload = _payload(_inbound("wamid.duplicate", "202", "Need a website"))
    async with _client(webhook_app) as client:
        assert (await _post_webhook(client, payload)).status_code == 200
        assert (await _post_webhook(client, payload)).status_code == 200

    assert await db_session.scalar(select(func.count()).select_from(Message)) == 1
    assert await db_session.scalar(select(func.count()).select_from(Job)) == 1


@pytest.mark.asyncio
async def test_batch_processes_all_messages_and_entries(
    webhook_app: FastAPI, db_session: AsyncSession
) -> None:
    payload = _payload(
        _inbound("wamid.batch.one", "203", "First"),
        _inbound("wamid.batch.two", "204", "Second"),
    )
    payload["entry"].append(
        {
            "id": "synthetic-entry-two",
            "changes": [
                {
                    "field": "messages",
                    "value": {"messages": [_inbound("wamid.batch.three", "205", "Third")]},
                }
            ],
        }
    )
    async with _client(webhook_app) as client:
        response = await _post_webhook(client, payload)

    assert response.status_code == 200
    assert await db_session.scalar(select(func.count()).select_from(Message)) == 3
    assert await db_session.scalar(select(func.count()).select_from(Job)) == 3


@pytest.mark.asyncio
async def test_batch_with_a_persisted_duplicate_still_saves_the_new_message(
    webhook_app: FastAPI, db_session: AsyncSession
) -> None:
    duplicate = _inbound("wamid.mixed.duplicate", "205", "Original")
    async with _client(webhook_app) as client:
        assert (await _post_webhook(client, _payload(duplicate))).status_code == 200
        response = await _post_webhook(
            client,
            _payload(duplicate, _inbound("wamid.mixed.new", "206", "New message")),
        )

    assert response.status_code == 200
    assert await db_session.scalar(select(func.count()).select_from(Message)) == 2
    assert await db_session.scalar(select(func.count()).select_from(Job)) == 2


@pytest.mark.asyncio
async def test_late_delivery_does_not_regress_latest_customer_timestamp(
    webhook_app: FastAPI, db_session: AsyncSession
) -> None:
    async with _client(webhook_app) as client:
        assert (
            await _post_webhook(
                client,
                _payload(_inbound("wamid.newer", "206", "Newer", timestamp="1760000002")),
            )
        ).status_code == 200
        assert (
            await _post_webhook(
                client,
                _payload(_inbound("wamid.older", "206", "Older", timestamp="1760000001")),
            )
        ).status_code == 200

    conversation = await db_session.scalar(select(Conversation).where(Conversation.wa_id == "206"))
    assert conversation is not None
    assert conversation.latest_inbound_at == datetime.fromtimestamp(1760000002, UTC)


@pytest.mark.asyncio
async def test_oversized_text_is_marked_bounded_and_queued_for_human(
    webhook_app: FastAPI, db_session: AsyncSession
) -> None:
    original_text = "x" * (MAX_INBOUND_TEXT_LENGTH + 20)
    payload = _payload(_inbound("wamid.truncated", "207", original_text))
    raw_body = _body(payload)
    assert len(raw_body) < MAX_WEBHOOK_BODY_BYTES

    async with _client(webhook_app) as client:
        response = await client.post(
            "/webhooks/whatsapp",
            content=raw_body,
            headers={"X-Hub-Signature-256": _signature(raw_body)},
        )

    message = await db_session.scalar(
        select(Message).where(Message.provider_message_id == "wamid.truncated")
    )
    conversation = await db_session.scalar(select(Conversation).where(Conversation.wa_id == "207"))
    assert response.status_code == 200
    assert message is not None and len(message.body or "") == MAX_INBOUND_TEXT_LENGTH
    assert message.body is not None and message.body.endswith(" [truncated]")
    assert conversation is not None and conversation.state == ConversationState.WAITING.value
    assert conversation.version == 1
    job = await db_session.scalar(select(Job).where(Job.conversation_id == conversation.id))
    assert job is not None and job.captured_version == 1


@pytest.mark.asyncio
async def test_db_failure_rolls_back_inbound_and_returns_retryable_error(
    webhook_app: FastAPI, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = webhooks._store_inbound_and_job

    async def fail_after_message(
        session: AsyncSession, conversation: Conversation, event: object
    ) -> None:
        session.add(
            Message(
                conversation_id=conversation.id,
                provider_message_id="wamid.rollback",
                direction="inbound",
                author="customer",
                body="Synthetic rollback",
                status="received",
            )
        )
        await session.flush()
        raise SQLAlchemyError("synthetic database failure")

    monkeypatch.setattr(webhooks, "_store_inbound_and_job", fail_after_message)
    async with _client(webhook_app) as client:
        response = await _post_webhook(
            client, _payload(_inbound("wamid.rollback", "206", "Rollback"))
        )
    monkeypatch.setattr(webhooks, "_store_inbound_and_job", original)

    assert response.status_code == 503
    assert await db_session.scalar(select(func.count()).select_from(Conversation)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Message)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Job)) == 0


@pytest.mark.asyncio
async def test_explicit_handoff_transitions_and_captures_new_version(
    webhook_app: FastAPI, database_engine: AsyncEngine, db_session: AsyncSession
) -> None:
    conversation = Conversation(wa_id="207", latest_inbound_at=datetime.now(UTC), version=4)
    db_session.add(conversation)
    await db_session.commit()

    async with _client(webhook_app) as client:
        response = await _post_webhook(
            client, _payload(_inbound("wamid.handoff", "207", "I need a price"))
        )

    stored = await db_session.scalar(select(Conversation).where(Conversation.id == conversation.id))
    job = await db_session.scalar(select(Job).where(Job.conversation_id == conversation.id))
    ownership = await read_ownership(database_engine, conversation.id)
    await db_session.refresh(conversation)
    assert response.status_code == 200
    assert (
        stored is not None
        and stored.state == ConversationState.WAITING.value
        and stored.version == 5
    )
    assert job is not None and job.captured_version == 5
    assert ownership.version == 5
    assert not automation_result_is_current(ownership, 4, AutomatedAction.REPLY)


@pytest.mark.asyncio
async def test_repeated_handoff_preserves_waiting_and_human_versions(
    webhook_app: FastAPI, db_session: AsyncSession
) -> None:
    waiting = Conversation(
        wa_id="208", latest_inbound_at=datetime.now(UTC), state="waiting", version=3
    )
    human = Conversation(wa_id="209", latest_inbound_at=datetime.now(UTC), state="human", version=6)
    db_session.add_all([waiting, human])
    await db_session.commit()

    async with _client(webhook_app) as client:
        assert (
            await _post_webhook(
                client, _payload(_inbound("wamid.waiting", "208", "I need a price"))
            )
        ).status_code == 200
        assert (
            await _post_webhook(client, _payload(_inbound("wamid.human", "209", "I need a price")))
        ).status_code == 200

    await db_session.refresh(waiting)
    await db_session.refresh(human)
    assert waiting.version == 3 and waiting.state == "waiting"
    assert human.version == 6 and human.state == "human"


@pytest.mark.asyncio
async def test_unsupported_media_records_metadata_and_queues_human(
    webhook_app: FastAPI, db_session: AsyncSession
) -> None:
    media = {
        "id": "wamid.media",
        "from": "210",
        "timestamp": "1760000000",
        "type": "image",
        "image": {"id": "media-id"},
    }
    async with _client(webhook_app) as client:
        response = await _post_webhook(client, _payload(media))

    message = await db_session.scalar(
        select(Message).where(Message.provider_message_id == "wamid.media")
    )
    conversation = await db_session.scalar(select(Conversation).where(Conversation.wa_id == "210"))
    assert response.status_code == 200
    assert message is not None and message.body is None and message.media_type == "image"
    assert conversation is not None and conversation.state == "waiting"
    assert await db_session.scalar(select(func.count()).select_from(Job)) == 1


@pytest.mark.asyncio
async def test_status_callbacks_update_without_jobs_or_regression(
    webhook_app: FastAPI, db_session: AsyncSession
) -> None:
    conversation = Conversation(wa_id="211", latest_inbound_at=datetime.now(UTC))
    db_session.add(conversation)
    await db_session.flush()
    outbound = Message(
        conversation_id=conversation.id,
        provider_message_id="wamid.outbound",
        direction="outbound",
        author="bot",
        body="Synthetic outbound",
        status="sending",
    )
    db_session.add(outbound)
    await db_session.commit()

    def status(value: str) -> dict[str, object]:
        return {"id": "wamid.outbound", "status": value, "timestamp": "1760000001"}

    async with _client(webhook_app) as client:
        assert (await _post_webhook(client, _payload(statuses=[status("sent")]))).status_code == 200
        assert (
            await _post_webhook(client, _payload(statuses=[status("delivered")]))
        ).status_code == 200
        assert (await _post_webhook(client, _payload(statuses=[status("read")]))).status_code == 200
        assert (
            await _post_webhook(client, _payload(statuses=[status("delivered"), status("sent")]))
        ).status_code == 200

    await db_session.refresh(outbound)
    assert outbound.status == MessageStatus.READ.value
    assert await db_session.scalar(select(func.count()).select_from(Job)) == 0


@pytest.mark.asyncio
async def test_malformed_and_oversized_requests_fail_without_persistence(
    webhook_app: FastAPI, db_session: AsyncSession
) -> None:
    malformed = b"{not-json"
    oversized = b"x" * (1_048_576 + 1)
    async with _client(webhook_app) as client:
        malformed_response = await client.post(
            "/webhooks/whatsapp",
            content=malformed,
            headers={"X-Hub-Signature-256": _signature(malformed)},
        )
        oversized_response = await client.post(
            "/webhooks/whatsapp",
            content=oversized,
            headers={"X-Hub-Signature-256": _signature(oversized)},
        )

    assert malformed_response.status_code == 400
    assert oversized_response.status_code == 413
    assert await db_session.scalar(select(func.count()).select_from(Message)) == 0


@pytest.mark.asyncio
async def test_meta_text_client_uses_configured_path_bearer_and_payload() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["path"] = request.url.path
        observed["authorization"] = request.headers["authorization"]
        observed["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"messages": [{"id": "wamid.accepted"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await send_text_message(
            _settings(), recipient_wa_id="212", body="Hello", client=client
        )

    assert result.outcome is MetaSendOutcome.ACCEPTED
    assert result.provider_message_id == "wamid.accepted"
    assert observed == {
        "path": "/v99.0/123456789/messages",
        "authorization": "Bearer synthetic-access-token",
        "payload": {
            "messaging_product": "whatsapp",
            "to": "212",
            "type": "text",
            "text": {"body": "Hello"},
        },
    }


@pytest.mark.asyncio
async def test_meta_client_distinguishes_rejection_and_network_uncertainty() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(400, json={"error": {"code": 131}})
        )
    ) as rejected_client:
        rejected = await send_text_message(
            _settings(), recipient_wa_id="213", body="Hello", client=rejected_client
        )

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout_handler)) as timeout_client:
        uncertain = await send_text_message(
            _settings(), recipient_wa_id="213", body="Hello", client=timeout_client
        )

    assert rejected.outcome is MetaSendOutcome.REJECTED and rejected.error_code == "131"
    assert uncertain.outcome is MetaSendOutcome.UNCERTAIN


@pytest.mark.asyncio
async def test_disabled_whatsapp_refuses_before_mock_transport_is_called() -> None:
    invoked = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal invoked
        invoked = True
        return httpx.Response(200, json={"messages": [{"id": "unexpected"}]})

    disabled_settings = _settings().model_copy(update={"whatsapp_enabled": False})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="disabled"):
            await send_text_message(
                disabled_settings,
                recipient_wa_id="214",
                body="Hello",
                client=client,
            )

    assert invoked is False
