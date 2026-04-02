# -*- coding: utf-8 -*-
from __future__ import annotations

import json


def test_run_dry_run_reports_candidate_dialog(tmp_path, monkeypatch) -> None:
    from copaw.app import session_detailed_log_report as module

    sessions_root = tmp_path / "workspaces"
    session_dir = sessions_root / "default" / "sessions"
    session_dir.mkdir(parents=True)
    session_file = session_dir / "session_alpha.json"
    session_file.write_text(
        json.dumps(
            {
                "agent": {
                    "memory": {
                        "content": [
                            [
                                {
                                    "role": "user",
                                    "id": "req-1",
                                    "timestamp": "2026-03-29 10:00:00",
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": "hello world",
                                        },
                                    ],
                                },
                                [],
                            ],
                            [
                                {
                                    "role": "assistant",
                                    "timestamp": "2026-03-29 10:00:05",
                                    "content": [
                                        {"type": "text", "text": "done"},
                                    ],
                                },
                                [],
                            ],
                        ],
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "COPAW_SESSION_SKILL_REPORT_STATE_DIR",
        str(tmp_path / "state"),
    )
    monkeypatch.setattr(module, "resolve_user_id", lambda: "mac:test-device")

    summary = module.run(
        [
            "--sessions-dir",
            str(sessions_root),
            "--dry-run",
        ],
    )

    assert summary["success"] is True
    assert summary["scanned_workspaces"] == 1
    assert summary["scanned_sessions"] == 1
    assert summary["candidate_dialogs"] == 1
    assert summary["uploaded_count"] == 1
    assert summary["failed_count"] == 0
    assert summary["uploaded"][0]["sessionid"] == "alpha"
    assert summary["uploaded"][0]["request_id"] == "req-1"


def test_main_prints_failure_summary_and_returns_zero(
    tmp_path,
    capsys,
) -> None:
    from copaw.app import session_detailed_log_report as module

    exit_code = module.main(
        [
            "--sessions-dir",
            str(tmp_path / "missing"),
        ],
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["success"] is False
    assert "sessions dir not found" in output["error"]
