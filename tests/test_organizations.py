from typing import Any
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient

from tests.conftest import _default_org_data


class TestCreateOrganization:
    async def test_create_org_success(
        self,
        client: AsyncClient,
        create_user: Any,
        mock_dadata: MagicMock,
    ) -> None:
        _, token = await create_user()
        data = _default_org_data()
        resp = await client.post(
            "/organizations/",
            json=data,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["inn"] == "7707083893"
        assert body["short_name"] == 'ООО "Рога и копыта"'
        assert body["status"] == "created"
        assert len(body["contacts"]) == 1
        assert body["contacts"][0]["display_name"] == "Иван Иванов"
        mock_dadata.find_by_id.assert_called_once_with("party", "7707083893")

    @pytest.mark.skip(reason="needs list members endpoint")
    async def test_create_org_creator_becomes_admin(
        self,
        client: AsyncClient,
        create_user: Any,
    ) -> None:
        _, token = await create_user()
        data = _default_org_data()
        resp = await client.post(
            "/organizations/",
            json=data,
            headers={"Authorization": f"Bearer {token}"},
        )
        org_id = resp.json()["id"]
        members_resp = await client.get(
            f"/organizations/{org_id}/members",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert members_resp.status_code == 200
        members = members_resp.json()
        assert len(members) == 1
        assert members[0]["role"] == "admin"
        assert members[0]["status"] == "member"

    async def test_create_org_duplicate_inn(
        self,
        client: AsyncClient,
        create_user: Any,
    ) -> None:
        _, token1 = await create_user()
        _, token2 = await create_user(email="other@example.com")
        data = _default_org_data()
        await client.post("/organizations/", json=data, headers={"Authorization": f"Bearer {token1}"})
        resp = await client.post("/organizations/", json=data, headers={"Authorization": f"Bearer {token2}"})
        assert resp.status_code == 409

    async def test_create_org_invalid_inn(self, client: AsyncClient, create_user: Any) -> None:
        _, token = await create_user()
        data = _default_org_data(inn="123")
        resp = await client.post("/organizations/", json=data, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 422

    async def test_create_org_no_contacts(self, client: AsyncClient, create_user: Any) -> None:
        _, token = await create_user()
        data = _default_org_data(contacts=[])
        resp = await client.post("/organizations/", json=data, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 422

    async def test_create_org_contact_missing_phone_and_email(
        self,
        client: AsyncClient,
        create_user: Any,
    ) -> None:
        _, token = await create_user()
        data = _default_org_data(contacts=[{"display_name": "Test"}])
        resp = await client.post("/organizations/", json=data, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 422

    async def test_create_org_dadata_failure(
        self,
        client: AsyncClient,
        create_user: Any,
        mock_dadata: MagicMock,
    ) -> None:
        mock_dadata.find_by_id.side_effect = Exception("Dadata unavailable")
        _, token = await create_user()
        data = _default_org_data()
        resp = await client.post("/organizations/", json=data, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 502

    async def test_create_org_dadata_empty(
        self,
        client: AsyncClient,
        create_user: Any,
        mock_dadata: MagicMock,
    ) -> None:
        mock_dadata.find_by_id.return_value = []
        _, token = await create_user()
        data = _default_org_data()
        resp = await client.post("/organizations/", json=data, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 502

    async def test_create_org_unauthenticated(self, client: AsyncClient) -> None:
        data = _default_org_data()
        resp = await client.post("/organizations/", json=data)
        assert resp.status_code == 401


class TestGetOrganization:
    async def test_get_org_by_id(self, client: AsyncClient, create_organization: Any) -> None:
        org_data, _ = await create_organization()
        resp = await client.get(f"/organizations/{org_data['id']}")
        assert resp.status_code == 200
        assert resp.json()["inn"] == "7707083893"
        assert len(resp.json()["contacts"]) == 1

    async def test_get_org_not_found(self, client: AsyncClient) -> None:
        resp = await client.get("/organizations/ZZZZZZ")
        assert resp.status_code == 404


class TestListUserOrganizations:
    async def test_list_my_orgs(self, client: AsyncClient, create_organization: Any) -> None:
        org_data, token = await create_organization()
        resp = await client.get("/users/me/organizations", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        orgs = resp.json()
        assert len(orgs) == 1
        assert orgs[0]["id"] == org_data["id"]

    async def test_list_my_orgs_empty(self, client: AsyncClient, create_user: Any) -> None:
        _, token = await create_user()
        resp = await client.get("/users/me/organizations", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_my_orgs_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/users/me/organizations")
        assert resp.status_code == 401


class TestVerifyOrganization:
    async def test_verify_org(
        self,
        client: AsyncClient,
        create_organization: Any,
        admin_user: tuple[dict[str, Any], str],
    ) -> None:
        org_data, _ = await create_organization()
        _, admin_token = admin_user
        resp = await client.patch(
            f"/private/organizations/{org_data['id']}/verify",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "verified"

    async def test_verify_org_idempotent(
        self,
        client: AsyncClient,
        create_organization: Any,
        admin_user: tuple[dict[str, Any], str],
    ) -> None:
        org_data, _ = await create_organization()
        _, admin_token = admin_user
        await client.patch(
            f"/private/organizations/{org_data['id']}/verify",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        resp = await client.patch(
            f"/private/organizations/{org_data['id']}/verify",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "verified"

    async def test_verify_org_not_admin(self, client: AsyncClient, create_organization: Any) -> None:
        org_data, token = await create_organization()
        resp = await client.patch(
            f"/private/organizations/{org_data['id']}/verify",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    async def test_verify_org_not_found(
        self,
        client: AsyncClient,
        admin_user: tuple[dict[str, Any], str],
    ) -> None:
        _, admin_token = admin_user
        resp = await client.patch(
            "/private/organizations/ZZZZZZ/verify",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404
