"""Typed application configuration loaded from environment variables."""

from enum import StrEnum
from typing import Self

from pydantic import AnyHttpUrl, Field, PostgresDsn, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

WORKER_POLL_SECONDS = 1.0
UI_POLL_SECONDS = 3.0
AI_TIMEOUT_SECONDS = 45.0
AI_CONNECT_TIMEOUT_SECONDS = 5.0
WHATSAPP_TIMEOUT_SECONDS = 15.0
MAX_INBOUND_TEXT_LENGTH = 8_000
MAX_OUTBOUND_TEXT_LENGTH = 3_000
MAX_WEBHOOK_BODY_BYTES = 1_048_576


class AppEnvironment(StrEnum):
    """Supported application environments."""

    LOCAL = "local"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Environment-backed settings with integration-specific validation."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        case_sensitive=True,
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
        populate_by_name=True,
    )

    database_url: PostgresDsn = Field(validation_alias="DATABASE_URL")
    test_database_url: PostgresDsn | None = Field(
        default=None,
        validation_alias="TEST_DATABASE_URL",
    )
    app_env: AppEnvironment = Field(validation_alias="APP_ENV")
    public_base_url: AnyHttpUrl = Field(validation_alias="PUBLIC_BASE_URL")

    huggingface_enabled: bool = Field(validation_alias="HUGGINGFACE_ENABLED")
    hf_token: SecretStr | None = Field(default=None, validation_alias="HF_TOKEN")
    huggingface_model: str | None = Field(
        default=None,
        validation_alias="HUGGINGFACE_MODEL",
    )

    whatsapp_enabled: bool = Field(validation_alias="WHATSAPP_ENABLED")
    whatsapp_access_token: SecretStr | None = Field(
        default=None,
        validation_alias="WHATSAPP_ACCESS_TOKEN",
    )
    whatsapp_phone_number_id: str | None = Field(
        default=None,
        validation_alias="WHATSAPP_PHONE_NUMBER_ID",
    )
    whatsapp_app_secret: SecretStr | None = Field(
        default=None,
        validation_alias="WHATSAPP_APP_SECRET",
    )
    whatsapp_verify_token: SecretStr | None = Field(
        default=None,
        validation_alias="WHATSAPP_VERIFY_TOKEN",
    )
    whatsapp_graph_version: str | None = Field(
        default=None,
        validation_alias="WHATSAPP_GRAPH_VERSION",
    )

    @model_validator(mode="after")
    def validate_configuration(self) -> Self:
        """Enforce transport, isolation, and enabled-integration requirements."""

        if self.app_env is AppEnvironment.PRODUCTION and self.public_base_url.scheme != "https":
            raise ValueError("APP_ENV=production requires an HTTPS PUBLIC_BASE_URL")

        if self.test_database_url is not None and self.test_database_url == self.database_url:
            raise ValueError("TEST_DATABASE_URL must differ from DATABASE_URL")

        if self.huggingface_enabled:
            missing_huggingface = []
            if _secret_is_blank(self.hf_token):
                missing_huggingface.append("HF_TOKEN")
            if _string_is_blank(self.huggingface_model):
                missing_huggingface.append("HUGGINGFACE_MODEL")
            if missing_huggingface:
                missing = ", ".join(missing_huggingface)
                raise ValueError(f"HUGGINGFACE_ENABLED=true requires non-empty {missing}")

        if self.whatsapp_enabled:
            required_whatsapp = {
                "WHATSAPP_ACCESS_TOKEN": self.whatsapp_access_token,
                "WHATSAPP_PHONE_NUMBER_ID": self.whatsapp_phone_number_id,
                "WHATSAPP_APP_SECRET": self.whatsapp_app_secret,
                "WHATSAPP_VERIFY_TOKEN": self.whatsapp_verify_token,
                "WHATSAPP_GRAPH_VERSION": self.whatsapp_graph_version,
            }
            missing_whatsapp = [
                name for name, value in required_whatsapp.items() if _value_is_blank(value)
            ]
            if missing_whatsapp:
                missing = ", ".join(missing_whatsapp)
                raise ValueError(f"WHATSAPP_ENABLED=true requires non-empty {missing}")

        return self


def _secret_is_blank(value: SecretStr | None) -> bool:
    return value is None or not value.get_secret_value().strip()


def _string_is_blank(value: str | None) -> bool:
    return value is None or not value.strip()


def _value_is_blank(value: SecretStr | str | None) -> bool:
    if isinstance(value, SecretStr):
        return _secret_is_blank(value)
    return _string_is_blank(value)
