import pytest


@pytest.mark.asyncio
async def test_admin_user_response_includes_is_admin(admin_client):
    """Verify UserResponse includes is_admin field for admin users"""
    response = await admin_client.get("/api/v1/auth/me")
    assert response.status_code == 200
    data = response.json()
    assert "is_admin" in data
    assert data["is_admin"] is True


@pytest.mark.asyncio
async def test_non_admin_user_response_includes_is_admin(authenticated_client):
    """Verify UserResponse includes is_admin field for non-admin users"""
    response = await authenticated_client.get("/api/v1/auth/me")
    assert response.status_code == 200
    data = response.json()
    assert "is_admin" in data
    assert data["is_admin"] is False


@pytest.mark.asyncio
async def test_non_admin_cannot_access_upgrade_to_enterprise(authenticated_client):
    """Non-admin users should get 403 when accessing upgrade-to-enterprise endpoint"""
    response = await authenticated_client.post("/api/v1/users/upgrade-to-enterprise")
    assert response.status_code == 403
    assert "Admin access required" in response.json()["detail"]


@pytest.mark.asyncio
async def test_admin_can_access_upgrade_to_enterprise(admin_client):
    """Admin users should be able to access upgrade-to-enterprise endpoint"""
    response = await admin_client.post("/api/v1/users/upgrade-to-enterprise")
    assert response.status_code == 200
    data = response.json()
    assert data["tier"] == "enterprise"
    assert "Successfully upgraded" in data["message"]


@pytest.mark.asyncio
async def test_non_admin_cannot_access_set_tier(authenticated_client):
    """Non-admin users should get 403 when accessing set-tier endpoint"""
    response = await authenticated_client.post("/api/v1/users/set-tier/pro")
    assert response.status_code == 403
    assert "Admin access required" in response.json()["detail"]


@pytest.mark.asyncio
async def test_admin_can_set_tier(admin_client):
    """Admin users should be able to set any tier"""
    response = await admin_client.post("/api/v1/users/set-tier/pro")
    assert response.status_code == 200
    data = response.json()
    assert data["tier"] == "pro"
    assert "Successfully set tier to pro" in data["message"]

    # Test setting to another tier
    response = await admin_client.post("/api/v1/users/set-tier/free")
    assert response.status_code == 200
    assert response.json()["tier"] == "free"
