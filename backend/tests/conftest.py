import asyncio
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.db.base import Base
from app.db.session import get_async_session
from app.main import app

# Use SQLite for tests
TEST_DB_URL = "sqlite+aiosqlite:///./test.db"

engine = create_async_engine(TEST_DB_URL, echo=False)
TestSession = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session():
    async with TestSession() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session):
    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_async_session] = override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def authenticated_client(client, db_session):
    """Client with a pre-created user and auth token."""
    # Create user
    response = await client.post(
        "/api/v1/auth/signup",
        json={"email": "test@test.com", "password": "Test123!", "full_name": "Test User"},
    )
    token = response.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


@pytest_asyncio.fixture
async def admin_client(client, db_session):
    """Client with a pre-created admin user and auth token."""
    # Create admin user
    response = await client.post(
        "/api/v1/auth/signup",
        json={"email": "admin@test.com", "password": "Test123!", "full_name": "Admin User"},
    )
    token = response.json()["access_token"]

    # Promote user to admin directly in database
    from app.models.user import User
    from sqlalchemy import select
    result = await db_session.execute(select(User).where(User.email == "admin@test.com"))
    admin_user = result.scalar_one()
    admin_user.is_admin = True
    await db_session.commit()

    client.headers["Authorization"] = f"Bearer {token}"
    return client


@pytest.fixture
def mock_storage():
    with patch("app.services.storage.storage") as mock:
        mock.upload_file = MagicMock()
        mock.download_file = MagicMock()
        mock.file_exists = MagicMock(return_value=True)
        mock.generate_presigned_url = MagicMock(return_value="http://mock-url")
        mock.delete_file = MagicMock()
        mock.delete_files = MagicMock()
        yield mock
