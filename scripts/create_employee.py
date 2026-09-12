"""Interactive local provisioning for the single KAALEX employee account."""

from __future__ import annotations

import asyncio
import getpass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db import create_database_engine, create_session_maker, session_scope
from app.models import Employee
from app.security import hash_password

EMPLOYEE_PROVISIONING_ADVISORY_LOCK_KEY = -7_240_204_000_000


async def create_sole_employee(
    session_maker: async_sessionmaker[AsyncSession],
    username: str,
    password: str,
) -> Employee:
    """Persist the first employee only, refusing every duplicate or second account."""

    cleaned_username = username.strip()
    if not cleaned_username:
        raise ValueError("Username must not be blank")

    async with session_scope(session_maker) as db_session:
        await db_session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": EMPLOYEE_PROVISIONING_ADVISORY_LOCK_KEY},
        )
        employee_exists = await db_session.scalar(select(Employee.id).limit(1))
        if employee_exists is not None:
            raise ValueError("An employee account already exists; this pilot permits only one")

        employee = Employee(username=cleaned_username, password_hash=hash_password(password))
        db_session.add(employee)
        await db_session.commit()
        return employee


async def provision_interactively() -> None:
    """Prompt locally without echoing the password or writing secrets to output."""

    username = input("Username: ")
    password = getpass.getpass("Password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise ValueError("Passwords do not match")

    settings = Settings()
    engine = create_database_engine(settings.database_url)
    try:
        await create_sole_employee(create_session_maker(engine), username, password)
    finally:
        await engine.dispose()
    print("Employee account created.")


def main() -> None:
    """Run the deliberately local, interactive provisioning command."""

    try:
        asyncio.run(provision_interactively())
    except ValueError as error:
        print(f"Employee account was not created: {error}")
        raise SystemExit(1) from error


if __name__ == "__main__":  # pragma: no cover - exercised through the module entry point
    main()
