"""T04 employee login, session inspection, and logout routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import Employee
from app.security import (
    SESSION_COOKIE_NAME,
    AuthenticatedSession,
    LoginThrottle,
    authenticate_session,
    cookie_options,
    create_employee_session,
    request_has_expected_origin,
    token_matches_hash,
    verify_password,
)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))


class LoginPayload(BaseModel):
    """The intentionally small JSON login request contract."""

    username: str
    password: str


def _error(status_code: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"code": code, "detail": detail})


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _session_maker(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.session_maker


def _login_throttle(request: Request) -> LoginThrottle:
    return request.app.state.login_throttle


def _client_ip(request: Request) -> str:
    """Use only the direct socket peer, never an untrusted forwarded header."""

    return request.client.host if request.client is not None else "unknown"


async def _request_json_login(request: Request) -> LoginPayload | JSONResponse:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return _error(422, "invalid_content_type", "JSON content is required")
    try:
        payload = await request.json()
        return LoginPayload.model_validate(payload)
    except (ValidationError, ValueError):
        return _error(422, "invalid_login_request", "Username and password are required")


async def _authenticated_request(
    request: Request,
    *,
    require_csrf: bool = False,
) -> tuple[AuthenticatedSession, AsyncSession] | JSONResponse:
    settings = _settings(request)
    if require_csrf and not request_has_expected_origin(request.headers.get("origin"), settings):
        return _error(403, "origin_rejected", "The request origin is not allowed")

    db_session = _session_maker(request)()
    authenticated = await authenticate_session(db_session, request.cookies.get(SESSION_COOKIE_NAME))
    if authenticated is None:
        await db_session.close()
        return _error(401, "authentication_required", "Authentication is required")

    if require_csrf:
        supplied_csrf = request.headers.get("x-csrf-token")
        if supplied_csrf is None or not token_matches_hash(
            supplied_csrf, authenticated.session.csrf_token_hash
        ):
            await db_session.close()
            return _error(403, "csrf_rejected", "A valid CSRF token is required")
    return authenticated, db_session


@router.get("/login")
async def login_page(request: Request):
    """Render the unauthenticated Arabic employee login page."""

    return templates.TemplateResponse(request=request, name="login.html")


@router.post("/auth/login")
async def login(request: Request) -> JSONResponse:
    """Authenticate the sole employee and issue a durable opaque session."""

    settings = _settings(request)
    if not request_has_expected_origin(request.headers.get("origin"), settings):
        return _error(403, "origin_rejected", "The request origin is not allowed")

    parsed_payload = await _request_json_login(request)
    if isinstance(parsed_payload, JSONResponse):
        return parsed_payload

    client_ip = _client_ip(request)
    throttle = _login_throttle(request)
    if throttle.is_limited(client_ip):
        return _error(429, "login_throttled", "Too many login attempts; try again shortly")

    async with _session_maker(request)() as db_session:
        employee = await db_session.scalar(
            select(Employee).where(Employee.username == parsed_payload.username)
        )
        if (
            employee is None
            or not employee.active
            or not verify_password(employee.password_hash, parsed_payload.password)
        ):
            throttle.record_failure(client_ip)
            return _error(401, "invalid_credentials", "Invalid username or password")

        session_token, csrf_token, _ = await create_employee_session(db_session, employee.id)
        await db_session.commit()

    throttle.reset(client_ip)
    response = JSONResponse(
        status_code=200,
        content={
            "employee": {"id": str(employee.id), "username": employee.username},
            "csrf_token": csrf_token,
        },
    )
    response.set_cookie(key=SESSION_COOKIE_NAME, value=session_token, **cookie_options(settings))
    return response


@router.get("/auth/session")
async def current_session(request: Request) -> JSONResponse:
    """Return the current employee identity and unchanged session CSRF contract."""

    authenticated_or_error = await _authenticated_request(request)
    if isinstance(authenticated_or_error, JSONResponse):
        return authenticated_or_error
    authenticated, db_session = authenticated_or_error
    try:
        return JSONResponse(
            content={
                "employee": {
                    "id": str(authenticated.employee.id),
                    "username": authenticated.employee.username,
                },
                "csrf_token": authenticated.csrf_token,
            },
            headers={"Cache-Control": "no-store"},
        )
    finally:
        await db_session.close()


@router.post("/auth/logout")
async def logout(request: Request) -> JSONResponse:
    """Require same-origin CSRF protection, then revoke exactly the current session."""

    authenticated_or_error = await _authenticated_request(request, require_csrf=True)
    if isinstance(authenticated_or_error, JSONResponse):
        return authenticated_or_error
    authenticated, db_session = authenticated_or_error
    try:
        await db_session.delete(authenticated.session)
        await db_session.commit()
    finally:
        await db_session.close()

    response = JSONResponse(content={"status": "logged_out"})
    options = cookie_options(_settings(request))
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path=options["path"],
        secure=options["secure"],
        httponly=options["httponly"],
        samesite=options["samesite"],
    )
    return response
