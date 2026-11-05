from __future__ import annotations

import pytest

import app.api.routes.agents as agents_route


def _find(items, agent_id: str):
    for item in items:
        if item.id == agent_id:
            return item
    return None


def test_build_catalog_marks_enabled_and_disabled_notes():
    registered = {
        "legal": {"name": "Legal Assistant", "class": "LegalAgent"},
        "orphan_agent": {"name": "Orphan Agent", "class": "OrphanAgent"},
    }

    items = agents_route._build_catalog(registered)

    legal = _find(items, "legal")
    assert legal is not None
    assert legal.enabled is True
    assert legal.has_policy is True
    assert legal.display_name == "Legal Assistant"

    # Known in policy, not registered in this snapshot.
    citizen = _find(items, "citizen_agent")
    assert citizen is not None
    assert citizen.enabled is False
    assert citizen.has_policy is True
    assert any("implementation is not registered" in n for n in citizen.notes)

    orphan = _find(items, "orphan_agent")
    assert orphan is not None
    assert orphan.enabled is True
    assert orphan.has_policy is False
    assert any("no policy entry" in n for n in orphan.notes)


@pytest.mark.asyncio
async def test_list_agents_lazy_register_defaults(monkeypatch):
    calls = {"registered": False}

    class _DummyRegistry:
        def list_agents(self):
            if not calls["registered"]:
                return {}
            return {"legal": {"name": "Legal Assistant", "class": "LegalAgent"}}

    def _fake_register_defaults():
        calls["registered"] = True

    monkeypatch.setattr(agents_route, "registry", _DummyRegistry())
    monkeypatch.setattr(agents_route, "register_defaults", _fake_register_defaults)

    rows = await agents_route.list_agents()

    assert calls["registered"] is True
    legal = _find(rows, "legal")
    assert legal is not None
    assert legal.enabled is True
