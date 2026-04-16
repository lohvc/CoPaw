# -*- coding: utf-8 -*-
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_default_service_interval_is_five_minutes():
    from copaw.app import session_report_service as module

    service = module.SessionReportService()

    assert service._interval_seconds == 5 * 60  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_run_once_executes_reports_in_order(monkeypatch):
    from copaw.app import session_report_service as module

    calls = []

    def skill_report(argv=None):
        return {"name": "skill", "argv": argv}

    def detailed_report(argv=None):
        return {"name": "detailed", "argv": argv}

    async def fake_to_thread(func, argv):
        calls.append((func.__name__, argv))
        return func(argv)

    monkeypatch.setattr(module.asyncio, "to_thread", fake_to_thread)

    service = module.SessionReportService(
        startup_delay_seconds=0,
        interval_seconds=60,
        skill_report_runner=skill_report,
        detailed_report_runner=detailed_report,
    )

    assert await service._run_once() is True
    assert calls == [
        ("skill_report", []),
        ("detailed_report", []),
    ]
    assert service.last_results["session_skill_report"]["name"] == "skill"
    assert (
        service.last_results["session_detailed_log_report"]["name"]
        == "detailed"
    )


@pytest.mark.asyncio
async def test_run_once_skips_when_previous_round_is_still_running(monkeypatch):
    from copaw.app import session_report_service as module

    calls = []

    async def fake_to_thread(*args, **kwargs):
        calls.append((args, kwargs))
        return {}

    monkeypatch.setattr(module.asyncio, "to_thread", fake_to_thread)

    service = module.SessionReportService(
        startup_delay_seconds=0,
        interval_seconds=60,
    )
    service._running = True  # pylint: disable=protected-access

    assert await service._run_once() is False
    assert calls == []


def test_manager_uses_legacy_session_report_heartbeat(tmp_path):
    from copaw.app import session_report_service as module

    workspace_dir = tmp_path / "default"
    workspace_dir.mkdir()
    (workspace_dir / "HEARTBEAT.md").write_text(
        "执行 `python -m copaw.app.session_skill_report`\n",
        encoding="utf-8",
    )

    manager = SimpleNamespace(
        agents={
            "default": SimpleNamespace(workspace_dir=workspace_dir),
        },
    )

    assert module.manager_uses_legacy_session_report_heartbeat(manager) is True


@pytest.mark.asyncio
async def test_start_service_if_enabled_starts_without_legacy_commands(
    monkeypatch,
    tmp_path,
):
    from copaw.app import session_report_service as module

    workspace_dir = tmp_path / "default"
    workspace_dir.mkdir()
    (workspace_dir / "HEARTBEAT.md").write_text(
        "# Heartbeat checklist\n- Scan inbox\n",
        encoding="utf-8",
    )
    manager = SimpleNamespace(
        agents={
            "default": SimpleNamespace(workspace_dir=workspace_dir),
        },
    )

    events = []

    class FakeSessionReportService:
        def __init__(self):
            events.append("init")

        async def start(self):
            events.append("start")

    monkeypatch.setattr(module, "SessionReportService", FakeSessionReportService)

    service = await module.start_session_report_service_if_enabled(manager)

    assert events == ["init", "start"]
    assert service is not None


@pytest.mark.asyncio
async def test_start_service_if_enabled_skips_with_legacy_commands(
    monkeypatch,
    tmp_path,
):
    from copaw.app import session_report_service as module

    workspace_dir = tmp_path / "default"
    workspace_dir.mkdir()
    (workspace_dir / "HEARTBEAT.md").write_text(
        "run `python -m copaw.app.session_detailed_log_report`.\n",
        encoding="utf-8",
    )
    manager = SimpleNamespace(
        agents={
            "default": SimpleNamespace(workspace_dir=workspace_dir),
        },
    )

    async def fail_start(*args, **kwargs):  # pragma: no cover
        raise AssertionError("service should not start when legacy commands exist")

    class FakeSessionReportService:
        start = fail_start

    monkeypatch.setattr(module, "SessionReportService", FakeSessionReportService)

    service = await module.start_session_report_service_if_enabled(manager)

    assert service is None
