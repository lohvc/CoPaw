# -*- coding: utf-8 -*-
from __future__ import annotations

import sys


def test_build_windows_device_id_includes_machine_guid_and_baseboard() -> None:
    from copaw.utils import device_id as module

    value = module.build_windows_device_id(
        machine_guid="GUID-123",
        baseboard_serial="BOARD-456",
    )

    assert value == "guid=GUID-123;baseboard=BOARD-456"


def test_resolve_user_id_uses_combined_windows_identifiers(monkeypatch) -> None:
    from copaw.app import session_skill_report as module

    monkeypatch.setattr(module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(module, "get_windows_machine_guid", lambda: "GUID-123")
    monkeypatch.setattr(
        module,
        "get_windows_baseboard_serial",
        lambda: "BOARD-456",
    )

    assert (
        module.resolve_user_id()
        == "win:guid=GUID-123;baseboard=BOARD-456"
    )


def test_get_windows_machine_guid_returns_empty_on_registry_errors(
    monkeypatch,
) -> None:
    from copaw.utils import device_id as module

    class BrokenWinReg:
        HKEY_LOCAL_MACHINE = object()

        @staticmethod
        def OpenKey(*args, **kwargs):
            raise OSError("boom")

    monkeypatch.setitem(sys.modules, "winreg", BrokenWinReg)
    assert module.get_windows_machine_guid() == ""


def test_get_windows_baseboard_serial_skips_placeholder_values(
    monkeypatch,
) -> None:
    from copaw.utils import device_id as module

    outputs = iter(
        [
            "SerialNumber\r\nTo Be Filled By O.E.M.\r\n\r\n",
            "SerialNumber\r\nBOARD-456\r\n\r\n",
        ],
    )
    monkeypatch.setattr(
        module,
        "_run_windows_command",
        lambda *args, **kwargs: next(outputs),
    )

    assert module.get_windows_baseboard_serial() == "BOARD-456"
