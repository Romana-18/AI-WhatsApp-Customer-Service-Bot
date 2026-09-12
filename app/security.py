"""Focused password, session, CSRF, cookie, origin, and login-throttle helpers."""

from __future__ import annotations

import hashlib
import secrets
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import AppEnvironment, Settings
from app.models import Employee, EmployeeSession

MINIMUM_PASSWORD_LENGTH = 12
SESSION_LIFETIME = timedelta(hours=12)
SESSION_COOKIE_NAME = "kaalex_session"
LOGIN_FAILURE_WINDOW = timedelta(minutes=1)
LOGIN_FAILURE_LIMIT = 5

_password_hasher = PasswordHasher()


@dataclass(frozen=True)
class AuthenticatedSession:
    """The employee and server-side session authenticated from an opaque cookie."""

    employee: Employee
    session: EmployeeSession
    csrf_token: str


def validate_provisioning_password(password: str) -> None:
    """Reject passwords below the sole-employee provisioning minimum."""

    if len(password) < MINIMUM_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MINIMUM_PASSWORD_LENGTH} characters long")


def hash_password(password: str) -> str:
    """Hash a provisioned password with argon2-cffi's Argon2id default."""

    validate_provisioning_password(password)
    return _password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Check credentials without exposing why verification failed."""

    try:
        return _password_hasher.verify(password_hash, password)
    except (InvalidHashError, VerificationError):
        return False


def generate_session_token() -> str:
    """Create an opaque token containing 256 bits of cryptographic randomness."""

    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Create the SHA-256 database representation of an opaque token."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def csrf_for_session_token(session_token: str) -> str:
    """Derive the stable per-session CSRF value without storing it in plaintext."""

    return hashlib.sha256(f"kaalex-csrf:{session_token}".encode()).hexdigest()


def token_matches_hash(token: str, expected_hash: str) -> bool:
    """Compare a token's database hash in constant time."""

    return secrets.compare_digest(hash_token(token), expected_hash)


async def create_employee_session(
    db_session: AsyncSession,
    employee_id: UUID,
    *,
    now: datetime | None = None,
) -> tuple[str, str, EmployeeSession]:
    """Add one durable session and return its browser-only token and CSRF value."""

    issued_at = now or datetime.now(UTC)
    session_token = generate_session_token()
    csrf_token = csrf_for_session_token(session_token)
    employee_session = EmployeeSession(
        employee_id=employee_id,
        token_hash=hash_token(session_token),
        csrf_token_hash=hash_token(csrf_token),
        expires_at=issued_at + SESSION_LIFETIME,
    )
    db_session.add(employee_session)
    await db_session.flush()
    return session_token, csrf_token, employee_session


async def authenticate_session(
    db_session: AsyncSession,
    session_token: str | None,
    *,
    now: datetime | None = None,
) -> AuthenticatedSession | None:
    """Resolve one active, unexpired employee session from its opaque cookie value."""

    if not session_token:
        return None

    result = await db_session.execute(
        select(EmployeeSession, Employee)
        .join(Employee, Employee.id == EmployeeSession.employee_id)
        .where(EmployeeSession.token_hash == hash_token(session_token))
    )
    row = result.one_or_none()
    if row is None:
        return None

    employee_session, employee = row
    current_time = now or datetime.now(UTC)
    if employee_session.expires_at <= current_time or not employee.active:
        return None

    csrf_token = csrf_for_session_token(session_token)
    if not token_matches_hash(csrf_token, employee_session.csrf_token_hash):
        return None
    return AuthenticatedSession(employee=employee, session=employee_session, csrf_token=csrf_token)


def cookie_options(settings: Settings) -> dict[str, object]:
    """Return the session-cookie attributes aligned to the absolute session lifetime."""

    return {
        "httponly": True,
        "secure": settings.app_env is AppEnvironment.PRODUCTION,
        "samesite": "strict",
        "path": "/",
        "max_age": int(SESSION_LIFETIME.total_seconds()),
    }


def request_has_expected_origin(origin: str | None, settings: Settings) -> bool:
    """Require the exact configured browser origin for unsafe requests."""

    if origin is None:
        return False
    public_url = urlsplit(str(settings.public_base_url))
    expected_origin = f"{public_url.scheme}://{public_url.netloc}"
    return secrets.compare_digest(origin.rstrip("/"), expected_origin.rstrip("/"))


class LoginThrottle:
    """Small per-process failed-login limiter; process restarts intentionally reset it."""

    def __init__(self) -> None:
        self._failures: dict[str, deque[datetime]] = defaultdict(deque)

    def is_limited(self, client_ip: str, *, now: datetime | None = None) -> bool:
        """Return whether this direct client IP has exhausted its minute-long allowance."""

        failures = self._active_failures(client_ip, now=now)
        return len(failures) >= LOGIN_FAILURE_LIMIT

    def record_failure(self, client_ip: str, *, now: datetime | None = None) -> None:
        """Record a generic failed login for the direct socket client IP."""

        self._active_failures(client_ip, now=now).append(now or datetime.now(UTC))

    def reset(self, client_ip: str) -> None:
        """Clear this address's failures after a successful login."""

        self._failures.pop(client_ip, None)

    def _active_failures(self, client_ip: str, *, now: datetime | None = None) -> deque[datetime]:
        current_time = now or datetime.now(UTC)
        failures = self._failures[client_ip]
        cutoff = current_time - LOGIN_FAILURE_WINDOW
        while failures and failures[0] <= cutoff:
            failures.popleft()
        return failures
