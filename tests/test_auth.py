import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.dependencies import SESSION_COOKIE_NAME, pwd_context
from app.main import app
from app.models.models import User


@pytest.mark.asyncio
async def test_web_login_uses_an_app_specific_session_cookie(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        session.add(
            User(
                email="admin@example.test",
                password_hash=pwd_context.hash("test-password"),
                bearer_token=None,
                is_active=True,
                is_admin=True,
            )
        )
        await session.commit()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            client.cookies.set(
                "access_token",
                "another-local-application-session",
            )

            login = await client.post(
                "/login",
                data={
                    "username": "admin@example.test",
                    "password": "test-password",
                },
                follow_redirects=False,
            )
            home = await client.get(login.headers["location"])
            docs = await client.get("/docs", follow_redirects=False)

            assert login.status_code == 303
            assert SESSION_COOKIE_NAME in login.cookies
            assert "access_token" not in login.cookies
            assert client.cookies.get("access_token") == (
                "another-local-application-session"
            )
            assert "Logged in as" in home.text
            assert "admin@example.test" in home.text
            assert docs.status_code == 200

            logout = await client.post("/logout", follow_redirects=False)

            assert logout.status_code == 302
            assert SESSION_COOKIE_NAME not in client.cookies
            assert client.cookies.get("access_token") == (
                "another-local-application-session"
            )
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_override
        await engine.dispose()
