from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any


def bind_runtime_symbols(symbols: dict[str, object]) -> None:
    if not isinstance(symbols, dict):
        return
    target = globals()
    module_name = str(target.get("__name__") or "")
    for key, value in symbols.items():
        if str(key).startswith("__"):
            continue
        current = target.get(key)
        if callable(current) and getattr(current, "__module__", "") == module_name:
            continue
        target[key] = value


DEFAULT_ASSIGNMENT_CONCURRENCY_LIMIT = 5
DEFAULT_ASSIGNMENT_EXECUTION_PROVIDER = "codex"
DEFAULT_ASSIGNMENT_EXECUTION_REFRESH_MODE = "event_stream"
DEFAULT_ASSIGNMENT_EXECUTION_POLL_INTERVAL_MS = 450
DEFAULT_ASSIGNMENT_EXECUTION_TIMEOUT_S = 1200
DEFAULT_ASSIGNMENT_FINAL_RESULT_EXIT_GRACE_SECONDS = 15
DEFAULT_ASSIGNMENT_STALE_RUN_GRACE_SECONDS = 15
DEFAULT_ASSIGNMENT_EVENT_STREAM_RETRY_MS = 1500
DEFAULT_ASSIGNMENT_EVENT_STREAM_KEEPALIVE_S = 15
DEFAULT_ASSIGNMENT_EVENT_HISTORY_LIMIT = 512
LEGACY_ASSIGNMENT_CODEX_COMMAND_TEMPLATE = (
    '"{codex_path}" exec --json --skip-git-repo-check --sandbox workspace-write '
    '--add-dir "{workspace_path}" -C "{workspace_path}" -'
)
DEFAULT_ASSIGNMENT_CODEX_COMMAND_TEMPLATE = (
    '"{codex_path}" exec --dangerously-bypass-approvals-and-sandbox --json --skip-git-repo-check '
    '--add-dir "{workspace_path}" -C "{workspace_path}" -'
)
ASSIGNMENT_REVIEW_MODES = {"none", "partial", "full"}
ASSIGNMENT_NODE_STATUSES = {"pending", "ready", "running", "succeeded", "failed", "blocked"}
ASSIGNMENT_NONTERMINAL_STATUSES = {"pending", "ready", "blocked"}
ASSIGNMENT_SCHEDULER_STATES = {"idle", "running", "pause_pending", "paused"}
ASSIGNMENT_DELIVERY_MODES = {"none", "specified"}
ASSIGNMENT_ARTIFACT_DELIVERY_STATUSES = {"pending", "delivered"}
ASSIGNMENT_EXECUTION_PROVIDERS = {DEFAULT_ASSIGNMENT_EXECUTION_PROVIDER}
ASSIGNMENT_RUN_STATUSES = {"starting", "running", "succeeded", "failed", "cancelled"}
ASSIGNMENT_TEST_GRAPH_SOURCE = "assignment-prototype-test-data"
ASSIGNMENT_TEST_GRAPH_EXTERNAL_REQUEST_ID = "task-center-prototype-v1"
ASSIGNMENT_TEST_GRAPH_NAME = "任务中心原型测试图"
ASSIGNMENT_TEST_GRAPH_SUMMARY = "基于任务中心参考图生成的测试任务图"
ASSIGNMENT_TEST_GRAPH_CREATED_AT = "2026-03-14T09:40:00+08:00"
ASSIGNMENT_TEST_GRAPH_UPDATED_AT = "2026-03-14T12:20:30+08:00"

_ASSIGNMENT_ACTIVE_RUN_LOCK = threading.Lock()
_ASSIGNMENT_ACTIVE_RUN_PROCESSES: dict[str, subprocess.Popen[str]] = {}
_ASSIGNMENT_EVENT_CONDITION = threading.Condition()
_ASSIGNMENT_EVENT_SEQ = 0
_ASSIGNMENT_EVENT_HISTORY: deque[dict[str, Any]] = deque(maxlen=DEFAULT_ASSIGNMENT_EVENT_HISTORY_LIMIT)


def _assignment_execution_timeout_s() -> int:
    raw = str(os.getenv("WORKFLOW_ASSIGNMENT_EXECUTION_TIMEOUT_S") or "").strip()
    if raw:
        try:
            return max(300, int(raw))
        except Exception:
            pass
    return max(300, int(DEFAULT_ASSIGNMENT_EXECUTION_TIMEOUT_S))


def _assignment_final_result_exit_grace_seconds() -> int:
    raw = str(os.getenv("WORKFLOW_ASSIGNMENT_FINAL_RESULT_EXIT_GRACE_SECONDS") or "").strip()
    if raw:
        try:
            return max(5, int(raw))
        except Exception:
            pass
    return max(5, int(DEFAULT_ASSIGNMENT_FINAL_RESULT_EXIT_GRACE_SECONDS))


class AssignmentCenterError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        message: str,
        code: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.extra = dict(extra or {})


def assignment_ticket_id() -> str:
    ts = now_local()
    return f"asg-{date_key(ts)}-{ts.strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}"


def assignment_node_id() -> str:
    ts = now_local()
    return f"node-{date_key(ts)}-{ts.strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}"


def assignment_audit_id() -> str:
    ts = now_local()
    return f"aaud-{date_key(ts)}-{ts.strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}"


def assignment_run_id() -> str:
    ts = now_local()
    return f"arun-{date_key(ts)}-{ts.strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}"


def assignment_execution_refresh_mode() -> str:
    return str(DEFAULT_ASSIGNMENT_EXECUTION_REFRESH_MODE or "event_stream").strip().lower() or "event_stream"


def assignment_event_stream_retry_ms() -> int:
    return max(500, int(DEFAULT_ASSIGNMENT_EVENT_STREAM_RETRY_MS))


def assignment_event_stream_keepalive_s() -> int:
    return max(5, int(DEFAULT_ASSIGNMENT_EVENT_STREAM_KEEPALIVE_S))


def assignment_current_event_seq() -> int:
    with _ASSIGNMENT_EVENT_CONDITION:
        return int(_ASSIGNMENT_EVENT_SEQ)


def _assignment_publish_runtime_event(
    *,
    ticket_id: str,
    kind: str,
    node_id: str = "",
    run_id: str = "",
    status: str = "",
    latest_event: str = "",
    latest_event_at: str = "",
    scheduler_state: str = "",
    event_type: str = "",
) -> dict[str, Any]:
    ticket_text = str(ticket_id or "").strip()
    if not ticket_text:
        return {}
    payload = {
        "ticket_id": ticket_text,
        "kind": str(kind or "").strip().lower() or "snapshot",
        "node_id": str(node_id or "").strip(),
        "run_id": str(run_id or "").strip(),
        "status": str(status or "").strip().lower(),
        "latest_event": _short_assignment_text(str(latest_event or "").strip(), 1000),
        "latest_event_at": str(latest_event_at or "").strip(),
        "scheduler_state": str(scheduler_state or "").strip().lower(),
        "event_type": str(event_type or "").strip().lower(),
        "emitted_at": iso_ts(now_local()),
    }
    with _ASSIGNMENT_EVENT_CONDITION:
        global _ASSIGNMENT_EVENT_SEQ
        _ASSIGNMENT_EVENT_SEQ += 1
        payload["seq"] = int(_ASSIGNMENT_EVENT_SEQ)
        _ASSIGNMENT_EVENT_HISTORY.append(dict(payload))
        _ASSIGNMENT_EVENT_CONDITION.notify_all()
    return dict(payload)


def assignment_wait_runtime_events(after_seq: int, *, timeout_s: float | int | None = None) -> dict[str, Any]:
    wait_s = max(1.0, float(timeout_s or assignment_event_stream_keepalive_s()))
    with _ASSIGNMENT_EVENT_CONDITION:
        target_seq = max(0, int(after_seq or 0))
        if _ASSIGNMENT_EVENT_SEQ <= target_seq:
            _ASSIGNMENT_EVENT_CONDITION.wait(wait_s)
        current_seq = int(_ASSIGNMENT_EVENT_SEQ)
        history = [dict(item) for item in list(_ASSIGNMENT_EVENT_HISTORY)]
    if current_seq <= target_seq:
        return {
            "current_seq": current_seq,
            "reset_required": False,
            "events": [],
        }
    if history and target_seq < (int(history[0].get("seq") or 0) - 1):
        return {
            "current_seq": current_seq,
            "reset_required": True,
            "events": history,
        }
    return {
        "current_seq": current_seq,
        "reset_required": False,
        "events": [item for item in history if int(item.get("seq") or 0) > target_seq],
    }


def _db_ref(audit_id: str) -> str:
    return f"state/workflow.db#assignment_audit_log/{audit_id}"


def _path_for_ui(root: Path, path: Path | str) -> str:
    raw = Path(path).resolve(strict=False)
    try:
        return raw.relative_to(root.resolve(strict=False)).as_posix()
    except Exception:
        return raw.as_posix()


def _row_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    return {name: row[name] for name in row.keys()}


def _json_load(raw: object, fallback: Any) -> Any:
    if raw in (None, ""):
        return fallback
    try:
        payload = json.loads(str(raw))
    except Exception:
        return fallback
    return payload


def _normalize_text(raw: Any, *, field: str, required: bool = False, max_len: int = 5000) -> str:
    text = str(raw or "").strip()
    if required and not text:
        raise AssignmentCenterError(400, f"{field} required", f"{field}_required")
    if len(text) > max_len:
        raise AssignmentCenterError(
            400,
            f"{field} too long",
            f"{field}_too_long",
            {"max_length": max_len},
        )
    return text


def _normalize_positive_int(
    raw: Any,
    *,
    field: str,
    default: int,
    minimum: int = 1,
    maximum: int = 64,
) -> int:
    if raw in (None, ""):
        value = int(default)
    else:
        try:
            value = int(raw)
        except Exception as exc:
            raise AssignmentCenterError(400, f"{field} invalid", f"{field}_invalid") from exc
    if value < minimum or value > maximum:
        raise AssignmentCenterError(
            400,
            f"{field} out of range",
            f"{field}_out_of_range",
            {"minimum": minimum, "maximum": maximum},
        )
    return value


def normalize_assignment_priority(raw: Any, *, required: bool = True) -> int:
    if raw in (None, ""):
        if required:
            raise AssignmentCenterError(400, "priority required", "priority_required")
        return 1
    if isinstance(raw, (int, float)):
        value = int(raw)
    else:
        text = str(raw or "").strip().upper()
        if not text:
            if required:
                raise AssignmentCenterError(400, "priority required", "priority_required")
            return 1
        if text.startswith("P") and len(text) == 2 and text[1].isdigit():
            value = int(text[1])
        else:
            try:
                value = int(text)
            except Exception as exc:
                raise AssignmentCenterError(
                    400,
                    "priority only allows P0/P1/P2/P3 or 0/1/2/3",
                    "priority_invalid",
                ) from exc
    if value not in (0, 1, 2, 3):
        raise AssignmentCenterError(
            400,
            "priority only allows P0/P1/P2/P3 or 0/1/2/3",
            "priority_invalid",
        )
    return value


def assignment_priority_label(value: Any) -> str:
    try:
        num = int(value)
    except Exception:
        num = 1
    if num not in (0, 1, 2, 3):
        num = 1
    return f"P{num}"


def _normalize_delivery_mode(raw: Any) -> str:
    value = str(raw or "none").strip().lower() or "none"
    if value not in ASSIGNMENT_DELIVERY_MODES:
        raise AssignmentCenterError(
            400,
            "delivery_mode invalid",
            "delivery_mode_invalid",
            {"allowed": sorted(ASSIGNMENT_DELIVERY_MODES)},
        )
    return value


def _delivery_mode_text(value: Any) -> str:
    return "指定交付对象" if str(value or "").strip().lower() == "specified" else "默认交付给当前 agent"


def _artifact_delivery_status_text(value: Any) -> str:
    return "已交付" if str(value or "").strip().lower() == "delivered" else "待交付"


def _normalize_artifact_delivery_status(raw: Any) -> str:
    value = str(raw or "pending").strip().lower() or "pending"
    if value not in ASSIGNMENT_ARTIFACT_DELIVERY_STATUSES:
        raise AssignmentCenterError(
            400,
            "artifact_delivery_status invalid",
            "artifact_delivery_status_invalid",
            {"allowed": sorted(ASSIGNMENT_ARTIFACT_DELIVERY_STATUSES)},
        )
    return value


def _normalize_review_mode(raw: Any) -> str:
    value = str(raw or "none").strip().lower() or "none"
    if value not in ASSIGNMENT_REVIEW_MODES:
        raise AssignmentCenterError(
            400,
            "review_mode invalid",
            "review_mode_invalid",
            {"allowed": sorted(ASSIGNMENT_REVIEW_MODES)},
        )
    if value != "none":
        raise AssignmentCenterError(
            409,
            "review_mode not supported in phase1",
            "not_supported_in_phase1",
            {"review_mode": value},
        )
    return value


def _normalize_execution_provider(raw: Any) -> str:
    value = str(raw or DEFAULT_ASSIGNMENT_EXECUTION_PROVIDER).strip().lower() or DEFAULT_ASSIGNMENT_EXECUTION_PROVIDER
    if value not in ASSIGNMENT_EXECUTION_PROVIDERS:
        raise AssignmentCenterError(
            409,
            "execution provider not supported in phase1",
            "assignment_execution_provider_not_supported",
            {"provider": value, "allowed": sorted(ASSIGNMENT_EXECUTION_PROVIDERS)},
        )
    return value


def _normalize_run_status(raw: Any) -> str:
    value = str(raw or "starting").strip().lower() or "starting"
    if value not in ASSIGNMENT_RUN_STATUSES:
        raise AssignmentCenterError(
            400,
            "assignment run status invalid",
            "assignment_run_status_invalid",
            {"allowed": sorted(ASSIGNMENT_RUN_STATUSES)},
        )
    return value


def _default_codex_command_path() -> str:
    found = shutil.which("codex.cmd") if os.name == "nt" else None
    if not found:
        found = shutil.which("codex")
    return str(found or "codex").strip()


def _normalize_codex_command_path(raw: Any) -> str:
    text = str(raw or _default_codex_command_path()).strip() or _default_codex_command_path()
    if os.name != "nt":
        return text
    lowered = text.lower()
    if lowered.endswith(".ps1"):
        cmd_path = text[:-4] + ".cmd"
        if Path(cmd_path).exists():
            return cmd_path
    resolved = shutil.which(text)
    if resolved:
        return str(resolved).strip() or text
    if not Path(text).suffix:
        for suffix in (".cmd", ".bat", ".exe"):
            candidate = text + suffix
            if Path(candidate).exists():
                return candidate
    return text


def _default_assignment_command_template(provider: str) -> str:
    provider_text = _normalize_execution_provider(provider)
    if provider_text == DEFAULT_ASSIGNMENT_EXECUTION_PROVIDER:
        return DEFAULT_ASSIGNMENT_CODEX_COMMAND_TEMPLATE
    return DEFAULT_ASSIGNMENT_CODEX_COMMAND_TEMPLATE


def _normalize_assignment_command_template_value(value: Any, provider: str) -> str:
    text = str(value or "").strip()
    default_template = _default_assignment_command_template(provider)
    if not text:
        return default_template
    if text == LEGACY_ASSIGNMENT_CODEX_COMMAND_TEMPLATE:
        return default_template
    return text


def _normalize_status(raw: Any, *, field: str = "status") -> str:
    value = str(raw or "").strip().lower()
    if value not in ASSIGNMENT_NODE_STATUSES:
        raise AssignmentCenterError(
            400,
            f"{field} invalid",
            f"{field}_invalid",
            {"allowed": sorted(ASSIGNMENT_NODE_STATUSES)},
        )
    return value


def _normalize_scheduler_state(raw: Any) -> str:
    value = str(raw or "").strip().lower()
    if value not in ASSIGNMENT_SCHEDULER_STATES:
        raise AssignmentCenterError(
            400,
            "scheduler_state invalid",
            "scheduler_state_invalid",
            {"allowed": sorted(ASSIGNMENT_SCHEDULER_STATES)},
        )
    return value


def _normalize_assignment_test_flag(raw: Any, *, default: bool = False) -> bool:
    if raw in (None, ""):
        return bool(default)
    try:
        return bool(parse_bool_flag(raw, default=default))
    except Exception:
        return bool(default)


def _row_is_test_data(row: sqlite3.Row | dict[str, Any] | None) -> bool:
    if row is None:
        return False
    try:
        raw = row["is_test_data"]  # type: ignore[index]
    except Exception:
        raw = row.get("is_test_data") if isinstance(row, dict) else 0
    return _normalize_assignment_test_flag(raw, default=False)


def _scheduler_state_text(value: str) -> str:
    key = str(value or "").strip().lower()
    if key == "running":
        return "运行中"
    if key == "pause_pending":
        return "暂停中"
    if key == "paused":
        return "已暂停"
    return "未启动"


def _node_status_text(value: str) -> str:
    key = str(value or "").strip().lower()
    mapping = {
        "pending": "待开始",
        "ready": "待开始",
        "starting": "启动中",
        "running": "进行中",
        "succeeded": "已完成",
        "failed": "失败",
        "blocked": "阻塞",
        "cancelled": "已取消",
    }
    return mapping.get(key, key or "-")


def _safe_json_list(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return list(raw)
    if raw in (None, ""):
        return []
    payload = _json_load(raw, [])
    return payload if isinstance(payload, list) else []


def _dedupe_tokens(values: list[Any], *, allow_empty: bool = False) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        token = safe_token(str(raw or ""), "", 160)
        if not token and not allow_empty:
            continue
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def _default_assignment_operator(raw: Any) -> str:
    return safe_token(str(raw or "web-user"), "web-user", 80)


def _ensure_graph_row(conn: sqlite3.Connection, ticket_id: str) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT
            ticket_id,graph_name,source_workflow,summary,review_mode,
            global_concurrency_limit,is_test_data,external_request_id,scheduler_state,pause_note,
            created_at,updated_at
        FROM assignment_graphs
        WHERE ticket_id=?
        LIMIT 1
        """,
        (ticket_id,),
    ).fetchone()
    if row is None:
        raise AssignmentCenterError(
            404,
            "assignment graph not found",
            "assignment_graph_not_found",
            {"ticket_id": ticket_id},
        )
    return row


def _ensure_graph_row_visible(
    conn: sqlite3.Connection,
    ticket_id: str,
    *,
    include_test_data: bool,
) -> sqlite3.Row:
    row = _ensure_graph_row(conn, ticket_id)
    if _row_is_test_data(row) and not include_test_data:
        raise AssignmentCenterError(
            404,
            "assignment graph not found",
            "assignment_graph_not_found",
            {"ticket_id": ticket_id},
        )
    return row


def _ensure_setting_row(
    conn: sqlite3.Connection,
    *,
    key: str,
    default_value: str,
    now_text: str,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO assignment_system_settings (
            setting_key,setting_value,updated_at
        ) VALUES (?,?,?)
        """,
        (key, default_value, now_text),
    )


def _get_assignment_setting_text(
    conn: sqlite3.Connection,
    *,
    key: str,
    default_value: str,
    now_text: str,
) -> tuple[str, str]:
    _ensure_setting_row(conn, key=key, default_value=default_value, now_text=now_text)
    row = conn.execute(
        """
        SELECT setting_value,updated_at
        FROM assignment_system_settings
        WHERE setting_key=?
        LIMIT 1
        """,
        (key,),
    ).fetchone()
    if row is None:
        return str(default_value or ""), now_text
    return str(row["setting_value"] or default_value or "").strip(), str(row["updated_at"] or now_text)


def _set_assignment_setting_text(
    conn: sqlite3.Connection,
    *,
    key: str,
    value: str,
    now_text: str,
) -> None:
    _ensure_setting_row(conn, key=key, default_value=value, now_text=now_text)
    conn.execute(
        """
        UPDATE assignment_system_settings
        SET setting_value=?,updated_at=?
        WHERE setting_key=?
        """,
        (str(value or ""), now_text, key),
    )


def _get_global_concurrency_limit(conn: sqlite3.Connection) -> tuple[int, str]:
    now_text = iso_ts(now_local())
    _ensure_setting_row(
        conn,
        key="global_concurrency_limit",
        default_value=str(DEFAULT_ASSIGNMENT_CONCURRENCY_LIMIT),
        now_text=now_text,
    )
    row = conn.execute(
        """
        SELECT setting_value,updated_at
        FROM assignment_system_settings
        WHERE setting_key='global_concurrency_limit'
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return DEFAULT_ASSIGNMENT_CONCURRENCY_LIMIT, now_text
    try:
        value = int(str(row["setting_value"] or DEFAULT_ASSIGNMENT_CONCURRENCY_LIMIT))
    except Exception:
        value = DEFAULT_ASSIGNMENT_CONCURRENCY_LIMIT
    if value < 1:
        value = DEFAULT_ASSIGNMENT_CONCURRENCY_LIMIT
    return value, str(row["updated_at"] or now_text)


def _assignment_execution_settings_from_conn(conn: sqlite3.Connection) -> dict[str, Any]:
    now_text = iso_ts(now_local())
    provider_text, provider_updated_at = _get_assignment_setting_text(
        conn,
        key="execution_provider",
        default_value=DEFAULT_ASSIGNMENT_EXECUTION_PROVIDER,
        now_text=now_text,
    )
    provider = _normalize_execution_provider(provider_text)
    codex_command_path, codex_path_updated_at = _get_assignment_setting_text(
        conn,
        key="codex_command_path",
        default_value=_default_codex_command_path(),
        now_text=now_text,
    )
    codex_command_path = _normalize_codex_command_path(codex_command_path)
    command_template, command_template_updated_at = _get_assignment_setting_text(
        conn,
        key="codex_command_template",
        default_value=_default_assignment_command_template(provider),
        now_text=now_text,
    )
    normalized_template = _normalize_assignment_command_template_value(command_template, provider)
    if normalized_template != str(command_template or "").strip():
        _set_assignment_setting_text(
            conn,
            key="codex_command_template",
            value=normalized_template,
            now_text=now_text,
        )
        command_template_updated_at = now_text
    command_template = normalized_template
    global_concurrency_limit, concurrency_updated_at = _get_global_concurrency_limit(conn)
    return {
        "execution_provider": provider,
        "codex_command_path": codex_command_path or _default_codex_command_path(),
        "command_template": command_template or _default_assignment_command_template(provider),
        "global_concurrency_limit": int(global_concurrency_limit),
        "updated_at": max(provider_updated_at, codex_path_updated_at, command_template_updated_at, concurrency_updated_at),
        "poll_mode": assignment_execution_refresh_mode(),
        "poll_interval_ms": DEFAULT_ASSIGNMENT_EXECUTION_POLL_INTERVAL_MS,
    }


def _ensure_assignment_support_tables(root: Path) -> None:
    from workflow_app.server.infra.db.migrations import ensure_tables as ensure_db_tables

    ensure_db_tables(
        root,
        default_agents_root=root.resolve(strict=False).as_posix(),
    )
    conn = connect_db(root)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS assignment_graphs (
                ticket_id TEXT PRIMARY KEY,
                graph_name TEXT NOT NULL DEFAULT '',
                source_workflow TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                review_mode TEXT NOT NULL DEFAULT 'none',
                global_concurrency_limit INTEGER NOT NULL DEFAULT 5,
                is_test_data INTEGER NOT NULL DEFAULT 0,
                external_request_id TEXT NOT NULL DEFAULT '',
                scheduler_state TEXT NOT NULL DEFAULT 'idle',
                pause_note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_assignment_graphs_source_request
            ON assignment_graphs(source_workflow,external_request_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_assignment_graphs_scheduler
            ON assignment_graphs(scheduler_state,updated_at DESC)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS assignment_nodes (
                node_id TEXT NOT NULL,
                ticket_id TEXT NOT NULL,
                node_name TEXT NOT NULL DEFAULT '',
                assigned_agent_id TEXT NOT NULL DEFAULT '',
                node_goal TEXT NOT NULL DEFAULT '',
                expected_artifact TEXT NOT NULL DEFAULT '',
                delivery_mode TEXT NOT NULL DEFAULT 'none',
                delivery_receiver_agent_id TEXT NOT NULL DEFAULT '',
                artifact_delivery_status TEXT NOT NULL DEFAULT 'pending',
                artifact_delivered_at TEXT NOT NULL DEFAULT '',
                artifact_paths_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'pending',
                priority INTEGER NOT NULL DEFAULT 1,
                completed_at TEXT NOT NULL DEFAULT '',
                success_reason TEXT NOT NULL DEFAULT '',
                result_ref TEXT NOT NULL DEFAULT '',
                failure_reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (ticket_id,node_id)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_assignment_nodes_ticket_created
            ON assignment_nodes(ticket_id,created_at,node_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_assignment_nodes_ticket_status
            ON assignment_nodes(ticket_id,status,updated_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_assignment_nodes_status
            ON assignment_nodes(status,updated_at DESC)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS assignment_edges (
                edge_id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id TEXT NOT NULL,
                from_node_id TEXT NOT NULL,
                to_node_id TEXT NOT NULL,
                edge_kind TEXT NOT NULL DEFAULT 'depends_on',
                created_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_assignment_edges_unique
            ON assignment_edges(ticket_id,from_node_id,to_node_id,edge_kind)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_assignment_edges_ticket_to
            ON assignment_edges(ticket_id,to_node_id,from_node_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_assignment_edges_ticket_from
            ON assignment_edges(ticket_id,from_node_id,to_node_id)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS assignment_audit_log (
                audit_id TEXT PRIMARY KEY,
                ticket_id TEXT NOT NULL DEFAULT '',
                node_id TEXT NOT NULL DEFAULT '',
                action TEXT NOT NULL DEFAULT '',
                operator TEXT NOT NULL DEFAULT '',
                reason TEXT NOT NULL DEFAULT '',
                target_status TEXT NOT NULL DEFAULT '',
                detail_json TEXT NOT NULL DEFAULT '{}',
                ref TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_assignment_audit_ticket_time
            ON assignment_audit_log(ticket_id,created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_assignment_audit_ticket_node_time
            ON assignment_audit_log(ticket_id,node_id,created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS assignment_execution_runs (
                run_id TEXT PRIMARY KEY,
                ticket_id TEXT NOT NULL DEFAULT '',
                node_id TEXT NOT NULL DEFAULT '',
                provider TEXT NOT NULL DEFAULT '',
                workspace_path TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'starting',
                command_summary TEXT NOT NULL DEFAULT '',
                prompt_ref TEXT NOT NULL DEFAULT '',
                stdout_ref TEXT NOT NULL DEFAULT '',
                stderr_ref TEXT NOT NULL DEFAULT '',
                result_ref TEXT NOT NULL DEFAULT '',
                latest_event TEXT NOT NULL DEFAULT '',
                latest_event_at TEXT NOT NULL DEFAULT '',
                exit_code INTEGER NOT NULL DEFAULT 0,
                started_at TEXT NOT NULL DEFAULT '',
                finished_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                provider_pid INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_assignment_runs_ticket_node_created
            ON assignment_execution_runs(ticket_id,node_id,created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_assignment_runs_status_created
            ON assignment_execution_runs(status,created_at DESC)
            """
        )
        conn.commit()
    finally:
        conn.close()


def get_assignment_concurrency_settings(root: Path) -> dict[str, Any]:
    _ensure_assignment_support_tables(root)
    conn = connect_db(root)
    try:
        limit, updated_at = _get_global_concurrency_limit(conn)
        conn.commit()
    finally:
        conn.close()
    return {
        "global_concurrency_limit": int(limit),
        "updated_at": updated_at,
    }


def get_assignment_execution_settings(root: Path) -> dict[str, Any]:
    _ensure_assignment_support_tables(root)
    conn = connect_db(root)
    try:
        payload = _assignment_execution_settings_from_conn(conn)
        conn.commit()
    finally:
        conn.close()
    return payload


def set_assignment_concurrency_settings(
    root: Path,
    *,
    global_concurrency_limit: Any,
    operator: str,
) -> dict[str, Any]:
    _ensure_assignment_support_tables(root)
    now_text = iso_ts(now_local())
    next_limit = _normalize_positive_int(
        global_concurrency_limit,
        field="global_concurrency_limit",
        default=DEFAULT_ASSIGNMENT_CONCURRENCY_LIMIT,
        minimum=1,
        maximum=64,
    )
    operator_text = _default_assignment_operator(operator)
    conn = connect_db(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_setting_row(
            conn,
            key="global_concurrency_limit",
            default_value=str(DEFAULT_ASSIGNMENT_CONCURRENCY_LIMIT),
            now_text=now_text,
        )
        conn.execute(
            """
            UPDATE assignment_system_settings
            SET setting_value=?,updated_at=?
            WHERE setting_key='global_concurrency_limit'
            """,
            (str(next_limit), now_text),
        )
        audit_id = _write_assignment_system_audit(
            conn,
            action="update_concurrency_limit",
            operator=operator_text,
            reason=f"set global_concurrency_limit={next_limit}",
            detail={"global_concurrency_limit": next_limit},
            created_at=now_text,
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "global_concurrency_limit": next_limit,
        "updated_at": now_text,
        "audit_id": audit_id,
    }


def set_assignment_execution_settings(
    root: Path,
    *,
    execution_provider: Any,
    codex_command_path: Any,
    command_template: Any,
    global_concurrency_limit: Any,
    operator: str,
) -> dict[str, Any]:
    _ensure_assignment_support_tables(root)
    now_text = iso_ts(now_local())
    provider = _normalize_execution_provider(execution_provider)
    codex_path = _normalize_codex_command_path(_normalize_text(
        codex_command_path or _default_codex_command_path(),
        field="codex_command_path",
        required=True,
        max_len=500,
    ))
    template = _normalize_text(
        command_template or _default_assignment_command_template(provider),
        field="command_template",
        required=True,
        max_len=2000,
    )
    template = _normalize_assignment_command_template_value(template, provider)
    if "{workspace_path}" not in template or "{codex_path}" not in template:
        raise AssignmentCenterError(
            400,
            "command_template must include {codex_path} and {workspace_path}",
            "assignment_command_template_invalid",
        )
    next_limit = _normalize_positive_int(
        global_concurrency_limit,
        field="global_concurrency_limit",
        default=DEFAULT_ASSIGNMENT_CONCURRENCY_LIMIT,
        minimum=1,
        maximum=64,
    )
    operator_text = _default_assignment_operator(operator)
    conn = connect_db(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        _set_assignment_setting_text(
            conn,
            key="execution_provider",
            value=provider,
            now_text=now_text,
        )
        _set_assignment_setting_text(
            conn,
            key="codex_command_path",
            value=codex_path,
            now_text=now_text,
        )
        _set_assignment_setting_text(
            conn,
            key="codex_command_template",
            value=template,
            now_text=now_text,
        )
        _set_assignment_setting_text(
            conn,
            key="global_concurrency_limit",
            value=str(next_limit),
            now_text=now_text,
        )
        audit_id = _write_assignment_system_audit(
            conn,
            action="update_execution_settings",
            operator=operator_text,
            reason=f"set assignment execution provider={provider}",
            detail={
                "execution_provider": provider,
                "codex_command_path": codex_path,
                "command_template": template,
                "global_concurrency_limit": next_limit,
            },
            created_at=now_text,
        )
        payload = _assignment_execution_settings_from_conn(conn)
        conn.commit()
    finally:
        conn.close()
    payload["audit_id"] = audit_id
    return payload


def _write_assignment_audit(
    conn: sqlite3.Connection,
    *,
    ticket_id: str,
    node_id: str,
    action: str,
    operator: str,
    reason: str,
    target_status: str,
    detail: dict[str, Any] | None,
    created_at: str,
) -> str:
    audit_id = assignment_audit_id()
    conn.execute(
        """
        INSERT INTO assignment_audit_log (
            audit_id,ticket_id,node_id,action,operator,reason,target_status,detail_json,ref,created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            audit_id,
            str(ticket_id or "").strip(),
            str(node_id or "").strip(),
            str(action or "").strip(),
            _default_assignment_operator(operator),
            str(reason or "").strip(),
            str(target_status or "").strip(),
            json.dumps(detail or {}, ensure_ascii=False),
            _db_ref(audit_id),
            created_at,
        ),
    )
    return audit_id


def _write_assignment_system_audit(
    conn: sqlite3.Connection,
    *,
    action: str,
    operator: str,
    reason: str,
    detail: dict[str, Any] | None,
    created_at: str,
) -> str:
    audit_id = assignment_audit_id()
    conn.execute(
        """
        INSERT INTO assignment_system_audit (
            audit_id,action,operator,reason,detail_json,created_at
        ) VALUES (?,?,?,?,?,?)
        """,
        (
            audit_id,
            str(action or "").strip(),
            _default_assignment_operator(operator),
            str(reason or "").strip(),
            json.dumps(detail or {}, ensure_ascii=False),
            created_at,
        ),
    )
    return audit_id


def _assignment_artifact_root(root: Path) -> Path:
    runtime_cfg = load_runtime_config(root)
    raw = str(runtime_cfg.get("artifact_root") or "").strip()
    base = Path(__file__).resolve().parents[4]
    default_root = (base.parent / ".output").resolve(strict=False)
    try:
        candidate = normalize_abs_path(raw, base=base) if raw else default_root
    except Exception:
        candidate = default_root
    artifact_root, _workspace_root = ensure_artifact_root_dirs(candidate)
    return artifact_root


def _assignment_workspace_root(root: Path) -> Path:
    artifact_root = _assignment_artifact_root(root)
    return (artifact_root / "workspace" / "assignments").resolve(strict=False)
