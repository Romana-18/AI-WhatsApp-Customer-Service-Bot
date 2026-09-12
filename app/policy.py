"""Deterministic backend policy rules that do not duplicate company knowledge."""

import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.models import ConversationState
from app.schemas import AutomatedAction, CollectionField, HandoffReason

CAIRO = ZoneInfo("Africa/Cairo")
HUMAN_OPEN = time(10, 0)
HUMAN_CLOSE = time(22, 0)
CUSTOMER_SERVICE_WINDOW = timedelta(hours=24)

_ALLOWED_AUTOMATED_ACTIONS = {
    ConversationState.BOT: frozenset({AutomatedAction.REPLY}),
    ConversationState.WAITING: frozenset(
        {AutomatedAction.HANDOFF_ACKNOWLEDGEMENT, AutomatedAction.COLLECT}
    ),
    ConversationState.HUMAN: frozenset(),
}

_COLLECTION_ORDER = (
    CollectionField.CONTACT_NAME,
    CollectionField.BUSINESS_FIELD,
    CollectionField.PREFERRED_CONTACT_TIME,
    CollectionField.PROJECT_DETAILS,
)

_EXPLICIT_HANDOFF_PATTERNS: tuple[tuple[HandoffReason, tuple[str, ...]], ...] = (
    (
        HandoffReason.HUMAN_REQUEST,
        (
            r"\b(?:speak|talk)\s+(?:to|with)\s+(?:a\s+)?(?:human(?:\s+agent)?|employee|representative)\b",
            r"\b(?:connect|transfer)\s+me\s+(?:to|with)\s+(?:a\s+)?(?:human(?:\s+agent)?|employee|representative)\b",
            r"\b(?:i\s+)?(?:want|need)\s+(?:a\s+)?(?:human(?:\s+agent)?|employee|representative)\b",
            r"(?:عايز|محتاج|اريد|ممكن)\s+(?:اكلم|اتكلم\s+مع|اتواصل\s+مع)?\s*(?:موظف|حد\s+من\s+الفريق|شخص\s+حقيقي)",
            r"(?:موظف|حد\s+من\s+الفريق)\s+(?:لو\s+سمحت|من\s+فضلك)",
        ),
    ),
    (
        HandoffReason.HUMAN_REQUEST,
        (
            r"^(?:please\s+)?call\s+me(?:\s+(?:today|tomorrow|back|at|on).*)?$",
            r"\b(?:i\s+)?(?:want|need|request)\s+(?:a\s+)?(?:phone\s+)?call\b",
            r"(?:كلمني|اتصل\s+بي|عايز\s+مكالمه|محتاج\s+مكالمه|ممكن\s+حد\s+يكلمني)",
        ),
    ),
    (
        HandoffReason.MEETING,
        (
            r"\b(?:book|schedule|arrange|request|need|want)\s+(?:a\s+)?meeting\b",
            r"(?:عايز|محتاج|اريد|ممكن)\s+(?:احجز|نحدد|نعمل)?\s*(?:اجتماع|مقابله)",
        ),
    ),
    (
        HandoffReason.PRICING,
        (
            r"\b(?:what\s+(?:is|are)|send|share|need|want|tell\s+me)\b.{0,24}\b(?:price|prices|pricing|cost)\b",
            r"^(?:price|prices|pricing|cost)\??$",
            r"(?:عايز|محتاج|اريد|ممكن|كام|ايه).{0,24}(?:سعر|اسعار|تكلفه)",
            r"^(?:السعر|الاسعار|التكلفه)(?:\s+كام)?\??$",
            r"\bhow\s+much(?:\s+(?:does|would|will).{0,20}\bcost\b|.{0,24}\b(?:price|prices|pricing|cost)\b)",
        ),
    ),
    (
        HandoffReason.PRICING,
        (
            r"\b(?:send|provide|prepare|need|want|request)\b.{0,24}\b(?:detailed\s+)?(?:quote|quotation)\b",
            r"(?:عايز|محتاج|اريد|ممكن|ابعت|جهز).{0,24}عرض\s+سعر(?:\s+تفصيلي)?",
        ),
    ),
    (
        HandoffReason.CONTRACT,
        (
            r"\b(?:send|need|want|review|discuss|sign)\b.{0,20}\bcontract\b",
            r"(?:عايز|محتاج|اريد|ممكن|ابعت|نراجع|نوقع).{0,20}(?:عقد|العقد)",
        ),
    ),
    (
        HandoffReason.INVOICE,
        (
            r"\b(?:send|request|issue)\b.{0,20}\b(?:an?\s+)?invoice(?:\s+please)?[?.!]*$",
            r"^(?:i\s+)?(?:need|want)\s+(?:an?\s+)?invoice(?:\s+please)?[?.!]*$",
            r"(?:عايز|محتاج|اريد|ممكن|ابعت|اصدر).{0,20}(?:فاتوره|الفاتوره)(?:\s+لو\s+سمحت)?$",
        ),
    ),
    (
        HandoffReason.VISIT,
        (
            r"\b(?:want|need|arrange|schedule|book)\b.{0,24}\bvisit\b.{0,20}\b(?:company|office)\b",
            r"(?:عايز|محتاج|اريد|ممكن|احجز|نحدد).{0,24}(?:ازور\s+|زياره\s+)(?:الشركه|المكتب)",
        ),
    ),
)

_COLLECTION_REFUSAL_PATTERNS = (
    re.compile(r"\b(?:i\s+)?(?:do\s+not|don't)\s+want\s+to\s+(?:share|answer)\b"),
    re.compile(r"\b(?:i\s+)?prefer\s+not\s+to\s+(?:share|answer|say)\b"),
    re.compile(r"(?:مش|لا)\s+(?:حابب|عايز)\s+(?:اقول|اجاوب|اشارك)"),
    re.compile(r"افضل\s+عدم\s+(?:الاجابه|المشاركه)"),
)


class PolicyViolation(ValueError):
    """Raised when backend state forbids a requested automated action."""


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _normalize_text(value: str) -> str:
    normalized = value.casefold().strip()
    normalized = re.sub(r"[\u064b-\u065f\u0670\u0640]", "", normalized)
    normalized = normalized.translate(str.maketrans("أإآةى", "اااهي"))
    return re.sub(r"\s+", " ", normalized)


def is_human_team_open(at: datetime) -> bool:
    """Return whether an aware instant falls within Cairo human working hours."""

    _require_aware(at, "at")
    local = at.astimezone(CAIRO)
    return local.weekday() != 4 and HUMAN_OPEN <= local.time().replace(tzinfo=None) < HUMAN_CLOSE


def is_within_customer_service_window(latest_inbound_at: datetime, now: datetime) -> bool:
    """Apply the strict 24-hour free-form WhatsApp window boundary."""

    _require_aware(latest_inbound_at, "latest_inbound_at")
    _require_aware(now, "now")
    return now.astimezone(UTC) < latest_inbound_at.astimezone(UTC) + CUSTOMER_SERVICE_WINDOW


def automated_action_allowed(
    state: ConversationState | str,
    action: AutomatedAction | str,
) -> bool:
    current_state = ConversationState(state)
    requested_action = AutomatedAction(action)
    return requested_action in _ALLOWED_AUTOMATED_ACTIONS[current_state]


def require_automated_action(
    state: ConversationState | str,
    action: AutomatedAction | str,
) -> None:
    if not automated_action_allowed(state, action):
        raise PolicyViolation(f"automated action {action!s} is not allowed in state {state!s}")


def explicit_handoff_reason(customer_text: str) -> HandoffReason | None:
    """Recognize only direct, high-confidence requests covered by the locked contract."""

    normalized = _normalize_text(customer_text)
    if not normalized:
        return None
    for reason, patterns in _EXPLICIT_HANDOFF_PATTERNS:
        if any(re.search(pattern, normalized) for pattern in patterns):
            return reason
    return None


def collection_refused(customer_text: str) -> bool:
    normalized = _normalize_text(customer_text)
    return any(pattern.search(normalized) for pattern in _COLLECTION_REFUSAL_PATTERNS)


def next_collection_field(
    values: Mapping[str, str | None],
    asked_fields: Iterable[str],
    *,
    collection_stopped: bool,
    known_sender_phone: str,
) -> CollectionField | None:
    """Choose at most one unasked optional field; the known sender phone is never requested."""

    if not known_sender_phone.strip():
        raise ValueError("known_sender_phone must be present")
    if collection_stopped:
        return None

    asked = {CollectionField(field) for field in asked_fields}
    for field in _COLLECTION_ORDER:
        value = values.get(field.value)
        if field not in asked and (value is None or not value.strip()):
            return field
    return None


def record_collection_question(
    asked_fields: Iterable[str], field: CollectionField | str
) -> list[str]:
    """Record a permitted question once while retaining deterministic field order."""

    requested = CollectionField(field)
    asked = [CollectionField(value) for value in asked_fields]
    if requested not in asked:
        asked.append(requested)
    return [value.value for value in asked]
