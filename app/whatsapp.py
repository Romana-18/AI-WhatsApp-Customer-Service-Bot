"""Focused Meta WhatsApp Cloud API protocol parsing and text transport."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import httpx

from app.config import MAX_INBOUND_TEXT_LENGTH, WHATSAPP_TIMEOUT_SECONDS, Settings


class WebhookPayloadError(ValueError):
    """Raised when a signed webhook body is not a usable Meta payload."""


class MetaSendOutcome(StrEnum):
    """Observed provider outcome, without inventing certainty after a network failure."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class InboundMessageEvent:
    """A normalized customer text or unsupported-media inbound event."""

    provider_message_id: str
    wa_id: str
    occurred_at: datetime
    body: str | None
    media_type: str | None
    was_truncated: bool


@dataclass(frozen=True)
class StatusEvent:
    """A normalized provider delivery status for an existing outbound message."""

    provider_message_id: str
    status: str
    occurred_at: datetime | None
    error_code: str | None


@dataclass(frozen=True)
class MetaSendResult:
    """The low-level provider observation reserved for T07's final send gate."""

    outcome: MetaSendOutcome
    provider_message_id: str | None = None
    status_code: int | None = None
    error_code: str | None = None


def verify_webhook_signature(body: bytes, signature: str | None, app_secret: str) -> bool:
    """Compare Meta's SHA-256 HMAC over the exact received bytes in constant time."""

    if signature is None or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def normalize_webhook_payload(
    payload: object,
) -> tuple[list[InboundMessageEvent], list[StatusEvent]]:
    """Normalize every supported customer message and status in a complete Meta batch."""

    if not isinstance(payload, dict) or not isinstance(payload.get("entry"), list):
        raise WebhookPayloadError("invalid webhook payload")

    inbound_events: list[InboundMessageEvent] = []
    status_events: list[StatusEvent] = []
    for entry in payload["entry"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("changes"), list):
            continue
        for change in entry["changes"]:
            if not isinstance(change, dict) or change.get("field") != "messages":
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            inbound_events.extend(_normalize_messages(value.get("messages")))
            status_events.extend(_normalize_statuses(value.get("statuses")))
    return inbound_events, status_events


def _normalize_messages(messages: object) -> list[InboundMessageEvent]:
    if not isinstance(messages, list):
        return []

    normalized: list[InboundMessageEvent] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        provider_message_id = message.get("id")
        wa_id = message.get("from")
        message_type = message.get("type")
        occurred_at = _meta_timestamp(message.get("timestamp"))
        if not all(
            isinstance(value, str) and value for value in (provider_message_id, wa_id, message_type)
        ):
            continue
        if occurred_at is None:
            continue
        if message_type == "text":
            text_value = message.get("text")
            body = text_value.get("body") if isinstance(text_value, dict) else None
            if not isinstance(body, str) or not body:
                continue
            bounded_body, was_truncated = _bounded_inbound_text(body)
            normalized.append(
                InboundMessageEvent(
                    provider_message_id=provider_message_id,
                    wa_id=wa_id,
                    occurred_at=occurred_at,
                    body=bounded_body,
                    media_type=None,
                    was_truncated=was_truncated,
                )
            )
        else:
            normalized.append(
                InboundMessageEvent(
                    provider_message_id=provider_message_id,
                    wa_id=wa_id,
                    occurred_at=occurred_at,
                    body=None,
                    media_type=message_type,
                    was_truncated=False,
                )
            )
    return normalized


def _normalize_statuses(statuses: object) -> list[StatusEvent]:
    if not isinstance(statuses, list):
        return []

    normalized: list[StatusEvent] = []
    for status in statuses:
        if not isinstance(status, dict):
            continue
        provider_message_id = status.get("id")
        raw_status = status.get("status")
        if not isinstance(provider_message_id, str) or not provider_message_id:
            continue
        if raw_status == "sent":
            raw_status = "accepted"
        if raw_status not in {"accepted", "delivered", "read", "failed"}:
            continue
        error_code = _status_error_code(status.get("errors"))
        normalized.append(
            StatusEvent(
                provider_message_id=provider_message_id,
                status=raw_status,
                occurred_at=_meta_timestamp(status.get("timestamp")),
                error_code=error_code,
            )
        )
    return normalized


def _status_error_code(errors: object) -> str | None:
    if not isinstance(errors, list) or not errors or not isinstance(errors[0], dict):
        return None
    code = errors[0].get("code")
    return str(code) if isinstance(code, (str, int)) else None


def _meta_timestamp(value: object) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(str(value)), UTC)
    except (TypeError, ValueError, OverflowError):
        return None


def _bounded_inbound_text(body: str) -> tuple[str, bool]:
    if len(body) <= MAX_INBOUND_TEXT_LENGTH:
        return body, False
    marker = " [truncated]"
    return body[: MAX_INBOUND_TEXT_LENGTH - len(marker)] + marker, True


async def send_text_message(
    settings: Settings,
    *,
    recipient_wa_id: str,
    body: str,
    client: httpx.AsyncClient | None = None,
) -> MetaSendResult:
    """Submit one text payload to Meta without retrying or deciding final-send policy."""

    if not settings.whatsapp_enabled:
        raise ValueError("WhatsApp transport is disabled")
    if (
        settings.whatsapp_access_token is None
        or settings.whatsapp_phone_number_id is None
        or settings.whatsapp_graph_version is None
    ):
        raise ValueError("WhatsApp transport requires complete enabled configuration")

    endpoint = (
        f"https://graph.facebook.com/{settings.whatsapp_graph_version}/"
        f"{settings.whatsapp_phone_number_id}/messages"
    )
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_access_token.get_secret_value()}",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_wa_id,
        "type": "text",
        "text": {"body": body},
    }

    owns_client = client is None
    active_client = client or httpx.AsyncClient(timeout=WHATSAPP_TIMEOUT_SECONDS)
    try:
        response = await active_client.post(endpoint, headers=headers, json=payload)
    except (httpx.TimeoutException, httpx.RequestError):
        return MetaSendResult(outcome=MetaSendOutcome.UNCERTAIN)
    finally:
        if owns_client:
            await active_client.aclose()

    if response.is_success:
        provider_message_id = _accepted_message_id(response)
        if provider_message_id is not None:
            return MetaSendResult(
                outcome=MetaSendOutcome.ACCEPTED,
                provider_message_id=provider_message_id,
                status_code=response.status_code,
            )
        return MetaSendResult(outcome=MetaSendOutcome.UNCERTAIN, status_code=response.status_code)
    return MetaSendResult(
        outcome=MetaSendOutcome.REJECTED,
        status_code=response.status_code,
        error_code=_response_error_code(response),
    )


def _accepted_message_id(response: httpx.Response) -> str | None:
    try:
        payload: Any = response.json()
    except json.JSONDecodeError:
        return None
    messages = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(messages, list) or not messages or not isinstance(messages[0], dict):
        return None
    message_id = messages[0].get("id")
    return message_id if isinstance(message_id, str) and message_id else None


def _response_error_code(response: httpx.Response) -> str | None:
    try:
        payload: Any = response.json()
    except json.JSONDecodeError:
        return None
    error = payload.get("error") if isinstance(payload, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    return str(code) if isinstance(code, (str, int)) else None
