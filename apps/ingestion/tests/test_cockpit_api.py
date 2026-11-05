from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.routes import admin as admin_routes
from app.core.auth_context import TrustedContext, UserRole
from app.core.canonical_models import IngestionProfile
from app.core.taxonomy import TenantId


def _ctx(role: UserRole, tenant_id: str = "default") -> TrustedContext:
    return TrustedContext(
        tenant_id=TenantId(tenant_id),
        user_role=role,
    )


@pytest.fixture
def mock_pg(monkeypatch):
    repo = MagicMock()
    monkeypatch.setattr(admin_routes, "_pg", lambda: repo)
    return repo


def test_create_profile_admin_success(mock_pg):
    profile = IngestionProfile(
        profile_id=uuid4(),
        tenant_id="default",
        name="Legal Private",
        description="Secure legal docs",
        config={
            "scope": "internal",
            "security_level": 4,
            "doc_type": "legal",
        },
    )

    out = admin_routes.create_profile(profile, ctx=_ctx(UserRole.ADMIN))

    assert out.name == "Legal Private"
    mock_pg.create_profile.assert_called_once()
    call_args = mock_pg.create_profile.call_args.kwargs
    assert call_args["tenant_id"] == "default"
    assert call_args["name"] == "Legal Private"


def test_create_profile_citizen_forbidden(mock_pg):
    profile = IngestionProfile(
        profile_id=uuid4(),
        tenant_id="default",
        name="Hacker Profile",
        description="Attempt",
        config={},
    )

    with pytest.raises(HTTPException) as exc:
        admin_routes.create_profile(profile, ctx=_ctx(UserRole.CITIZEN))

    assert exc.value.status_code == 403
    mock_pg.create_profile.assert_not_called()


def test_list_profiles_admin(mock_pg):
    mock_pg.list_profiles.return_value = [
        {
            "profile_id": str(uuid4()),
            "tenant_id": "default",
            "name": "Profile A",
            "description": "A",
            "config": {},
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }
    ]

    rows = admin_routes.list_profiles(ctx=_ctx(UserRole.ADMIN))

    assert len(rows) == 1
    assert rows[0].name == "Profile A"
    mock_pg.list_profiles.assert_called_once_with(tenant_id="default")


def test_list_documents_admin(mock_pg):
    mock_pg.list_documents_for_tenant.return_value = [
        {
            "doc_id": str(uuid4()),
            "tenant_id": "default",
            "title": "Law A",
            "scope": "public",
            "doc_type": "law",
            "doc_category": "law",
            "security_level": 1,
            "is_deleted": False,
            "chunks_count": 2,
            "rows_count": 0,
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }
    ]

    body = admin_routes.list_documents(
        limit=10,
        scope="public",
        doc_type="law",
        is_deleted=False,
        ctx=_ctx(UserRole.ADMIN),
    )

    assert len(body) == 1
    assert body[0]["doc_type"] == "law"
    assert body[0]["chunks_count"] == 2
    mock_pg.list_documents_for_tenant.assert_called_once_with(
        "default",
        scope="public",
        doc_type="law",
        is_deleted=False,
        limit=10,
    )
