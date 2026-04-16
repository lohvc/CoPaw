# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

import pytest


class _FakeMessage:
    def __init__(self, text: str):
        self._text = text

    def get_text_content(self) -> str:
        return self._text


@pytest.mark.asyncio
async def test_query_handler_schedules_session_report_after_save(
    monkeypatch,
    tmp_path,
):
    from copaw.app.runner import runner as module

    runner = module.AgentRunner(agent_id="default", workspace_dir=tmp_path)
    events: list[tuple[str, object]] = []

    class FakeSession:
        async def load_session_state(self, **kwargs):
            events.append(("load", kwargs["session_id"]))

        async def save_session_state(self, **kwargs):
            events.append(("save", kwargs["session_id"]))

    class FakeAgent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def register_mcp_clients(self):
            events.append(("register_mcp", None))

        def set_console_output_enabled(self, *, enabled: bool):
            events.append(("console_output", enabled))

        def rebuild_sys_prompt(self):
            events.append(("rebuild_prompt", None))

        async def __call__(self, msgs):
            events.append(("agent_call", len(msgs)))

    async def fake_stream_printing_messages(*, agents, coroutine_task):
        await coroutine_task
        yield SimpleNamespace(content="ok"), True

    async def fake_resolve_pending_approval(*args, **kwargs):
        return None, False, None

    created: dict[str, object] = {}

    class FakeTask:
        def add_done_callback(self, callback):
            created["done_callback"] = callback

        def cancelled(self):
            return False

        def exception(self):
            return None

    def fake_create_task(coro, name=None):
        created["coro"] = coro
        created["name"] = name
        return FakeTask()

    reported_roots: list[str] = []

    async def fake_trigger_session_reports_for_workspace(workspace_dir):
        reported_roots.append(str(workspace_dir))

    monkeypatch.setattr(module, "CoPawAgent", FakeAgent)
    monkeypatch.setattr(module, "build_env_context", lambda **kwargs: {})
    monkeypatch.setattr(module, "load_agent_config", lambda *_: object())
    monkeypatch.setattr(
        module,
        "stream_printing_messages",
        fake_stream_printing_messages,
    )
    monkeypatch.setattr(
        runner,
        "_resolve_pending_approval",
        fake_resolve_pending_approval,
    )
    monkeypatch.setattr(module.asyncio, "create_task", fake_create_task)
    monkeypatch.setattr(
        module,
        "trigger_session_reports_for_workspace",
        fake_trigger_session_reports_for_workspace,
        raising=False,
    )

    runner.session = FakeSession()
    request = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
    )
    msgs = [_FakeMessage("hello world")]

    results = []
    async for item in runner.query_handler(msgs, request=request):
        results.append(item)

    assert len(results) == 1
    assert ("save", "session-1") in events
    assert created["name"] == "session_report_upload:default:session-1"

    await created["coro"]

    assert reported_roots == [str(tmp_path / "sessions")]


@pytest.mark.asyncio
async def test_query_handler_ignores_session_report_schedule_failures(
    monkeypatch,
    tmp_path,
):
    from copaw.app.runner import runner as module

    runner = module.AgentRunner(agent_id="default", workspace_dir=tmp_path)
    events: list[tuple[str, object]] = []

    class FakeSession:
        async def load_session_state(self, **kwargs):
            events.append(("load", kwargs["session_id"]))

        async def save_session_state(self, **kwargs):
            events.append(("save", kwargs["session_id"]))

    class FakeAgent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def register_mcp_clients(self):
            events.append(("register_mcp", None))

        def set_console_output_enabled(self, *, enabled: bool):
            events.append(("console_output", enabled))

        def rebuild_sys_prompt(self):
            events.append(("rebuild_prompt", None))

        async def __call__(self, msgs):
            events.append(("agent_call", len(msgs)))

    async def fake_stream_printing_messages(*, agents, coroutine_task):
        await coroutine_task
        yield SimpleNamespace(content="ok"), True

    async def fake_resolve_pending_approval(*args, **kwargs):
        return None, False, None

    def fake_create_task(*args, **kwargs):
        raise RuntimeError("scheduler unavailable")

    monkeypatch.setattr(module, "CoPawAgent", FakeAgent)
    monkeypatch.setattr(module, "build_env_context", lambda **kwargs: {})
    monkeypatch.setattr(module, "load_agent_config", lambda *_: object())
    monkeypatch.setattr(
        module,
        "stream_printing_messages",
        fake_stream_printing_messages,
    )
    monkeypatch.setattr(
        runner,
        "_resolve_pending_approval",
        fake_resolve_pending_approval,
    )
    monkeypatch.setattr(module.asyncio, "create_task", fake_create_task)

    runner.session = FakeSession()
    request = SimpleNamespace(
        session_id="session-2",
        user_id="user-2",
        channel="console",
    )
    msgs = [_FakeMessage("hello again")]

    results = []
    async for item in runner.query_handler(msgs, request=request):
        results.append(item)

    assert len(results) == 1
    assert ("save", "session-2") in events


def test_handle_session_report_task_done_ignores_callback_errors():
    from copaw.app.runner import runner as module

    class FakeTask:
        def cancelled(self):
            return False

        def exception(self):
            raise RuntimeError("task inspection failed")

    module.AgentRunner._handle_session_report_task_done(FakeTask())
