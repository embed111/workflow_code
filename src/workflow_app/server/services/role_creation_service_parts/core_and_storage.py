import base64
import binascii
import json
import re
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from . import assignment_service

connect_db: Any = None
safe_token: Any = None
now_local: Any = None
iso_ts: Any = None
date_key: Any = None
path_in_scope: Any = None
relative_to_root: Any = None
append_training_center_audit: Any = None
TrainingCenterError: Any = RuntimeError

ROLE_CREATION_STAGES: tuple[dict[str, Any], ...] = (
    {
        "key": "workspace_init",
        "index": 1,
        "title": "初始化工作区",
        "kind": "system",
        "analyst_title": "初始化角色骨架",
        "analyst_desc": "生成真实角色工作区、记忆骨架与维护脚本。",
        "next_hint": "完成后进入角色画像收集。",
    },
    {
        "key": "persona_collection",
        "index": 2,
        "title": "角色画像收集",
        "kind": "task",
        "analyst_title": "分析引导与画像收口",
        "analyst_desc": "继续收口角色目标、边界、场景和协作方式。",
        "next_hint": "信息足够后进入能力后台生成。",
    },
    {
        "key": "capability_generation",
        "index": 3,
        "title": "能力后台生成",
        "kind": "task",
        "analyst_title": "后台能力生成协调",
        "analyst_desc": "把已确认画像拆成具体后台任务并持续调向。",
        "next_hint": "生成结果后进入回看与调向。",
    },
    {
        "key": "review_and_alignment",
        "index": 4,
        "title": "结果回看与调向",
        "kind": "task",
        "analyst_title": "结果回传与方向调整",
        "analyst_desc": "把后台产物回传到当前会话，并决定是否继续补能力。",
        "next_hint": "主要结果满足预期后进入确认验收。",
    },
    {
        "key": "acceptance_confirmation",
        "index": 5,
        "title": "确认验收",
        "kind": "analyst",
        "analyst_title": "验收追问与放行判断",
        "analyst_desc": "由当前分析师发起验收问答，等待用户明确确认。",
        "next_hint": "用户确认通过后即可完成角色创建。",
    },
    {
        "key": "complete_creation",
        "index": 6,
        "title": "完成角色创建",
        "kind": "analyst",
        "analyst_title": "完成创建并切回空闲",
        "analyst_desc": "调用完成接口，保留工作区与记忆机制，切回可用状态。",
        "next_hint": "完成后角色可继续进入训练与发布治理。",
    },
)
ROLE_CREATION_STAGE_BY_KEY = {str(item["key"]): dict(item) for item in ROLE_CREATION_STAGES}
ROLE_CREATION_REQUIRED_FIELDS = ("role_name", "role_goal", "core_capabilities")
ROLE_CREATION_ALL_FIELDS = (
    "role_name",
    "role_goal",
    "core_capabilities",
    "boundaries",
    "applicable_scenarios",
    "collaboration_style",
    "example_assets",
)
ROLE_CREATION_RUNTIME_STATUS_LABELS = {
    "idle": "空闲",
    "creating": "创建中",
    "training": "训练中",
    "executing": "执行中",
}
ROLE_CREATION_SESSION_STATUSES = {"draft", "creating", "completed"}
ROLE_CREATION_MESSAGE_TYPES = {"chat", "system_task_update", "system_stage_update", "system_result"}
ROLE_CREATION_MESSAGE_QUEUE_STATES = {"idle", "pending", "running", "failed"}
ROLE_CREATION_MESSAGE_QUEUE_STATE_LABELS = {
    "idle": "空闲",
    "pending": "待分析",
    "running": "分析中",
    "failed": "分析失败",
}
ROLE_CREATION_USER_MESSAGE_PROCESSING_STATES = {"pending", "processing", "processed", "failed"}
ROLE_CREATION_USER_MESSAGE_PROCESSING_LABELS = {
    "pending": "待处理",
    "processing": "处理中",
    "processed": "已处理",
    "failed": "处理失败",
}
ROLE_CREATION_MESSAGE_BATCH_DEBOUNCE_S = 0.9
ROLE_CREATION_DELEGATE_PATTERN = re.compile(
    r"(另起(?:一个)?任务去|单独起(?:一个)?任务去|单独起个任务去|后台去跑|后台去做|后台去处理|去整理|去收集|去生成|去补)",
    re.IGNORECASE,
)
ROLE_CREATION_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


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


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads_dict(raw: Any) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _json_loads_list(raw: Any) -> list[Any]:
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        value = json.loads(text)
    except Exception:
        return []
    return value if isinstance(value, list) else []


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, column_def: str) -> None:
    cols = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")


def _ensure_role_creation_tables(root: Path) -> None:
    conn = connect_db(root)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS role_creation_sessions (
                session_id TEXT PRIMARY KEY,
                session_title TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft',
                current_stage_key TEXT NOT NULL DEFAULT 'workspace_init',
                current_stage_index INTEGER NOT NULL DEFAULT 1,
                role_spec_json TEXT NOT NULL DEFAULT '{}',
                missing_fields_json TEXT NOT NULL DEFAULT '[]',
                assignment_ticket_id TEXT NOT NULL DEFAULT '',
                created_agent_id TEXT NOT NULL DEFAULT '',
                created_agent_name TEXT NOT NULL DEFAULT '',
                created_agent_workspace_path TEXT NOT NULL DEFAULT '',
                workspace_init_status TEXT NOT NULL DEFAULT 'pending',
                workspace_init_ref TEXT NOT NULL DEFAULT '',
                last_message_preview TEXT NOT NULL DEFAULT '',
                last_message_at TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL DEFAULT '',
                completed_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_role_creation_sessions_updated ON role_creation_sessions(updated_at DESC)"
        )
        _ensure_column(
            conn,
            "role_creation_sessions",
            "dialogue_agent_name",
            "dialogue_agent_name TEXT NOT NULL DEFAULT ''",
        )
        _ensure_column(
            conn,
            "role_creation_sessions",
            "dialogue_agent_workspace_path",
            "dialogue_agent_workspace_path TEXT NOT NULL DEFAULT ''",
        )
        _ensure_column(
            conn,
            "role_creation_sessions",
            "dialogue_provider",
            "dialogue_provider TEXT NOT NULL DEFAULT ''",
        )
        _ensure_column(
            conn,
            "role_creation_sessions",
            "last_dialogue_trace_ref",
            "last_dialogue_trace_ref TEXT NOT NULL DEFAULT ''",
        )
        _ensure_column(
            conn,
            "role_creation_sessions",
            "message_processing_status",
            "message_processing_status TEXT NOT NULL DEFAULT 'idle'",
        )
        _ensure_column(
            conn,
            "role_creation_sessions",
            "message_processing_error",
            "message_processing_error TEXT NOT NULL DEFAULT ''",
        )
        _ensure_column(
            conn,
            "role_creation_sessions",
            "message_processing_started_at",
            "message_processing_started_at TEXT NOT NULL DEFAULT ''",
        )
        _ensure_column(
            conn,
            "role_creation_sessions",
            "message_processing_updated_at",
            "message_processing_updated_at TEXT NOT NULL DEFAULT ''",
        )
        _ensure_column(
            conn,
            "role_creation_sessions",
            "message_processing_batch_id",
            "message_processing_batch_id TEXT NOT NULL DEFAULT ''",
        )
        _ensure_column(
            conn,
            "role_creation_sessions",
            "user_message_count",
            "user_message_count INTEGER NOT NULL DEFAULT 0",
        )
        _ensure_column(
            conn,
            "role_creation_sessions",
            "unhandled_user_message_count",
            "unhandled_user_message_count INTEGER NOT NULL DEFAULT 0",
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS role_creation_messages (
                message_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                attachments_json TEXT NOT NULL DEFAULT '[]',
                message_type TEXT NOT NULL DEFAULT 'chat',
                meta_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_role_creation_messages_session ON role_creation_messages(session_id,created_at)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS role_creation_task_refs (
                ref_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                ticket_id TEXT NOT NULL,
                node_id TEXT NOT NULL,
                stage_key TEXT NOT NULL,
                stage_index INTEGER NOT NULL DEFAULT 0,
                relation_state TEXT NOT NULL DEFAULT 'active',
                close_reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_role_creation_task_refs_unique ON role_creation_task_refs(session_id,node_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_role_creation_task_refs_stage ON role_creation_task_refs(session_id,stage_index,updated_at)"
        )
        _ensure_column(
            conn,
            "agent_registry",
            "runtime_status",
            "runtime_status TEXT NOT NULL DEFAULT 'idle'",
        )
        conn.commit()
    finally:
        conn.close()


def _tc_now_text() -> str:
    return iso_ts(now_local())


def _role_creation_session_id() -> str:
    ts = now_local()
    return f"rcs-{date_key(ts)}-{ts.strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}"


def _role_creation_message_id() -> str:
    ts = now_local()
    return f"rcm-{date_key(ts)}-{ts.strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}"


def _role_creation_task_ref_id() -> str:
    ts = now_local()
    return f"rct-{date_key(ts)}-{ts.strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}"


def _normalize_stage_key(raw: Any, *, allow_empty: bool = False) -> str:
    text = str(raw or "").strip().lower()
    if allow_empty and not text:
        return ""
    if text not in ROLE_CREATION_STAGE_BY_KEY:
        raise TrainingCenterError(400, "stage_key invalid", "role_creation_stage_invalid")
    return text


def _runtime_status_label(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    return ROLE_CREATION_RUNTIME_STATUS_LABELS.get(text, "空闲")


def _normalize_session_status(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if text not in ROLE_CREATION_SESSION_STATUSES:
        return "draft"
    return text


def _normalize_message_type(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if text not in ROLE_CREATION_MESSAGE_TYPES:
        return "chat"
    return text


def _normalize_role_creation_queue_state(raw: Any, *, default: str = "idle") -> str:
    fallback = default if default in ROLE_CREATION_MESSAGE_QUEUE_STATES else "idle"
    text = str(raw or "").strip().lower()
    if text not in ROLE_CREATION_MESSAGE_QUEUE_STATES:
        return fallback
    return text


def _normalize_role_creation_user_message_state(raw: Any, *, default: str = "processed") -> str:
    fallback = default if default in ROLE_CREATION_USER_MESSAGE_PROCESSING_STATES else "processed"
    text = str(raw or "").strip().lower()
    if text not in ROLE_CREATION_USER_MESSAGE_PROCESSING_STATES:
        return fallback
    return text


def _role_creation_queue_state_text(raw: Any) -> str:
    key = _normalize_role_creation_queue_state(raw)
    return ROLE_CREATION_MESSAGE_QUEUE_STATE_LABELS.get(key, "空闲")


def _role_creation_user_message_state_text(raw: Any) -> str:
    key = _normalize_role_creation_user_message_state(raw)
    return ROLE_CREATION_USER_MESSAGE_PROCESSING_LABELS.get(key, "已处理")


def _parse_bool_flag(value: Any, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return bool(default)


def _normalize_text(value: Any, *, max_len: int = 0) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if max_len > 0:
        return text[:max_len]
    return text


def _split_items(value: Any, *, limit: int = 12) -> list[str]:
    if isinstance(value, list):
        items: list[str] = []
        for raw in value:
            items.extend(
                _normalize_text(item, max_len=200)
                for item in re.split(r"[\n,，、;；|]+", str(raw or ""))
            )
    else:
        items = [
            _normalize_text(item, max_len=200)
            for item in re.split(r"[\n,，、;；|]+", str(value or ""))
        ]
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= max(1, int(limit)):
            break
    return out


def _message_preview(content: Any, attachments: list[dict[str, Any]]) -> str:
    text = _normalize_text(content, max_len=120)
    if text:
        return text
    if attachments:
        return f"[图片 {len(attachments)}]"
    return ""


def _normalize_message_attachments(raw: Any) -> list[dict[str, Any]]:
    items = raw if isinstance(raw, list) else []
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        content_type = _normalize_text(item.get("content_type"), max_len=80).lower()
        data_url = _normalize_text(item.get("data_url"), max_len=4_000_000)
        if not data_url and content_type in ROLE_CREATION_IMAGE_MIME_TYPES:
            payload_base64 = _normalize_text(item.get("payload_base64"), max_len=4_000_000)
            if payload_base64:
                data_url = f"data:{content_type};base64,{payload_base64}"
        if not data_url:
            continue
        if not content_type:
            m = re.match(r"^data:([^;,]+)", data_url, flags=re.IGNORECASE)
            if m:
                content_type = _normalize_text(m.group(1), max_len=80).lower()
        if content_type not in ROLE_CREATION_IMAGE_MIME_TYPES:
            raise TrainingCenterError(400, "仅支持图片附件", "role_creation_attachment_type_invalid")
        if not data_url.startswith("data:") or ";base64," not in data_url:
            raise TrainingCenterError(400, "图片附件编码无效", "role_creation_attachment_invalid")
        header, payload = data_url.split(",", 1)
        try:
            binary = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError):
            raise TrainingCenterError(400, "图片附件编码无效", "role_creation_attachment_invalid_base64")
        if len(binary) > 4 * 1024 * 1024:
            raise TrainingCenterError(400, "单张图片不能超过 4MB", "role_creation_attachment_too_large")
        out.append(
            {
                "attachment_id": safe_token(
                    _normalize_text(item.get("attachment_id") or uuid.uuid4().hex[:10]),
                    uuid.uuid4().hex[:10],
                    40,
                ),
                "kind": "image",
                "file_name": _normalize_text(item.get("file_name"), max_len=200) or "image",
                "content_type": content_type,
                "size_bytes": len(binary),
                "data_url": header + "," + base64.b64encode(binary).decode("ascii"),
            }
        )
    return out[:6]


def _session_row_to_summary(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    current = dict(row or {})
    role_spec = _json_loads_dict(current.get("role_spec_json"))
    missing_fields = [str(item).strip() for item in _json_loads_list(current.get("missing_fields_json")) if str(item).strip()]
    message_processing_status = _normalize_role_creation_queue_state(current.get("message_processing_status"), default="idle")
    status = _normalize_session_status(current.get("status"))
    workspace_init_status = str(current.get("workspace_init_status") or "").strip()
    current_stage_key = str(current.get("current_stage_key") or "workspace_init").strip()
    current_stage_index = int(current.get("current_stage_index") or 1)
    if status != "completed" and workspace_init_status != "completed":
        current_stage_key = "workspace_init"
        current_stage_index = 1
    return {
        "session_id": str(current.get("session_id") or "").strip(),
        "session_title": str(current.get("session_title") or "").strip(),
        "status": status,
        "current_stage_key": current_stage_key,
        "current_stage_index": current_stage_index,
        "last_message_preview": str(current.get("last_message_preview") or "").strip(),
        "last_message_at": str(current.get("last_message_at") or "").strip(),
        "assignment_ticket_id": str(current.get("assignment_ticket_id") or "").strip(),
        "created_agent_id": str(current.get("created_agent_id") or "").strip(),
        "created_agent_name": str(current.get("created_agent_name") or "").strip(),
        "created_agent_workspace_path": str(current.get("created_agent_workspace_path") or "").strip(),
        "workspace_init_status": workspace_init_status,
        "workspace_init_ref": str(current.get("workspace_init_ref") or "").strip(),
        "dialogue_agent_name": str(current.get("dialogue_agent_name") or "").strip(),
        "dialogue_agent_workspace_path": str(current.get("dialogue_agent_workspace_path") or "").strip(),
        "dialogue_provider": str(current.get("dialogue_provider") or "").strip(),
        "last_dialogue_trace_ref": str(current.get("last_dialogue_trace_ref") or "").strip(),
        "message_processing_status": message_processing_status,
        "message_processing_status_text": _role_creation_queue_state_text(message_processing_status),
        "message_processing_error": str(current.get("message_processing_error") or "").strip(),
        "message_processing_started_at": str(current.get("message_processing_started_at") or "").strip(),
        "message_processing_updated_at": str(current.get("message_processing_updated_at") or "").strip(),
        "message_processing_batch_id": str(current.get("message_processing_batch_id") or "").strip(),
        "user_message_count": int(current.get("user_message_count") or 0),
        "unhandled_user_message_count": int(current.get("unhandled_user_message_count") or 0),
        "started_at": str(current.get("started_at") or "").strip(),
        "completed_at": str(current.get("completed_at") or "").strip(),
        "created_at": str(current.get("created_at") or "").strip(),
        "updated_at": str(current.get("updated_at") or "").strip(),
        "role_name": str(role_spec.get("role_name") or "").strip(),
        "missing_fields": missing_fields,
    }


def _fetch_session_row(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM role_creation_sessions WHERE session_id=? LIMIT 1",
        (session_id,),
    ).fetchone()
    if row is None:
        raise TrainingCenterError(404, "role creation session not found", "role_creation_session_not_found")
    return row


def _list_session_messages(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT message_id,session_id,role,content,attachments_json,message_type,meta_json,created_at
        FROM role_creation_messages
        WHERE session_id=?
        ORDER BY created_at ASC,message_id ASC
        """,
        (session_id,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        meta = _json_loads_dict(row["meta_json"])
        role = str(row["role"] or "").strip().lower() or "assistant"
        message_type = _normalize_message_type(row["message_type"])
        processing_state = ""
        if role == "user" and message_type == "chat":
            processing_state = _normalize_role_creation_user_message_state(
                meta.get("processing_state"),
                default="processed",
            )
        out.append(
            {
                "message_id": str(row["message_id"] or "").strip(),
                "session_id": str(row["session_id"] or "").strip(),
                "role": role,
                "content": str(row["content"] or ""),
                "attachments": _json_loads_list(row["attachments_json"]),
                "message_type": message_type,
                "meta": meta,
                "processing_state": processing_state,
                "processing_state_text": _role_creation_user_message_state_text(processing_state) if processing_state else "",
                "processing_batch_id": str(meta.get("processing_batch_id") or "").strip(),
                "processing_error": str(meta.get("processing_error") or "").strip(),
                "processing_started_at": str(meta.get("processing_started_at") or "").strip(),
                "processed_at": str(meta.get("processed_at") or "").strip(),
                "client_message_id": str(meta.get("client_message_id") or "").strip(),
                "created_at": str(row["created_at"] or "").strip(),
            }
        )
    return out


def _role_creation_user_message_counts(messages: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "total": 0,
        "pending": 0,
        "processing": 0,
        "processed": 0,
        "failed": 0,
        "unhandled": 0,
    }
    for message in list(messages or []):
        if str(message.get("role") or "").strip().lower() != "user":
            continue
        if _normalize_message_type(message.get("message_type")) != "chat":
            continue
        state = _normalize_role_creation_user_message_state(
            message.get("processing_state") or (message.get("meta") or {}).get("processing_state"),
            default="processed",
        )
        counts["total"] += 1
        counts[state] += 1
        if state != "processed":
            counts["unhandled"] += 1
    return counts


def _update_role_creation_message_queue_state(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    queue_status: str,
    queue_error: str | None = None,
    batch_id: str | None = None,
    started_at: str | None = None,
    updated_at: str = "",
    messages: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    current_row = _fetch_session_row(conn, session_id)
    current = dict(current_row or {})
    next_status = _normalize_role_creation_queue_state(
        queue_status,
        default=str(current.get("message_processing_status") or "idle").strip().lower() or "idle",
    )
    current_error = str(current.get("message_processing_error") or "").strip()
    current_batch_id = str(current.get("message_processing_batch_id") or "").strip()
    current_started_at = str(current.get("message_processing_started_at") or "").strip()
    rows = list(messages or _list_session_messages(conn, session_id))
    counts = _role_creation_user_message_counts(rows)
    updated_text = _normalize_text(updated_at or _tc_now_text(), max_len=40) or _tc_now_text()
    next_error = current_error if queue_error is None else _normalize_text(queue_error, max_len=2000)
    next_batch_id = current_batch_id if batch_id is None else _normalize_text(batch_id, max_len=120)
    next_started_at = current_started_at if started_at is None else _normalize_text(started_at, max_len=40)
    if next_status == "running":
        next_started_at = next_started_at or updated_text
    elif next_status == "pending":
        next_error = ""
        if counts["processing"] <= 0:
            next_batch_id = ""
    elif next_status == "idle":
        next_error = ""
        next_batch_id = ""
        next_started_at = ""
    if counts["unhandled"] <= 0 and next_status != "failed":
        next_status = "idle"
        next_error = ""
        next_batch_id = ""
        next_started_at = ""
    conn.execute(
        """
        UPDATE role_creation_sessions
        SET message_processing_status=?,message_processing_error=?,message_processing_started_at=?,
            message_processing_updated_at=?,message_processing_batch_id=?,user_message_count=?,unhandled_user_message_count=?
        WHERE session_id=?
        """,
        (
            next_status,
            next_error,
            next_started_at,
            updated_text,
            next_batch_id,
            counts["total"],
            counts["unhandled"],
            session_id,
        ),
    )
    return counts


def _list_task_refs(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT ref_id,session_id,ticket_id,node_id,stage_key,stage_index,relation_state,close_reason,created_at,updated_at
        FROM role_creation_task_refs
        WHERE session_id=?
        ORDER BY stage_index ASC,created_at ASC,node_id ASC
        """,
        (session_id,),
    ).fetchall()
    return [
        {
            "ref_id": str(row["ref_id"] or "").strip(),
            "session_id": str(row["session_id"] or "").strip(),
            "ticket_id": str(row["ticket_id"] or "").strip(),
            "node_id": str(row["node_id"] or "").strip(),
            "stage_key": str(row["stage_key"] or "").strip(),
            "stage_index": int(row["stage_index"] or 0),
            "relation_state": str(row["relation_state"] or "active").strip().lower() or "active",
            "close_reason": str(row["close_reason"] or "").strip(),
            "created_at": str(row["created_at"] or "").strip(),
            "updated_at": str(row["updated_at"] or "").strip(),
        }
        for row in rows
    ]
