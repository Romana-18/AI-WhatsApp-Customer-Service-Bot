"""T03 deterministic business-policy tests."""

from datetime import UTC, datetime, timedelta

import pytest

from app.models import ConversationState
from app.policy import (
    CAIRO,
    PolicyViolation,
    automated_action_allowed,
    collection_refused,
    explicit_handoff_reason,
    is_human_team_open,
    is_within_customer_service_window,
    next_collection_field,
    record_collection_question,
    require_automated_action,
)
from app.schemas import AutomatedAction, CollectionField, HandoffReason


def test_cairo_working_hour_boundaries() -> None:
    assert is_human_team_open(datetime(2026, 1, 3, 10, 0, tzinfo=CAIRO))
    assert is_human_team_open(datetime(2026, 1, 8, 21, 59, tzinfo=CAIRO))
    assert not is_human_team_open(datetime(2026, 1, 8, 22, 0, tzinfo=CAIRO))
    assert not is_human_team_open(datetime(2026, 1, 9, 12, 0, tzinfo=CAIRO))


def test_cairo_hours_use_aware_datetimes_across_dst_transitions() -> None:
    before_dst = datetime(2026, 4, 18, 10, 0, tzinfo=CAIRO)
    after_dst = datetime(2026, 4, 25, 10, 0, tzinfo=CAIRO)
    before_standard_time = datetime(2026, 10, 24, 10, 0, tzinfo=CAIRO)
    after_standard_time = datetime(2026, 10, 31, 10, 0, tzinfo=CAIRO)

    assert before_dst.utcoffset() != after_dst.utcoffset()
    assert before_standard_time.utcoffset() != after_standard_time.utcoffset()
    assert all(
        is_human_team_open(value)
        for value in (before_dst, after_dst, before_standard_time, after_standard_time)
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        is_human_team_open(datetime(2026, 1, 3, 10, 0))


def test_customer_service_window_is_strict_and_timezone_aware() -> None:
    latest_inbound = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    assert is_within_customer_service_window(
        latest_inbound, latest_inbound + timedelta(hours=23, minutes=59)
    )
    assert not is_within_customer_service_window(
        latest_inbound, latest_inbound + timedelta(hours=24)
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        is_within_customer_service_window(latest_inbound.replace(tzinfo=None), latest_inbound)


def test_customer_service_window_uses_elapsed_time_across_cairo_dst() -> None:
    latest_inbound = datetime(2026, 4, 23, 12, 0, tzinfo=CAIRO)
    before_elapsed_expiry = datetime(2026, 4, 24, 12, 30, tzinfo=CAIRO)
    at_elapsed_expiry = datetime(2026, 4, 24, 13, 0, tzinfo=CAIRO)

    assert before_elapsed_expiry.astimezone(UTC) - latest_inbound.astimezone(UTC) == timedelta(
        hours=23, minutes=30
    )
    assert is_within_customer_service_window(latest_inbound, before_elapsed_expiry)
    assert not is_within_customer_service_window(latest_inbound, at_elapsed_expiry)


def test_state_action_compatibility_is_backend_enforced() -> None:
    assert automated_action_allowed(ConversationState.BOT, AutomatedAction.REPLY)
    assert not automated_action_allowed(ConversationState.WAITING, AutomatedAction.REPLY)
    assert automated_action_allowed(
        ConversationState.WAITING, AutomatedAction.HANDOFF_ACKNOWLEDGEMENT
    )
    assert automated_action_allowed(ConversationState.WAITING, AutomatedAction.COLLECT)

    for action in AutomatedAction:
        assert not automated_action_allowed(ConversationState.HUMAN, action)
        with pytest.raises(PolicyViolation):
            require_automated_action(ConversationState.HUMAN, action)


@pytest.mark.parametrize(
    ("customer_text", "expected_reason"),
    [
        ("Please connect me to a human", HandoffReason.HUMAN_REQUEST),
        ("محتاج أكلم موظف", HandoffReason.HUMAN_REQUEST),
        ("Please call me tomorrow", HandoffReason.HUMAN_REQUEST),
        ("عايز نحدد اجتماع", HandoffReason.MEETING),
        ("What are your prices?", HandoffReason.PRICING),
        ("ممكن عرض سعر تفصيلي؟", HandoffReason.PRICING),
        ("I need to discuss the contract", HandoffReason.CONTRACT),
        ("Please send me an invoice", HandoffReason.INVOICE),
        ("عايز أزور الشركة", HandoffReason.VISIT),
    ],
)
def test_explicit_high_confidence_handoff_is_narrowly_detected(
    customer_text: str, expected_reason: HandoffReason
) -> None:
    assert explicit_handoff_reason(customer_text) is expected_reason


@pytest.mark.parametrize(
    "customer_text",
    [
        "We are designing a human-centered interface",
        "Let's call this product Horizon",
        "Meeting deadlines is important",
        "The application needs an invoice screen",
        "Tell me about your work process",
        "You can call me Ahmed.",
        "How much experience does your team have?",
        "I need an AI agent for WhatsApp.",
        "I need an invoice automation screen.",
    ],
)
def test_ambiguous_wording_is_not_claimed_as_deterministic_intent(
    customer_text: str,
) -> None:
    assert explicit_handoff_reason(customer_text) is None


def test_collection_refusal_is_deliberately_narrow() -> None:
    assert collection_refused("I prefer not to share that")
    assert collection_refused("مش عايز أشارك البيانات")
    assert not collection_refused("No, my preferred time is Sunday")


def test_collection_asks_only_one_missing_unasked_field_and_never_phone() -> None:
    values = {
        "contact_name": None,
        "business_field": None,
        "preferred_contact_time": None,
        "project_details": None,
        "alternative_phone": None,
    }
    asked: list[str] = []

    for expected in CollectionField:
        selected = next_collection_field(
            values,
            asked,
            collection_stopped=False,
            known_sender_phone="synthetic-known-sender",
        )
        assert selected is expected
        asked = record_collection_question(asked, selected)

    assert (
        next_collection_field(
            values,
            asked,
            collection_stopped=False,
            known_sender_phone="synthetic-known-sender",
        )
        is None
    )
    assert "alternative_phone" not in asked


def test_collection_stops_after_refusal_and_skips_known_values() -> None:
    values = {
        "contact_name": "Synthetic Customer",
        "business_field": None,
        "preferred_contact_time": None,
        "project_details": None,
    }
    assert (
        next_collection_field(
            values,
            [],
            collection_stopped=False,
            known_sender_phone="synthetic-known-sender",
        )
        is CollectionField.BUSINESS_FIELD
    )
    assert (
        next_collection_field(
            values,
            [],
            collection_stopped=True,
            known_sender_phone="synthetic-known-sender",
        )
        is None
    )
