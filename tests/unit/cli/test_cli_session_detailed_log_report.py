# -*- coding: utf-8 -*-
from __future__ import annotations

from click.testing import CliRunner

from copaw.cli.main import cli


def test_session_detailed_log_report_command_forwards_args(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_main(argv=None) -> int:
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(
        "copaw.cli.session_detailed_log_report_cmd.main",
        fake_main,
    )

    result = CliRunner().invoke(
        cli,
        [
            "session-detailed-log-report",
            "--sessions-dir",
            "/tmp/workspaces",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert captured["argv"] == [
        "--sessions-dir",
        "/tmp/workspaces",
        "--dry-run",
    ]
