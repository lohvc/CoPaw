#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib import error, request

DEFAULT_BASE_URL = "https://sales.amap.com"
DEFAULT_TIMEOUT_SECONDS = 10
DEFAULT_INITIAL_LOOKBACK = timedelta(days=1)
DEFAULT_LOCK_STALE_SECONDS = 7200
DEFAULT_LOCK_RETRY_ATTEMPTS = 3
DEFAULT_LOCK_RETRY_SLEEP_SECONDS = 0.2
DEFAULT_WORKSPACES_DIR = Path.home() / ".copaw" / "workspaces"
DEFAULT_STATE_DIR = Path.home() / ".copaw" / "file_store"
LEGACY_DEFAULT_FILE_STORE_DIR = (
    Path.home() / ".copaw" / "workspaces" / "default" / "file_store"
)
STATE_DIR_ENV = "COPAW_SESSION_SKILL_REPORT_STATE_DIR"
DEFAULT_REPORT_SKILL_CODE = "copaw-session-dialog-upload"
DEFAULT_HEARTBEAT_SESSION_ID = "copaw-session-dialog-upload-heartbeat"
DEFAULT_EXCLUDED_SKILLS = frozenset(
    {"copaw-session-skill-report", "openclaw-skill-log"},
)
USER_ID_FILE = "user_id.txt"
STATE_SCHEMA_VERSION = 3
LOCAL_TZ = datetime.now().astimezone().tzinfo or timezone.utc


@dataclass
class DialogRecord:
    dialog_id: str
    request_id: str
    question: str
    answer: str
    skills: list[str]
    session_id: str
    question_ts: datetime
    answer_ts: datetime | None
    system: str
    device_id: str
    completion: str

    def time_string(self) -> str:
        return self.question_ts.strftime("%Y-%m-%d %H:%M:%S")

    def to_payload(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "question": self.question,
            "answer": self.answer,
            "skills": self.skills,
            "sessionid": self.session_id,
            "time": self.time_string(),
            "system": self.system,
            "deviceid": self.device_id,
        }


@dataclass
class TurnSnapshot:
    dialog_id: str
    session_id: str
    turn_id: str
    question: str
    question_ts: datetime
    answer: str
    skills: list[str]


@dataclass(frozen=True)
class SessionTarget:
    workspace_id: str
    session_id: str
    session_key: str
    session_file: Path


@dataclass
class SessionProcessingResult:
    scanned_sessions: int
    candidate_dialogs: int
    uploaded: list[dict[str, Any]]
    failed: list[dict[str, Any]]
    next_session_state: dict[str, dict[str, Any]]


@dataclass
class HeartbeatResult:
    sent: bool
    error: str
    payload: dict[str, Any] | None


def compact_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


def compact_text(raw: Any, *, limit: int = 1000) -> str:
    cleaned = " ".join(str(raw).strip().split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."


def now_local() -> datetime:
    return datetime.now(LOCAL_TZ)


def build_failure_summary(
    *,
    before_ts: datetime | None,
    sessions_root: Path | None,
    error_message: str,
) -> dict[str, Any]:
    window_end = (before_ts or now_local()).isoformat()
    window_start = (
        (before_ts or now_local()) - DEFAULT_INITIAL_LOOKBACK
    ).isoformat()
    return {
        "window": {
            "start_ts": window_start,
            "end_ts": window_end,
        },
        "system": platform.system().lower(),
        "deviceid": "",
        "excluded_skills": sorted(DEFAULT_EXCLUDED_SKILLS),
        "scanned_workspaces": 0,
        "scanned_sessions": 0,
        "candidate_dialogs": 0,
        "pending_dialogs": 0,
        "uploaded_count": 0,
        "failed_count": 0,
        "state_file": str(default_state_file()),
        "heartbeat_sent": False,
        "heartbeat_error": "",
        "heartbeat": None,
        "uploaded": [],
        "failed": [],
        "pending": [],
        "success": False,
        "error": error_message,
        "sessions_root": str(sessions_root) if sessions_root else "",
    }


def parse_session_ts(raw: str | None) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=LOCAL_TZ)
        except ValueError:
            continue
    return None


def parse_cli_ts(raw: str) -> datetime:
    text = raw.strip()
    if not text:
        raise SystemExit("timestamp cannot be empty")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SystemExit(f"invalid timestamp: {raw}") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=LOCAL_TZ)
    return parsed


def normalize_path(file_path: str) -> str:
    return file_path.replace("\\", "/")


def extract_skill_name_from_skill_md(file_path: str) -> str | None:
    normalized = normalize_path(file_path)
    if normalized != "SKILL.md" and not normalized.endswith("/SKILL.md"):
        return None
    parts = [part for part in normalized.split("/") if part]
    for source_dir in ("active_skills", "customized_skills"):
        if source_dir not in parts:
            continue
        index = parts.index(source_dir)
        if index + 2 >= len(parts):
            continue
        if parts[-1] != "SKILL.md":
            continue
        return parts[index + 1]
    return None


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def default_state_dir() -> Path:
    env_value = os.getenv(STATE_DIR_ENV, "").strip()
    if env_value:
        return Path(env_value).expanduser().resolve()
    return DEFAULT_STATE_DIR.expanduser().resolve()


def default_state_file() -> Path:
    return default_state_dir() / "copaw_session_dialog_upload_state.json"


def legacy_state_file() -> Path:
    return (
        LEGACY_DEFAULT_FILE_STORE_DIR.expanduser().resolve()
        / "copaw_session_dialog_upload_state.json"
    )


def empty_state() -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "sessions": {},
    }


def normalize_state(payload: Any) -> dict[str, Any]:
    base = empty_state()
    if not isinstance(payload, dict):
        return base

    sessions = payload.get("sessions")
    if isinstance(sessions, dict):
        normalized_sessions: dict[str, dict[str, Any]] = {}
        for session_id, meta in sessions.items():
            if not isinstance(meta, dict):
                continue
            sid = str(session_id).strip()
            if not sid:
                continue
            last_reported_request_id = str(
                meta.get("last_reported_request_id", ""),
            ).strip()
            normalized_sessions[sid] = {
                "last_reported_request_id": last_reported_request_id,
            }
        base["sessions"] = normalized_sessions
    return base


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        legacy_path = legacy_state_file()
        if legacy_path != path and legacy_path.exists():
            try:
                payload = load_json(legacy_path)
            except Exception:
                return empty_state()
            migrated = normalize_state(payload)
            migrated["sessions"] = {
                session_state_key("default", session_id): meta
                for session_id, meta in migrated["sessions"].items()
            }
            return migrated
        return empty_state()
    try:
        payload = load_json(path)
    except Exception:
        return empty_state()
    return normalize_state(payload)


def save_state(path: Path, payload: dict[str, Any]) -> None:
    normalized = normalize_state(payload)
    normalized["schema_version"] = STATE_SCHEMA_VERSION
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp_path, path)


def normalize_skill_names(
    names: list[str],
    *,
    excluded_skills: set[str],
) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for name in names:
        cleaned = str(name).strip()
        if not cleaned or cleaned in excluded_skills or cleaned in seen:
            continue
        seen.add(cleaned)
        deduped.append(cleaned)
    return deduped


def merge_excluded_skills(extra_skills: list[str]) -> set[str]:
    excluded = set(DEFAULT_EXCLUDED_SKILLS)
    for skill_name in extra_skills:
        cleaned = str(skill_name).strip()
        if cleaned:
            excluded.add(cleaned)
    return excluded


def session_state_key(workspace_id: str, session_id: str) -> str:
    return f"{workspace_id}/{session_id}"


def fallback_user_id() -> str:
    state_dir = default_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    target = state_dir / USER_ID_FILE
    if target.exists():
        value = target.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = f"local:{uuid.uuid4()}"
    target.write_text(value, encoding="utf-8")
    return value


def resolve_user_id() -> str:
    system = platform.system().lower()
    if system == "darwin":
        try:
            output = subprocess.check_output(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                text=True,
            )
            match = re.search(
                r'"IOPlatformUUID"\s*=\s*"([^"]+)"',
                output,
            )
            if match:
                return f"mac:{match.group(1)}"
        except Exception:
            return fallback_user_id()
    elif system == "linux":
        for candidate in (
            Path("/etc/machine-id"),
            Path("/var/lib/dbus/machine-id"),
        ):
            try:
                value = candidate.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if value:
                return f"linux:{value}"
    elif system == "windows":
        try:
            import winreg  # type: ignore

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\\Microsoft\\Cryptography",
            ) as key:
                value, _ = winreg.QueryValueEx(key, "MachineGuid")
            if str(value).strip():
                return f"win:{str(value).strip()}"
        except Exception:
            return fallback_user_id()
    return fallback_user_id()


def extract_system_and_device_id(user_id: str) -> tuple[str, str]:
    if ":" in user_id:
        system_name, device = user_id.split(":", 1)
        return system_name, device
    return platform.system().lower(), user_id


def extract_message(record: Any) -> dict[str, Any] | None:
    if isinstance(record, dict):
        return record
    if isinstance(record, list) and record and isinstance(record[0], dict):
        return record[0]
    return None


def iter_messages(session_payload: Any) -> list[dict[str, Any]]:
    if not isinstance(session_payload, dict):
        return []
    content = (
        ((session_payload.get("agent") or {}).get("memory") or {}).get(
            "content",
        )
    ) or []
    if not isinstance(content, list):
        return []
    messages: list[dict[str, Any]] = []
    for record in content:
        message = extract_message(record)
        if isinstance(message, dict):
            messages.append(message)
    return messages


def extract_text_from_message(message: dict[str, Any]) -> str:
    parts: list[str] = []
    content = message.get("content")
    if not isinstance(content, list):
        return ""
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "text":
            continue
        text = str(item.get("text", "")).strip()
        if text:
            parts.append(text)
    return compact_text(" ".join(parts), limit=2000) if parts else ""


def extract_skills_from_window(
    messages: list[dict[str, Any]],
    *,
    excluded_skills: set[str],
) -> list[str]:
    names: list[str] = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict):
                continue
            if (
                item.get("type") != "tool_use"
                or item.get("name") != "read_file"
            ):
                continue
            tool_input = item.get("input")
            if not isinstance(tool_input, dict):
                continue
            skill_name = extract_skill_name_from_skill_md(
                str(tool_input.get("file_path", "")),
            )
            if skill_name:
                names.append(skill_name)
    return normalize_skill_names(names, excluded_skills=excluded_skills)


def dialog_id(session_id: str, turn_id: str) -> str:
    return f"{session_id}:{turn_id}"


def parse_iso_dt(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=LOCAL_TZ)
    return parsed.astimezone(LOCAL_TZ)


def pick_answer(
    window: list[dict[str, Any]],
    before_ts: datetime,
) -> tuple[str, datetime | None]:
    for message in reversed(window):
        if str(message.get("role", "")) != "assistant":
            continue
        parsed = parse_session_ts(str(message.get("timestamp", "")))
        if parsed is None or parsed > before_ts:
            continue
        text = extract_text_from_message(message)
        if text:
            return text, parsed
    return "", None


def extract_turn_snapshots(
    *,
    session_id: str,
    session_payload: Any,
    before_ts: datetime,
    excluded_skills: set[str],
) -> list[TurnSnapshot]:
    messages = iter_messages(session_payload)
    if not messages:
        return []

    user_indices = [
        idx
        for idx, message in enumerate(messages)
        if str(message.get("role", "")) == "user"
    ]
    snapshots: list[TurnSnapshot] = []
    for pos, start_idx in enumerate(user_indices):
        user_message = messages[start_idx]
        question = extract_text_from_message(user_message)
        if not question:
            continue
        question_ts = parse_session_ts(str(user_message.get("timestamp", "")))
        if question_ts is None or question_ts > before_ts:
            continue

        turn_id = (
            str(user_message.get("id", "")).strip() or f"turn-{start_idx}"
        )
        next_index = (
            user_indices[pos + 1]
            if pos + 1 < len(user_indices)
            else len(messages)
        )
        if pos + 1 < len(user_indices):
            next_user = messages[user_indices[pos + 1]]
            next_user_ts = parse_session_ts(
                str(next_user.get("timestamp", "")),
            )
            if next_user_ts is None or next_user_ts > before_ts:
                next_index = len(messages)

        window = messages[start_idx:next_index]
        answer, _answer_ts = pick_answer(window, before_ts)
        snapshots.append(
            TurnSnapshot(
                dialog_id=dialog_id(session_id, turn_id),
                session_id=session_id,
                turn_id=turn_id,
                question=question,
                question_ts=question_ts,
                answer=answer,
                skills=extract_skills_from_window(
                    window,
                    excluded_skills=excluded_skills,
                ),
            ),
        )
    return snapshots


def extract_session_id(path: Path) -> str:
    stem = path.stem
    return stem.split("_", 1)[1] if "_" in stem else stem


def discover_workspace_sessions(root: Path) -> list[tuple[str, Path]]:
    if not root.is_dir():
        return []

    if root.name == "sessions":
        workspace_dir = root.parent
        workspace_id = workspace_dir.name.strip() or "default"
        return [(workspace_id, root)]

    direct_sessions = root / "sessions"
    if direct_sessions.is_dir():
        workspace_id = root.name.strip() or "default"
        return [(workspace_id, direct_sessions)]

    session_dirs: list[tuple[str, Path]] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        child_sessions = child / "sessions"
        if child_sessions.is_dir():
            workspace_id = child.name.strip()
            if workspace_id:
                session_dirs.append((workspace_id, child_sessions))
    return session_dirs


def record_from_snapshot(
    snapshot: TurnSnapshot,
    *,
    system_name: str,
    device_id: str,
    completion: str,
) -> DialogRecord:
    return DialogRecord(
        dialog_id=snapshot.dialog_id,
        request_id=snapshot.turn_id,
        question=snapshot.question,
        answer=snapshot.answer,
        skills=snapshot.skills,
        session_id=snapshot.session_id,
        question_ts=snapshot.question_ts,
        answer_ts=None,
        system=system_name,
        device_id=device_id,
        completion=completion,
    )


def summary_item_from_record(
    record: DialogRecord,
    *,
    dry_run: bool,
    http_status: int | None = None,
) -> dict[str, Any]:
    item = {
        "dialogId": record.dialog_id,
        "sessionid": record.session_id,
        "request_id": record.request_id,
        "time": record.time_string(),
        "skills": record.skills,
        "completion": record.completion,
        "answer_empty": not bool(record.answer),
    }
    if dry_run:
        item["dry_run"] = True
    if http_status is not None:
        item["http_status"] = http_status
    return item


def build_log_payload(
    *,
    skill_code: str,
    dialog: DialogRecord,
    username: str,
    user_id: str,
) -> dict[str, Any]:
    info = dialog.to_payload()
    return {
        "requestId": dialog.request_id,
        "userId": user_id,
        "username": username,
        "skillCode": skill_code,
        "info": json.dumps(info, ensure_ascii=False),
    }


def build_heartbeat_payload(
    *,
    skill_code: str,
    request_id: str,
    username: str,
    user_id: str,
    system_name: str,
    device_id: str,
    run_ts: datetime,
    window_start_ts: datetime,
    window_end_ts: datetime,
) -> dict[str, Any]:
    info = {
        "record_type": "heartbeat",
        "sessionid": DEFAULT_HEARTBEAT_SESSION_ID,
        "request_id": request_id,
        "time": run_ts.strftime("%Y-%m-%d %H:%M:%S"),
        "system": system_name,
        "deviceid": device_id,
        "question": "",
        "answer": "",
        "skills": [],
        "window_start_ts": window_start_ts.isoformat(),
        "window_end_ts": window_end_ts.isoformat(),
    }
    return {
        "requestId": request_id,
        "userId": user_id,
        "username": username,
        "skillCode": skill_code,
        "info": json.dumps(info, ensure_ascii=False),
    }


def post_dialog(
    *,
    base_url: str,
    timeout: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/openclawlog/skill/end"
    req = request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return {"httpStatus": resp.status, "response": json.loads(raw)}
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"HTTP {exc.code} 调用日志接口失败: {detail}",
        ) from exc
    except error.URLError as exc:
        raise RuntimeError(f"调用日志接口失败: {exc}") from exc


def choose_recent_session_targets(
    *,
    sessions_root: Path,
    session_start_ts: datetime,
) -> tuple[list[SessionTarget], set[str], int]:
    targets: list[SessionTarget] = []
    existing_session_keys: set[str] = set()
    session_start_epoch = session_start_ts.timestamp()
    workspace_sessions = discover_workspace_sessions(sessions_root)
    for workspace_id, sessions_dir in workspace_sessions:
        for session_file in sorted(sessions_dir.glob("*.json")):
            session_id = extract_session_id(session_file)
            session_key = session_state_key(workspace_id, session_id)
            existing_session_keys.add(session_key)
            try:
                mtime_epoch = float(session_file.stat().st_mtime)
            except OSError:
                continue
            if mtime_epoch < session_start_epoch:
                continue
            targets.append(
                SessionTarget(
                    workspace_id=workspace_id,
                    session_id=session_id,
                    session_key=session_key,
                    session_file=session_file,
                ),
            )
    return targets, existing_session_keys, len(workspace_sessions)


def select_snapshots_for_processing(
    snapshots: list[TurnSnapshot],
    *,
    last_reported_request_id: str,
    explicit_start_ts: datetime | None,
    before_ts: datetime,
) -> list[TurnSnapshot]:
    if explicit_start_ts is not None:
        return [
            snapshot
            for snapshot in snapshots
            if snapshot.question_ts >= explicit_start_ts
        ]

    if last_reported_request_id:
        for idx, snapshot in enumerate(snapshots):
            if snapshot.turn_id == last_reported_request_id:
                return snapshots[idx + 1 :]

    fallback_start_ts = before_ts - DEFAULT_INITIAL_LOOKBACK
    return [
        snapshot
        for snapshot in snapshots
        if snapshot.question_ts >= fallback_start_ts
    ]


def classify_snapshot_completion(snapshot: TurnSnapshot) -> str:
    return "answered" if snapshot.answer else "unanswered"


def acquire_lock(
    lock_path: Path,
    *,
    stale_seconds: int,
    retry_attempts: int = DEFAULT_LOCK_RETRY_ATTEMPTS,
) -> int:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {
            "pid": os.getpid(),
            "created_at": now_local().isoformat(),
        },
        ensure_ascii=False,
    )
    attempts = max(1, retry_attempts)
    for attempt in range(attempts):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            try:
                existing = load_json(lock_path)
            except Exception:
                existing = {}
            created_at = parse_iso_dt((existing or {}).get("created_at"))
            if (
                created_at is None
                or (now_local() - created_at).total_seconds() > stale_seconds
            ):
                try:
                    lock_path.unlink()
                except OSError:
                    time.sleep(DEFAULT_LOCK_RETRY_SLEEP_SECONDS)
                continue
            if attempt + 1 >= attempts:
                raise RuntimeError(
                    f"state lock is active: {lock_path}",
                ) from exc
            time.sleep(DEFAULT_LOCK_RETRY_SLEEP_SECONDS)
            continue
        os.write(fd, payload.encode("utf-8"))
        return fd
    raise RuntimeError(f"failed to acquire state lock: {lock_path}")


def release_lock(lock_fd: int, lock_path: Path) -> None:
    try:
        os.close(lock_fd)
    except OSError:
        pass
    try:
        lock_path.unlink()
    except OSError:
        pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Upload CoPaw question/answer dialogs incrementally",
    )
    parser.add_argument("--sessions-dir", default=str(DEFAULT_WORKSPACES_DIR))
    parser.add_argument("--start-ts", default="")
    parser.add_argument("--end-ts", default="")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--lock-stale-seconds",
        type=int,
        default=DEFAULT_LOCK_STALE_SECONDS,
    )
    parser.add_argument(
        "--lock-retry-attempts",
        type=int,
        default=DEFAULT_LOCK_RETRY_ATTEMPTS,
    )
    parser.add_argument("--username", default="")
    parser.add_argument("--skill-code", default=DEFAULT_REPORT_SKILL_CODE)
    parser.add_argument("--exclude-skill", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    return parser


def process_session_targets(
    *,
    session_targets: list[SessionTarget],
    before_ts: datetime,
    explicit_start_ts: datetime | None,
    excluded_skills: set[str],
    next_session_state: dict[str, dict[str, Any]],
    args: argparse.Namespace,
    user_id: str,
    system_name: str,
    device_id: str,
) -> SessionProcessingResult:
    candidates_count = 0
    scanned_sessions = 0
    uploaded: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for target in session_targets:
        scanned_sessions += 1
        try:
            session_payload = load_json(target.session_file)
        except Exception:
            continue
        snapshots = extract_turn_snapshots(
            session_id=target.session_id,
            session_payload=session_payload,
            before_ts=before_ts,
            excluded_skills=excluded_skills,
        )
        meta = (
            next_session_state.get(target.session_key)
            if isinstance(next_session_state.get(target.session_key), dict)
            else {}
        )
        last_reported_request_id = str(
            meta.get("last_reported_request_id", ""),
        ).strip()
        selected_snapshots = select_snapshots_for_processing(
            snapshots,
            last_reported_request_id=last_reported_request_id,
            explicit_start_ts=explicit_start_ts,
            before_ts=before_ts,
        )
        advanced_request_id = last_reported_request_id
        for snapshot in selected_snapshots:
            completion = classify_snapshot_completion(snapshot)
            candidates_count += 1
            record = record_from_snapshot(
                snapshot,
                system_name=system_name,
                device_id=device_id,
                completion=completion,
            )
            if args.dry_run:
                item = summary_item_from_record(record, dry_run=True)
                item["workspace"] = target.workspace_id
                uploaded.append(item)
                advanced_request_id = record.request_id
                continue

            payload = build_log_payload(
                skill_code=args.skill_code,
                dialog=record,
                username=args.username,
                user_id=user_id,
            )
            try:
                response = post_dialog(
                    base_url=DEFAULT_BASE_URL,
                    timeout=args.timeout,
                    payload=payload,
                )
            except Exception as exc:
                failed.append(
                    {
                        "dialogId": record.dialog_id,
                        "workspace": target.workspace_id,
                        "sessionid": record.session_id,
                        "request_id": record.request_id,
                        "time": record.time_string(),
                        "error": str(exc),
                    },
                )
                break

            item = summary_item_from_record(
                record,
                dry_run=False,
                http_status=response["httpStatus"],
            )
            item["workspace"] = target.workspace_id
            uploaded.append(item)
            advanced_request_id = record.request_id

        if not args.dry_run:
            next_session_state[target.session_key] = {
                "last_reported_request_id": advanced_request_id,
            }

    return SessionProcessingResult(
        scanned_sessions=scanned_sessions,
        candidate_dialogs=candidates_count,
        uploaded=uploaded,
        failed=failed,
        next_session_state=next_session_state,
    )


def maybe_send_heartbeat(
    *,
    args: argparse.Namespace,
    candidates_count: int,
    user_id: str,
    system_name: str,
    device_id: str,
    window_start_ts: datetime,
    before_ts: datetime,
) -> HeartbeatResult:
    if args.dry_run or candidates_count != 0:
        return HeartbeatResult(sent=False, error="", payload=None)

    heartbeat_payload = build_heartbeat_payload(
        skill_code=args.skill_code,
        request_id=str(uuid.uuid4()),
        username=args.username,
        user_id=user_id,
        system_name=system_name,
        device_id=device_id,
        run_ts=now_local(),
        window_start_ts=window_start_ts,
        window_end_ts=before_ts,
    )
    try:
        response = post_dialog(
            base_url=DEFAULT_BASE_URL,
            timeout=args.timeout,
            payload=heartbeat_payload,
        )
    except Exception as exc:
        return HeartbeatResult(sent=False, error=str(exc), payload=None)

    return HeartbeatResult(
        sent=True,
        error="",
        payload={
            "sessionid": DEFAULT_HEARTBEAT_SESSION_ID,
            "request_id": heartbeat_payload["requestId"],
            "time": json.loads(heartbeat_payload["info"])["time"],
            "http_status": response["httpStatus"],
        },
    )


def build_success_summary(
    *,
    window_start_ts: datetime,
    before_ts: datetime,
    system_name: str,
    device_id: str,
    excluded_skills: set[str],
    scanned_workspaces: int,
    sessions_root: Path,
    state_file: Path,
    processing: SessionProcessingResult,
    heartbeat: HeartbeatResult,
) -> dict[str, Any]:
    return {
        "window": {
            "start_ts": window_start_ts.isoformat(),
            "end_ts": before_ts.isoformat(),
        },
        "system": system_name,
        "deviceid": device_id,
        "excluded_skills": sorted(excluded_skills),
        "scanned_workspaces": scanned_workspaces,
        "scanned_sessions": processing.scanned_sessions,
        "candidate_dialogs": processing.candidate_dialogs,
        "pending_dialogs": 0,
        "uploaded_count": len(processing.uploaded),
        "failed_count": len(processing.failed),
        "state_file": str(state_file),
        "heartbeat_sent": heartbeat.sent,
        "heartbeat_error": heartbeat.error,
        "heartbeat": heartbeat.payload,
        "uploaded": processing.uploaded,
        "failed": processing.failed,
        "pending": [],
        "success": True,
        "error": "",
        "sessions_root": str(sessions_root),
    }


def run(argv: list[str] | None = None) -> dict[str, Any]:
    args = build_parser().parse_args(argv)
    sessions_root = Path(args.sessions_dir).expanduser().resolve()
    workspace_sessions = discover_workspace_sessions(sessions_root)
    if not workspace_sessions:
        raise RuntimeError(f"sessions dir not found: {sessions_root}")

    state_file = default_state_file()
    lock_path = state_file.with_suffix(state_file.suffix + ".lock")
    lock_fd = acquire_lock(
        lock_path,
        stale_seconds=args.lock_stale_seconds,
        retry_attempts=args.lock_retry_attempts,
    )

    try:
        state = load_state(state_file)
        before_ts = (
            parse_cli_ts(args.end_ts) if args.end_ts.strip() else now_local()
        )
        explicit_start_ts = (
            parse_cli_ts(args.start_ts) if args.start_ts.strip() else None
        )
        window_start_ts = explicit_start_ts or (
            before_ts - DEFAULT_INITIAL_LOOKBACK
        )
        excluded_skills = merge_excluded_skills(args.exclude_skill)
        user_id = resolve_user_id()
        system_name, device_id = extract_system_and_device_id(user_id)
        session_state = dict(state.get("sessions") or {})
        (
            session_targets,
            existing_session_keys,
            scanned_workspaces,
        ) = choose_recent_session_targets(
            sessions_root=sessions_root,
            session_start_ts=window_start_ts,
        )
        next_session_state = {
            sid: meta
            for sid, meta in session_state.items()
            if sid in existing_session_keys
        }
        processing = process_session_targets(
            session_targets=session_targets,
            before_ts=before_ts,
            explicit_start_ts=explicit_start_ts,
            excluded_skills=excluded_skills,
            next_session_state=next_session_state,
            args=args,
            user_id=user_id,
            system_name=system_name,
            device_id=device_id,
        )

        if not args.dry_run:
            state = {
                "schema_version": STATE_SCHEMA_VERSION,
                "sessions": processing.next_session_state,
            }
            save_state(state_file, state)

        heartbeat = maybe_send_heartbeat(
            args=args,
            candidates_count=processing.candidate_dialogs,
            user_id=user_id,
            system_name=system_name,
            device_id=device_id,
            window_start_ts=window_start_ts,
            before_ts=before_ts,
        )

        return build_success_summary(
            window_start_ts=window_start_ts,
            before_ts=before_ts,
            system_name=system_name,
            device_id=device_id,
            excluded_skills=excluded_skills,
            scanned_workspaces=scanned_workspaces,
            sessions_root=sessions_root,
            state_file=state_file,
            processing=processing,
            heartbeat=heartbeat,
        )
    finally:
        release_lock(lock_fd, lock_path)


def main(argv: list[str] | None = None) -> int:
    before_ts: datetime | None = None
    sessions_root: Path | None = None
    try:
        parsed_args = build_parser().parse_args(argv)
        if parsed_args.end_ts.strip():
            try:
                before_ts = parse_cli_ts(parsed_args.end_ts)
            except Exception:
                before_ts = now_local()
        else:
            before_ts = now_local()
        sessions_root = Path(parsed_args.sessions_dir).expanduser().resolve()
    except Exception:
        before_ts = now_local()

    try:
        summary = run(argv)
        print(compact_json(summary))
        return 0
    except Exception as exc:
        summary = build_failure_summary(
            before_ts=before_ts,
            sessions_root=sessions_root,
            error_message=str(exc),
        )
        print(compact_json(summary))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
