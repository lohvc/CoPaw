# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_trigger_session_reports_for_workspace_runs_both_uploads(
    monkeypatch,
    tmp_path,
):
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

    summary = await module.trigger_session_reports_for_workspace(
        tmp_path,
        skill_report_runner=skill_report,
        detailed_report_runner=detailed_report,
    )

    expected_argv = ["--sessions-dir", str(tmp_path)]
    assert calls == [
        ("skill_report", expected_argv),
        ("detailed_report", expected_argv),
    ]
    assert summary["session_skill_report"]["name"] == "skill"
    assert summary["session_detailed_log_report"]["name"] == "detailed"


@pytest.mark.asyncio
async def test_trigger_session_reports_records_failures_and_continues(
    monkeypatch,
    tmp_path,
):
    from copaw.app import session_report_service as module

    def failing_skill_report(argv=None):
        raise RuntimeError("network error")

    def detailed_report(argv=None):
        return {"name": "detailed", "argv": argv}

    async def fake_to_thread(func, argv):
        return func(argv)

    monkeypatch.setattr(module.asyncio, "to_thread", fake_to_thread)

    summary = await module.trigger_session_reports_for_workspace(
        tmp_path,
        skill_report_runner=failing_skill_report,
        detailed_report_runner=detailed_report,
    )

    assert summary["session_skill_report"]["success"] is False
    assert "network error" in summary["session_skill_report"]["error"]
    assert summary["session_detailed_log_report"]["name"] == "detailed"


@pytest.mark.asyncio
async def test_trigger_session_reports_ignores_unexpected_setup_errors(
    monkeypatch,
    tmp_path,
):
    from copaw.app import session_report_service as module

    def fail_build_report_argv(*args, **kwargs):
        raise RuntimeError("bad sessions root")

    monkeypatch.setattr(module, "_build_report_argv", fail_build_report_argv)

    summary = await module.trigger_session_reports_for_workspace(tmp_path)

    assert summary["session_skill_report"]["success"] is False
    assert summary["session_detailed_log_report"]["success"] is False
    assert "bad sessions root" in summary["session_skill_report"]["error"]
