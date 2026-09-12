"""T04 authentication, cookie, CSRF, and sole-employee security tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.config import Settings
from app.db import create_database_engine, create_session_maker, session_scope
from app.models import Employee, EmployeeSession
from app.routes.auth import router
from app.security import (
    LOGIN_FAILURE_LIMIT,
    SESSION_COOKIE_NAME,
    LoginThrottle,
    authenticate_session,
    create_employee_session,
    hash_password,
    hash_token,
)
from scripts.create_employee import EMPLOYEE_PROVISIONING_ADVISORY_LOCK_KEY, create_sole_employee

ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = "postgresql+psycopg://app_user:synthetic@db:5432/kaalex"
TEST_DATABASE_URL = "postgresql+psycopg://test_user:synthetic@test-db:5432/kaalex_test"
PASSWORD = "synthetic secure password"
ORIGIN = "http://127.0.0.1:8000"


def _settings(*, production: bool = False) -> Settings:
    return Settings(
        database_url=DATABASE_URL,
        test_database_url=TEST_DATABASE_URL,
        app_env="production" if production else "local",
        public_base_url="https://support.example.invalid" if production else ORIGIN,
        huggingface_enabled=False,
        whatsapp_enabled=False,
    )


def _test_url() -> URL:
    settings = Settings()
    if settings.test_database_url is None:
        pytest.fail("TEST_DATABASE_URL is required for T04 PostgreSQL tests")
    test_url = make_url(str(settings.test_database_url))
    if test_url.host != "test-db" or test_url.database != "kaalex_test":
        pytest.fail("T04 tests require isolated Docker test-db/kaalex_test")
    return test_url


@pytest.fixture(scope="session", autouse=True)
def migrated_security_database() -> Iterator[None]:
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection_url"] = _test_url()
    command.upgrade(config, "head")
    yield


@pytest_asyncio.fixture
async def database_engine(migrated_security_database: None) -> AsyncIterator[AsyncEngine]:
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


@pytest_asyncio.fixture
async def employee(db_session: AsyncSession) -> Employee:
    created = Employee(username="sole.employee", password_hash=hash_password(PASSWORD))
    db_session.add(created)
    await db_session.commit()
    return created


@pytest_asyncio.fixture
async def auth_app(database_engine: AsyncEngine) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.settings = _settings()
    app.state.session_maker = create_session_maker(database_engine)
    app.state.login_throttle = LoginThrottle()
    return app


def _client(app: FastAPI, *, ip: str = "127.0.0.1") -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(ip, 12345)),
        base_url=ORIGIN,
    )


async def _login(
    client: httpx.AsyncClient, username: str = "sole.employee", password: str = PASSWORD
):
    return await client.post(
        "/auth/login",
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
        json={"username": username, "password": password},
    )


@pytest.mark.asyncio
async def test_correct_password_returns_identity_and_not_hash(
    auth_app: FastAPI, employee: Employee
) -> None:
    async with _client(auth_app) as client:
        response = await _login(client)

    assert response.status_code == 200
    body = response.json()
    assert body["employee"] == {"id": str(employee.id), "username": employee.username}
    assert body["csrf_token"]
    assert employee.password_hash not in response.text
    assert "token_hash" not in response.text
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]


@pytest.mark.asyncio
async def test_wrong_and_unknown_credentials_share_generic_error(
    auth_app: FastAPI, employee: Employee
) -> None:
    async with _client(auth_app) as client:
        wrong_password = await _login(client, password="wrong synthetic password")
        unknown_user = await _login(client, username="not-an-employee")

    assert wrong_password.status_code == unknown_user.status_code == 401
    assert (
        wrong_password.json()
        == unknown_user.json()
        == {
            "code": "invalid_credentials",
            "detail": "Invalid username or password",
        }
    )


@pytest.mark.asyncio
async def test_provisioning_allows_only_one_employee_and_never_outputs_secrets(
    database_engine: AsyncEngine,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session_maker = create_session_maker(database_engine)
    password = "first employee secret"
    with pytest.raises(ValueError, match="at least 12"):
        await create_sole_employee(session_maker, "too.short", "short")
    created = await create_sole_employee(session_maker, "first.employee", password)

    with pytest.raises(ValueError, match="only one"):
        await create_sole_employee(session_maker, "second.employee", "another secure secret")

    captured_output = capsys.readouterr()
    captured = captured_output.out + captured_output.err + caplog.text
    assert password not in captured
    assert created.password_hash not in captured
    assert created.password_hash != password


def test_provisioning_lock_is_outside_positive_conversation_id_domain() -> None:
    assert -(2**63) <= EMPLOYEE_PROVISIONING_ADVISORY_LOCK_KEY < 0


@pytest.mark.asyncio
async def test_session_authentication_rejects_missing_unknown_expired_and_inactive(
    db_session: AsyncSession, employee: Employee
) -> None:
    token, _, stored_session = await create_employee_session(db_session, employee.id)
    await db_session.commit()

    assert await authenticate_session(db_session, None) is None
    assert await authenticate_session(db_session, "unknown-token") is None
    assert await authenticate_session(db_session, token) is not None
    assert token != stored_session.token_hash
    assert stored_session.token_hash == hash_token(token)

    stored_session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    assert await authenticate_session(db_session, token) is None

    stored_session.expires_at = datetime.now(UTC) + timedelta(hours=1)
    employee.active = False
    await db_session.commit()
    assert await authenticate_session(db_session, token) is None


@pytest.mark.asyncio
async def test_session_endpoint_requires_valid_session_and_is_not_cached(
    auth_app: FastAPI, employee: Employee
) -> None:
    async with _client(auth_app) as client:
        assert (await client.get("/auth/session")).status_code == 401
        login_response = await _login(client)
        session_response = await client.get("/auth/session")

    assert session_response.status_code == 200
    assert session_response.headers["cache-control"] == "no-store"
    assert session_response.json()["employee"]["id"] == str(employee.id)
    assert session_response.json()["csrf_token"] == login_response.json()["csrf_token"]


@pytest.mark.asyncio
async def test_logout_requires_csrf_origin_and_revokes_exact_session(
    auth_app: FastAPI, db_session: AsyncSession, employee: Employee
) -> None:
    async with _client(auth_app) as client:
        login_response = await _login(client)
        csrf_token = login_response.json()["csrf_token"]
        assert (await client.post("/auth/logout", headers={"Origin": ORIGIN})).status_code == 403
        assert (
            await client.post(
                "/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": "wrong-token"}
            )
        ).status_code == 403
        logout_response = await client.post(
            "/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": csrf_token}
        )
        old_cookie = login_response.cookies[SESSION_COOKIE_NAME]
        after_logout = await client.get("/auth/session")

    assert logout_response.status_code == 200
    assert "Max-Age=0" in logout_response.headers["set-cookie"]
    assert after_logout.status_code == 401
    assert await authenticate_session(db_session, old_cookie) is None


@pytest.mark.asyncio
async def test_cross_origin_login_and_mutation_are_rejected(
    auth_app: FastAPI, employee: Employee
) -> None:
    async with _client(auth_app) as client:
        rejected_login = await client.post(
            "/auth/login",
            headers={"Origin": "https://attacker.invalid", "Content-Type": "application/json"},
            json={"username": employee.username, "password": PASSWORD},
        )
        login_response = await _login(client)
        rejected_logout = await client.post(
            "/auth/logout",
            headers={
                "Origin": "https://attacker.invalid",
                "X-CSRF-Token": login_response.json()["csrf_token"],
            },
        )

    assert rejected_login.status_code == rejected_logout.status_code == 403


@pytest.mark.asyncio
async def test_csrf_is_hashed_stable_across_tabs_and_authorizes_logout(
    auth_app: FastAPI, db_session: AsyncSession, employee: Employee
) -> None:
    async with _client(auth_app) as first_tab:
        login_response = await _login(first_tab)
        csrf_token = login_response.json()["csrf_token"]
        raw_cookie = login_response.cookies[SESSION_COOKIE_NAME]
        async with _client(auth_app) as second_tab:
            second_tab.cookies.set(SESSION_COOKIE_NAME, raw_cookie)
            second_session = await second_tab.get("/auth/session")
        stored_before_logout = await db_session.scalar(
            select(EmployeeSession).where(EmployeeSession.employee_id == employee.id)
        )
        logout_response = await first_tab.post(
            "/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": csrf_token}
        )

    assert stored_before_logout is not None
    assert csrf_token not in stored_before_logout.csrf_token_hash
    assert stored_before_logout.csrf_token_hash == hash_token(csrf_token)
    assert second_session.json()["csrf_token"] == csrf_token
    assert logout_response.status_code == 200


def test_cookie_options_protect_production_and_allow_local_http() -> None:
    from app.security import cookie_options

    production = cookie_options(_settings(production=True))
    local = cookie_options(_settings())

    assert production["httponly"] is True
    assert production["secure"] is True
    assert production["samesite"] == "strict"
    assert production["path"] == "/"
    assert local["secure"] is False


@pytest.mark.asyncio
async def test_production_login_sets_a_secure_cookie(auth_app: FastAPI, employee: Employee) -> None:
    auth_app.state.settings = _settings(production=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=auth_app),
        base_url="https://support.example.invalid",
    ) as client:
        response = await client.post(
            "/auth/login",
            headers={
                "Origin": "https://support.example.invalid",
                "Content-Type": "application/json",
            },
            json={"username": employee.username, "password": PASSWORD},
        )

    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]


def test_login_throttle_tracks_direct_ip_resets_and_excludes_forwarded_headers() -> None:
    throttle = LoginThrottle()
    now = datetime.now(UTC)
    for _ in range(LOGIN_FAILURE_LIMIT):
        throttle.record_failure("198.51.100.10", now=now)

    assert throttle.is_limited("198.51.100.10", now=now)
    assert not throttle.is_limited("198.51.100.11", now=now)
    throttle.reset("198.51.100.10")
    assert not throttle.is_limited("198.51.100.10", now=now)


@pytest.mark.asyncio
async def test_login_throttle_ignores_arbitrary_forwarded_for(
    auth_app: FastAPI, employee: Employee
) -> None:
    async with _client(auth_app, ip="203.0.113.50") as client:
        for _ in range(LOGIN_FAILURE_LIMIT):
            response = await client.post(
                "/auth/login",
                headers={
                    "Origin": ORIGIN,
                    "Content-Type": "application/json",
                    "X-Forwarded-For": "1.2.3.4",
                },
                json={"username": employee.username, "password": "incorrect password"},
            )
            assert response.status_code == 401
        throttled = await _login(client)

    assert throttled.status_code == 429


@pytest.mark.asyncio
async def test_successful_login_resets_the_client_failure_bucket(
    auth_app: FastAPI, employee: Employee
) -> None:
    async with _client(auth_app, ip="203.0.113.51") as client:
        for _ in range(LOGIN_FAILURE_LIMIT - 1):
            assert (await _login(client, password="incorrect password")).status_code == 401
        assert (await _login(client)).status_code == 200
        for _ in range(LOGIN_FAILURE_LIMIT):
            assert (await _login(client, password="incorrect password")).status_code == 401
        assert (await _login(client, password="incorrect password")).status_code == 429
