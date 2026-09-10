import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash
from app.models.entities import User


@pytest.mark.asyncio
async def test_auth_register_success_and_conflict(client: AsyncClient):
    # Register player
    payload = {
        "username": "new_player",
        "email": "new_player@example.com",
        "password": "Password123!",
        "global_role": "player",
    }
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "new_player"
    assert data["global_role"] == "player"

    # Register admin
    admin_payload = {
        "username": "new_admin",
        "email": "new_admin@example.com",
        "password": "Password123!",
        "global_role": "admin",
    }
    resp_admin = await client.post("/api/v1/auth/register", json=admin_payload)
    assert resp_admin.status_code == 201
    assert resp_admin.json()["global_role"] == "admin"

    # Fallback role when role is unknown
    other_payload = {
        "username": "other_user",
        "email": "other@example.com",
        "password": "Password123!",
        "global_role": "unknown_role",
    }
    resp_other = await client.post("/api/v1/auth/register", json=other_payload)
    assert resp_other.status_code == 201
    assert resp_other.json()["global_role"] == "player"

    # Conflict on username
    conflict_username = {
        "username": "new_player",
        "email": "different_email@example.com",
        "password": "Password123!",
    }
    resp_conflict = await client.post("/api/v1/auth/register", json=conflict_username)
    assert resp_conflict.status_code == 409

    # Conflict on email
    conflict_email = {
        "username": "unique_username",
        "email": "new_player@example.com",
        "password": "Password123!",
    }
    resp_conflict2 = await client.post("/api/v1/auth/register", json=conflict_email)
    assert resp_conflict2.status_code == 409


@pytest.mark.asyncio
async def test_auth_token_login_flows(client: AsyncClient, db_session: AsyncSession):
    # Create test user
    user = User(
        id=uuid.uuid4(),
        username="login_tester",
        email="tester@tournament.test",
        hashed_password=get_password_hash("Secret123!"),
        global_role="player",
    )
    db_session.add(user)
    await db_session.commit()

    # Successful login by username
    resp = await client.post(
        "/api/v1/auth/token",
        data={"username": "login_tester", "password": "Secret123!"},
    )
    assert resp.status_code == 200
    token_data = resp.json()
    assert "access_token" in token_data
    assert token_data["token_type"] == "bearer"

    # Successful login by email
    resp_email = await client.post(
        "/api/v1/auth/token",
        data={"username": "tester@tournament.test", "password": "Secret123!"},
    )
    assert resp_email.status_code == 200

    # Wrong password
    resp_wrong_pass = await client.post(
        "/api/v1/auth/token",
        data={"username": "login_tester", "password": "WrongPassword!"},
    )
    assert resp_wrong_pass.status_code == 401

    # Nonexistent user
    resp_no_user = await client.post(
        "/api/v1/auth/token",
        data={"username": "does_not_exist", "password": "Secret123!"},
    )
    assert resp_no_user.status_code == 401


@pytest.mark.asyncio
async def test_auth_list_users(client: AsyncClient, db_session: AsyncSession):
    user1 = User(
        id=uuid.uuid4(),
        username="u1",
        email="u1@test.local",
        hashed_password=get_password_hash("pass"),
        global_role="player",
    )
    db_session.add(user1)
    await db_session.commit()

    resp = await client.get("/api/v1/auth/users")
    assert resp.status_code == 200
    users = resp.json()
    assert isinstance(users, list)
    assert any(u["username"] == "u1" for u in users)


@pytest.mark.asyncio
async def test_auth_dev_token(client: AsyncClient, db_session: AsyncSession):
    user = User(
        id=uuid.uuid4(),
        username="dev_user",
        email="dev@test.local",
        hashed_password=get_password_hash("pass"),
        global_role="admin",
    )
    db_session.add(user)
    await db_session.commit()

    # Valid user id
    resp = await client.post(f"/api/v1/auth/dev-token/{user.id}")
    assert resp.status_code == 200
    assert "access_token" in resp.json()

    # Invalid UUID
    resp_bad_uuid = await client.post("/api/v1/auth/dev-token/not-a-uuid")
    assert resp_bad_uuid.status_code == 400

    # Nonexistent user
    random_id = uuid.uuid4()
    resp_not_found = await client.post(f"/api/v1/auth/dev-token/{random_id}")
    assert resp_not_found.status_code == 404
