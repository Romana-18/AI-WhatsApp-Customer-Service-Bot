"""Structured contracts shared by business policy and ownership operations."""

import uuid
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.models import ConversationState


class AutomatedAction(StrEnum):
    REPLY = "reply"
    HANDOFF_ACKNOWLEDGEMENT = "handoff_acknowledgement"
    COLLECT = "collect"


class CollectionField(StrEnum):
    CONTACT_NAME = "contact_name"
    BUSINESS_FIELD = "business_field"
    PREFERRED_CONTACT_TIME = "preferred_contact_time"
    PROJECT_DETAILS = "project_details"


class HandoffReason(StrEnum):
    PRICING = "pricing"
    HUMAN_REQUEST = "human_request"
    MEETING = "meeting"
    CONTRACT = "contract"
    INVOICE = "invoice"
    VISIT = "visit"
    MISSING_INFORMATION = "missing_information"
    UNRELIABLE_ANSWER = "unreliable_answer"


class OwnershipSnapshot(BaseModel):
    """Committed ownership data returned by serialized transitions."""

    model_config = ConfigDict(frozen=True)

    conversation_id: int = Field(gt=0)
    state: ConversationState
    version: int = Field(ge=0)
    assigned_employee_id: uuid.UUID | None
    handoff_reason: HandoffReason | None
    collection_stopped: bool
