# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Iterable, Optional

from ..constant import HEARTBEAT_FILE
from . import session_detailed_log_report, session_skill_report

logger = logging.getLogger(__name__)

DEFAULT_SESSION_REPORT_STARTUP_DELAY_SECONDS = 60
DEFAULT_SESSION_REPORT_INTERVAL_SECONDS = 5 * 60

LEGACY_SESSION_REPORT_COMMAND_MARKERS = (
    "python -m copaw.app.session_skill_report",
    "python -m copaw.app.session_detailed_log_report",
    "copaw session-skill-report",
    "copaw session-detailed-log-report",
)


def contains_legacy_session_report_commands(raw: str) -> bool:
    text = str(raw or "").lower()
    return any(marker in text for marker in LEGACY_SESSION_REPORT_COMMAND_MARKERS)


def iter_workspace_dirs(multi_agent_manager: Any) -> Iterable[Path]:
    agents = getattr(multi_agent_manager, "agents", {}) or {}
    for workspace in agents.values():
        workspace_dir = getattr(workspace, "workspace_dir", None)
        if workspace_dir:
            yield Path(workspace_dir)


def manager_uses_legacy_session_report_heartbeat(
    multi_agent_manager: Any,
) -> bool:
    for workspace_dir in iter_workspace_dirs(multi_agent_manager):
        heartbeat_file = workspace_dir / HEARTBEAT_FILE
        if not heartbeat_file.is_file():
            continue
        try:
            content = heartbeat_file.read_text(encoding="utf-8")
        except OSError:
            continue
        if contains_legacy_session_report_commands(content):
            logger.warning(
                "SessionReportService disabled: legacy heartbeat session "
                "report command detected in %s",
                heartbeat_file,
            )
            return True
    return False


class SessionReportService:
    def __init__(
        self,
        *,
        startup_delay_seconds: int = DEFAULT_SESSION_REPORT_STARTUP_DELAY_SECONDS,
        interval_seconds: int = DEFAULT_SESSION_REPORT_INTERVAL_SECONDS,
        skill_report_runner: Any = None,
        detailed_report_runner: Any = None,
    ):
        self._startup_delay_seconds = max(0, int(startup_delay_seconds))
        self._interval_seconds = max(1, int(interval_seconds))
        self._skill_report_runner = skill_report_runner or session_skill_report.run
        self._detailed_report_runner = (
            detailed_report_runner or session_detailed_log_report.run
        )
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self.last_results: dict[str, Any] = {}

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(
            self._loop(),
            name="session_report_service",
        )
        logger.info(
            "SessionReportService started (startup_delay=%ss interval=%ss)",
            self._startup_delay_seconds,
            self._interval_seconds,
        )

    async def stop(self) -> None:
        if not self._task:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("SessionReportService stopped")

    async def _loop(self) -> None:
        try:
            if self._startup_delay_seconds > 0:
                await asyncio.sleep(self._startup_delay_seconds)
            while True:
                await self._run_once()
                await asyncio.sleep(self._interval_seconds)
        except asyncio.CancelledError:
            raise

    async def _run_once(self) -> bool:
        if self._running:
            logger.warning(
                "SessionReportService skipped tick: previous round still running",
            )
            return False

        self._running = True
        try:
            await self._run_report(
                report_name="session_skill_report",
                runner=self._skill_report_runner,
            )
            await self._run_report(
                report_name="session_detailed_log_report",
                runner=self._detailed_report_runner,
            )
            return True
        finally:
            self._running = False

    async def _run_report(self, *, report_name: str, runner: Any) -> dict[str, Any]:
        try:
            summary = await asyncio.to_thread(runner, [])
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("SessionReportService %s failed", report_name)
            summary = {"success": False, "error": str(exc)}
        self.last_results[report_name] = summary
        return summary


async def start_session_report_service_if_enabled(
    multi_agent_manager: Any,
) -> SessionReportService | None:
    if manager_uses_legacy_session_report_heartbeat(multi_agent_manager):
        return None

    service = SessionReportService()
    await service.start()
    return service
