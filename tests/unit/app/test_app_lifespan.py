# -*- coding: utf-8 -*-
import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI


@pytest.mark.asyncio
async def test_lifespan_starts_and_stops_session_report_service(monkeypatch):
    from copaw.app import _app as module

    events = []

    class FakeManager:
        async def start_all_configured_agents(self):
            events.append("manager_start")
            return {"default": True}

        async def get_agent(self, agent_id):
            assert agent_id == "default"
            return SimpleNamespace(channel_manager=None)

        async def stop_all(self):
            events.append("manager_stop")

    class FakeProviderManager:
        @staticmethod
        def get_instance():
            return object()

    class FakeService:
        async def stop(self):
            events.append("service_stop")

    async def fake_start_session_report_service_if_enabled(manager):
        assert isinstance(manager, FakeManager)
        events.append("service_start")
        return FakeService()

    monkeypatch.setattr(module, "add_copaw_file_handler", lambda *_: None)
    monkeypatch.setattr(
        module,
        "migrate_legacy_workspace_to_default_agent",
        lambda: None,
    )
    monkeypatch.setattr(module, "ensure_default_agent_exists", lambda: None)
    monkeypatch.setattr(module, "ensure_qa_agent_exists", lambda: None)
    monkeypatch.setattr(module, "MultiAgentManager", FakeManager)
    monkeypatch.setattr(module, "ProviderManager", FakeProviderManager)
    monkeypatch.setattr(
        module,
        "start_session_report_service_if_enabled",
        fake_start_session_report_service_if_enabled,
    )
    monkeypatch.setattr("copaw.app.auth.auto_register_from_env", lambda: None)
    monkeypatch.setitem(
        sys.modules,
        "copaw.utils.telemetry",
        SimpleNamespace(
            collect_and_upload_telemetry=lambda *_: None,
            has_telemetry_been_collected=lambda *_: True,
            is_telemetry_opted_out=lambda *_: True,
        ),
    )

    app = FastAPI()

    async with module.lifespan(app):
        assert events == ["manager_start", "service_start"]
        assert isinstance(app.state.session_report_service, FakeService)

    assert events == [
        "manager_start",
        "service_start",
        "service_stop",
        "manager_stop",
    ]
