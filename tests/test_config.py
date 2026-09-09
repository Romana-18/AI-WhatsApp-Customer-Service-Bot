"""T01 configuration and test-isolation acceptance tests."""

from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.config import AppEnvironment, Settings

DATABASE_URL = "postgresql+psycopg://app_user:synthetic@db:5432/kaalex"
TEST_DATABASE_URL = "postgresql+psycopg://test_user:synthetic@test-db:5432/kaalex_test"


def settings_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "database_url": DATABASE_URL,
        "test_database_url": None,
        "app_env": "local",
        "public_base_url": "http://127.0.0.1:8000",
        "huggingface_enabled": False,
        "hf_token": None,
        "huggingface_model": None,
        "whatsapp_enabled": False,
        "whatsapp_access_token": None,
        "whatsapp_phone_number_id": None,
        "whatsapp_app_secret": None,
        "whatsapp_verify_token": None,
        "whatsapp_graph_version": None,
    }
    values.update(overrides)
    return values


def test_disabled_integrations_need_no_fake_credentials() -> None:
    settings = Settings(**settings_values())

    assert settings.huggingface_enabled is False
    assert settings.hf_token is None
    assert settings.whatsapp_enabled is False
    assert settings.whatsapp_access_token is None


@pytest.mark.parametrize(
    ("overrides", "missing_name"),
    [
        ({"huggingface_enabled": True}, "HF_TOKEN"),
        (
            {"huggingface_enabled": True, "hf_token": "synthetic-token"},
            "HUGGINGFACE_MODEL",
        ),
    ],
)
def test_enabled_huggingface_requires_actionable_configuration(
    overrides: dict[str, object],
    missing_name: str,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(**settings_values(**overrides))

    error = str(exc_info.value)
    assert missing_name in error
    assert "synthetic-token" not in error


def test_enabled_huggingface_accepts_the_configured_candidate() -> None:
    settings = Settings(
        **settings_values(
            huggingface_enabled=True,
            hf_token="synthetic-token",
            huggingface_model="Qwen/Qwen2.5-7B-Instruct:cheapest",
        )
    )

    assert settings.hf_token is not None
    assert settings.hf_token.get_secret_value() == "synthetic-token"
    assert settings.huggingface_model == "Qwen/Qwen2.5-7B-Instruct:cheapest"
    assert "synthetic-token" not in repr(settings)


def test_enabled_whatsapp_requires_every_meta_setting_without_leaking_secrets() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            **settings_values(
                whatsapp_enabled=True,
                whatsapp_access_token="synthetic-access-token",
                whatsapp_app_secret="synthetic-app-secret",
            )
        )

    error = str(exc_info.value)
    assert "WHATSAPP_PHONE_NUMBER_ID" in error
    assert "WHATSAPP_VERIFY_TOKEN" in error
    assert "WHATSAPP_GRAPH_VERSION" in error
    assert "synthetic-access-token" not in error
    assert "synthetic-app-secret" not in error


def test_production_rejects_http_public_origin() -> None:
    with pytest.raises(ValidationError, match="HTTPS PUBLIC_BASE_URL"):
        Settings(
            **settings_values(
                app_env=AppEnvironment.PRODUCTION,
                public_base_url="http://example.invalid",
            )
        )


def test_production_accepts_https_public_origin() -> None:
    settings = Settings(
        **settings_values(
            app_env=AppEnvironment.PRODUCTION,
            public_base_url="https://support.example.invalid",
        )
    )

    assert settings.public_base_url.scheme == "https"


def test_local_loopback_http_origin_is_accepted() -> None:
    settings = Settings(**settings_values(public_base_url="http://localhost:8000"))

    assert settings.app_env is AppEnvironment.LOCAL
    assert settings.public_base_url.scheme == "http"


def test_test_database_must_differ_from_application_database() -> None:
    with pytest.raises(ValidationError, match="TEST_DATABASE_URL must differ"):
        Settings(**settings_values(test_database_url=DATABASE_URL))


def test_distinct_test_database_is_accepted() -> None:
    settings = Settings(**settings_values(test_database_url=TEST_DATABASE_URL))

    assert settings.test_database_url is not None
    assert settings.test_database_url != settings.database_url


def test_default_http_transport_is_blocked() -> None:
    with httpx.Client() as client:
        with pytest.raises(RuntimeError, match="Outbound HTTP is disabled"):
            client.get("https://example.invalid")


def test_httpx_mock_transport_remains_available() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"synthetic": True}))

    with httpx.Client(transport=transport) as client:
        response = client.get("https://example.invalid")

    assert response.json() == {"synthetic": True}


def test_example_environment_uses_only_the_selected_ai_provider_names() -> None:
    example = Path(".env.example").read_text(encoding="utf-8")

    assert "HF_TOKEN=" in example
    assert "HUGGINGFACE_MODEL=Qwen/Qwen2.5-7B-Instruct:cheapest" in example
    assert "OPENROUTER" not in example.upper()
