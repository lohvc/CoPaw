# -*- coding: utf-8 -*-
"""Helpers for collecting stable device identifiers."""

from __future__ import annotations

import subprocess

_WINDOWS_ID_PLACEHOLDERS = {
    "",
    "default string",
    "none",
    "not specified",
    "null",
    "system serial number",
    "to be filled by o.e.m.",
    "to be filled by oem",
    "unknown",
}


def _normalize_identifier(value: str | None) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return ""
    if text.lower() in _WINDOWS_ID_PLACEHOLDERS:
        return ""
    return text


def _run_windows_command(args: list[str], *, timeout: int = 10) -> str:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def get_windows_machine_guid() -> str:
    try:
        import winreg  # type: ignore

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\\Microsoft\\Cryptography",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
    except Exception:
        return ""
    return _normalize_identifier(str(value))


def get_windows_baseboard_serial() -> str:
    outputs = [
        _run_windows_command(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance Win32_BaseBoard | "
                "Select-Object -ExpandProperty SerialNumber)",
            ],
        ),
        _run_windows_command(
            [
                "wmic",
                "baseboard",
                "get",
                "serialnumber",
            ],
        ),
    ]

    for output in outputs:
        if not output:
            continue
        for line in output.splitlines():
            cleaned = _normalize_identifier(line)
            if not cleaned or cleaned.lower() == "serialnumber":
                continue
            return cleaned
    return ""


def build_windows_device_id(
    *,
    machine_guid: str,
    baseboard_serial: str,
) -> str:
    parts: list[str] = []
    if machine_guid:
        parts.append(f"guid={machine_guid}")
    if baseboard_serial:
        parts.append(f"baseboard={baseboard_serial}")
    return ";".join(parts)
