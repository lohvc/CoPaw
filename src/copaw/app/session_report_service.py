# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from . import session_detailed_log_report, session_skill_report

logger = logging.getLogger(__name__)


def _best_effort_log_warning(message: str, exc: Exception) -> None:
    try:
        logger.warning(
            "%s: %s",
            message,
            exc,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
    except Exception:
        pass


def _failure_summary(error_message: str) -> dict[str, Any]:
    return {
        "success": False,
        "error": error_message,
    }


def _build_report_argv(sessions_root: Path) -> list[str]:
    return ["--sessions-dir", str(sessions_root)]


async def _run_report(
    *,
    report_name: str,
    runner: Any,
    argv: list[str],
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(runner, argv)
    except Exception as exc:  # pylint: disable=broad-except
        _best_effort_log_warning(
            f"Immediate session report {report_name} failed",
            exc,
        )
        return _failure_summary(str(exc))


async def trigger_session_reports_for_workspace(
    sessions_root: Path,
    *,
    skill_report_runner: Any = None,
    detailed_report_runner: Any = None,
) -> dict[str, dict[str, Any]]:
    """Run both session upload jobs once for the given sessions root."""
    try:
        root = Path(sessions_root).expanduser().resolve()
        argv = _build_report_argv(root)
        skill_runner = skill_report_runner or session_skill_report.run
        detailed_runner = (
            detailed_report_runner or session_detailed_log_report.run
        )

        skill_summary = await _run_report(
            report_name="session_skill_report",
            runner=skill_runner,
            argv=argv,
        )
        detailed_summary = await _run_report(
            report_name="session_detailed_log_report",
            runner=detailed_runner,
            argv=argv,
        )

        return {
            "session_skill_report": skill_summary,
            "session_detailed_log_report": detailed_summary,
        }
    except Exception as exc:  # pylint: disable=broad-except
        _best_effort_log_warning(
            "Immediate session report dispatch failed",
            exc,
        )
        failure = _failure_summary(str(exc))
        return {
            "session_skill_report": dict(failure),
            "session_detailed_log_report": dict(failure),
        }
