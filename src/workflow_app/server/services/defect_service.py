from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from ..infra.db.connection import connect_db
from . import assignment_service, runtime_upgrade_service


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


class DefectCenterError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        message: str,
        code: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = int(status_code)
        self.code = str(code or "defect_error")
        self.extra = dict(extra or {})


DEFECT_STATUS_NOT_FORMAL = "not_formal"
DEFECT_STATUS_UNRESOLVED = "unresolved"
DEFECT_STATUS_RESOLVED = "resolved"
DEFECT_STATUS_CLOSED = "closed"
DEFECT_STATUS_DISPUTE = "dispute"

DEFECT_ALL_STATUSES = {
    DEFECT_STATUS_NOT_FORMAL,
    DEFECT_STATUS_UNRESOLVED,
    DEFECT_STATUS_RESOLVED,
    DEFECT_STATUS_CLOSED,
    DEFECT_STATUS_DISPUTE,
}

DEFECT_STATUS_TEXT = {
    DEFECT_STATUS_NOT_FORMAL: "当前不构成缺陷",
    DEFECT_STATUS_UNRESOLVED: "未解决",
    DEFECT_STATUS_RESOLVED: "已解决",
    DEFECT_STATUS_CLOSED: "已关闭",
    DEFECT_STATUS_DISPUTE: "有分歧",
}

DEFECT_PROCESS_ACTION_KIND = "process"
DEFECT_REVIEW_ACTION_KIND = "review"
DEFECT_QUEUE_SETTINGS_ID = "default"
DEFECT_DEFAULT_TASK_PRIORITY = "P1"
DEFECT_QUEUE_ELIGIBLE_STATUSES = {
    DEFECT_STATUS_UNRESOLVED,
    DEFECT_STATUS_DISPUTE,
}
DEFECT_QUEUE_TERMINAL_STATUSES = {
    DEFECT_STATUS_RESOLVED,
    DEFECT_STATUS_CLOSED,
}
_DEFECT_TABLES_READY_ROOTS: set[str] = set()
DEFECT_QUEUE_SETTINGS_ID = "default"
DEFECT_DEFAULT_TASK_PRIORITY = "P1"
DEFECT_QUEUE_ELIGIBLE_STATUSES = {
    DEFECT_STATUS_UNRESOLVED,
    DEFECT_STATUS_DISPUTE,
}
DEFECT_QUEUE_TERMINAL_STATUSES = {
    DEFECT_STATUS_RESOLVED,
    DEFECT_STATUS_CLOSED,
}


def _now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _date_key() -> str:
    return datetime.now().astimezone().strftime("%Y%m%d")


def _safe_token(value: Any, *, max_len: int = 160) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    out = []
    for ch in text[:max_len]:
        if ch.isalnum() or ch in {"-", "_", ".", ":"}:
            out.append(ch)
    return "".join(out)


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, column_def: str) -> None:
    existing = {
        str((row["name"] if isinstance(row, sqlite3.Row) else row[1]) or "").strip()
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if str(column or "").strip() in existing:
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, column_def: str) -> None:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    existing = {
        str((row["name"] if isinstance(row, sqlite3.Row) else row[1]) or "").strip()
        for row in rows
    }
    if str(column or "").strip() in existing:
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")


def _json_dumps(payload: Any, fallback: str) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False, indent=None)
    except Exception:
        return fallback


def _json_loads_object(raw: Any) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _json_loads_list(raw: Any) -> list[Any]:
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except Exception:
        return []
    return payload if isinstance(payload, list) else []


def _bool_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


def _normalize_task_priority(value: Any, *, default: str = DEFECT_DEFAULT_TASK_PRIORITY) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return str(default or DEFECT_DEFAULT_TASK_PRIORITY).strip().upper() or DEFECT_DEFAULT_TASK_PRIORITY
    if text.startswith("P") and len(text) == 2 and text[1].isdigit():
        label = text
    else:
        try:
            label = f"P{int(text)}"
        except Exception as exc:
            raise DefectCenterError(
                400,
                "task_priority only allows P0/P1/P2/P3 or 0/1/2/3",
                "defect_task_priority_invalid",
            ) from exc
    if label not in {"P0", "P1", "P2", "P3"}:
        raise DefectCenterError(
            400,
            "task_priority only allows P0/P1/P2/P3 or 0/1/2/3",
            "defect_task_priority_invalid",
        )
    return label


def _task_priority_rank(value: Any) -> int:
    label = _normalize_task_priority(value, default=DEFECT_DEFAULT_TASK_PRIORITY)
    return int(label[1])


def _infer_task_priority(
    report_text: Any,
    *,
    decision: dict[str, Any] | None = None,
    status: Any = "",
) -> str:
    combined = " ".join(
        [
            str(report_text or "").strip().lower(),
            str((decision or {}).get("title") or "").strip().lower(),
            str((decision or {}).get("summary") or "").strip().lower(),
        ]
    )
    if any(token in combined for token in ("崩溃", "卡死", "白屏", "无法", "不能", "不可用", "连接不上", "连不上", "中断", "退出", "消失", "丢失")):
        return "P0"
    if any(token in combined for token in ("失败", "报错", "异常", "阻塞", "超时", "不生效", "错位", "遮挡", "回退", "404", "500")):
        return "P1"
    if str(status or "").strip().lower() == DEFECT_STATUS_NOT_FORMAL:
        return "P3"
    return "P2"


_EXPLICIT_PRIORITY_PATTERNS = (
    re.compile(r"[\[【(]\s*(P[0-3]|[0-3])\s*[\]】)]", re.IGNORECASE),
    re.compile(r"(?:建议)?优先级\s*[:：]?\s*(P[0-3]|[0-3])\b", re.IGNORECASE),
)


def _extract_explicit_task_priority(
    value: Any,
    *,
    field: str,
    strict: bool,
) -> str:
    text = str(value or "")
    if not text.strip():
        return ""
    for pattern in _EXPLICIT_PRIORITY_PATTERNS:
        matched = pattern.search(text)
        if matched is not None:
            return _normalize_task_priority(matched.group(1), default=DEFECT_DEFAULT_TASK_PRIORITY)
    if not strict:
        return ""
    upper = text.upper()
    candidates: list[str] = []
    for matched in re.finditer(r"[\[【(]\s*([^\s\]】)]+)\s*[\]】)]", upper):
        token = str(matched.group(1) or "").strip()
        if token.startswith("P"):
            candidates.append(token)
    for matched in re.finditer(r"(?:建议)?优先级\s*[:：]?\s*([A-Z0-9]+)\b", upper):
        token = str(matched.group(1) or "").strip()
        if token:
            candidates.append(token)
    for token in candidates:
        try:
            return _normalize_task_priority(token, default=DEFECT_DEFAULT_TASK_PRIORITY)
        except DefectCenterError as exc:
            raise DefectCenterError(
                400,
                f"{field} contains invalid explicit task_priority",
                "defect_task_priority_invalid",
                {"field": field, "explicit_token": token},
            ) from exc
    return ""


def _resolve_explicit_task_priority(
    explicit_value: Any,
    defect_summary: Any,
    report_text: Any,
    *,
    strict: bool,
) -> tuple[str, str]:
    explicit_text = str(explicit_value or "").strip()
    if explicit_text:
        return _normalize_task_priority(explicit_text, default=DEFECT_DEFAULT_TASK_PRIORITY), "field"
    for field_name, value in (
        ("defect_summary", defect_summary),
        ("report_text", report_text),
    ):
        parsed = _extract_explicit_task_priority(value, field=field_name, strict=strict)
        if parsed:
            return parsed, field_name
    return "", ""


def _resolve_task_priority_truth(
    *,
    explicit_value: Any = "",
    defect_summary: Any = "",
    report_text: Any = "",
    stored_priority: Any = "",
    decision: dict[str, Any] | None = None,
    status: Any = "",
    strict: bool,
) -> tuple[str, str]:
    explicit_priority, explicit_source = _resolve_explicit_task_priority(
        explicit_value,
        defect_summary,
        report_text,
        strict=strict,
    )
    if explicit_priority:
        return explicit_priority, explicit_source
    fallback = stored_priority or _infer_task_priority(report_text, decision=decision, status=status)
    return _normalize_task_priority(fallback, default=DEFECT_DEFAULT_TASK_PRIORITY), "inferred"


def _normalize_reported_at(value: Any, *, fallback: str = "") -> str:
    text = str(value or "").strip()
    if text:
        return text[:64]
    return str(fallback or _now_text()).strip()[:64]


def _reported_at_sort_text(item: dict[str, Any]) -> str:
    return str(item.get("reported_at") or item.get("created_at") or "").strip()


def _report_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    dts_sequence = int(item.get("dts_sequence") or 0)
    dts_marker = dts_sequence if dts_sequence > 0 else 10**9
    return (
        _task_priority_rank(item.get("task_priority")),
        _reported_at_sort_text(item),
        dts_marker,
        str(item.get("report_id") or "").strip(),
    )


def _defect_order_by_sql() -> str:
    return (
        " ORDER BY "
        "CASE UPPER(COALESCE(task_priority,'')) "
        "WHEN 'P0' THEN 0 "
        "WHEN 'P1' THEN 1 "
        "WHEN 'P2' THEN 2 "
        "WHEN 'P3' THEN 3 "
        "ELSE 9 END ASC, "
        "COALESCE(reported_at,'') ASC, "
        "CASE WHEN COALESCE(dts_sequence,0)>0 THEN dts_sequence ELSE 1000000000 END ASC, "
        "COALESCE(report_id,'') ASC"
    )


def _defect_report_id() -> str:
    return f"dr-{_date_key()}-{uuid.uuid4().hex[:10]}"


def _defect_history_id() -> str:
    return f"dh-{_date_key()}-{uuid.uuid4().hex[:10]}"


def _require_report_id(report_id: str) -> str:
    key = _safe_token(report_id, max_len=160)
    if not key:
        raise DefectCenterError(400, "report_id required", "defect_report_id_required")
    return key


def _status_text(status: Any) -> str:
    return DEFECT_STATUS_TEXT.get(str(status or "").strip().lower(), str(status or "").strip() or "-")


def _normalize_text(
    value: Any,
    *,
    field: str,
    required: bool = False,
    max_len: int = 4000,
) -> str:
    text = str(value or "").strip()
    if not text:
        if required:
            raise DefectCenterError(400, f"{field} required", f"{field}_required")
        return ""
    if len(text) > max_len:
        raise DefectCenterError(400, f"{field} too long", f"{field}_too_long", {"max_len": max_len})
    return text


def _derive_summary(summary: Any, report_text: Any) -> str:
    summary_text = str(summary or "").strip()
    if summary_text:
        return summary_text[:120]
    for line in str(report_text or "").splitlines():
        candidate = line.strip()
        if candidate:
            return candidate[:120]
    return "未命名缺陷记录"


def _normalize_image_evidence(raw: Any) -> list[dict[str, Any]]:
    rows = raw if isinstance(raw, list) else []
    out: list[dict[str, Any]] = []
    for item in rows:
        if isinstance(item, str):
            url = item.strip()
            if not url:
                continue
            out.append({"image_id": f"img-{uuid.uuid4().hex[:8]}", "name": "", "url": url})
            continue
        if not isinstance(item, dict):
            continue
        url = str(
            item.get("url")
            or item.get("src")
            or item.get("data_url")
            or item.get("dataUrl")
            or item.get("content")
            or ""
        ).strip()
        if not url:
            continue
        out.append(
            {
                "image_id": _safe_token(item.get("image_id") or item.get("attachment_id") or "", max_len=80)
                or f"img-{uuid.uuid4().hex[:8]}",
                "name": str(item.get("name") or item.get("file_name") or "").strip()[:240],
                "url": url,
            }
        )
    return out


def _ensure_defect_tables(root: Path) -> None:
    root_path = Path(root).resolve(strict=False)
    cache_key = root_path.as_posix()
    if cache_key in _DEFECT_TABLES_READY_ROOTS:
        return
    conn = connect_db(root_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS defect_reports (
                report_id TEXT PRIMARY KEY,
                dts_id TEXT NOT NULL DEFAULT '',
                dts_sequence INTEGER NOT NULL DEFAULT 0,
                defect_summary TEXT NOT NULL DEFAULT '',
                report_text TEXT NOT NULL DEFAULT '',
                evidence_images_json TEXT NOT NULL DEFAULT '[]',
                task_priority TEXT NOT NULL DEFAULT 'P1',
                reported_at TEXT NOT NULL DEFAULT '',
                is_formal INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'not_formal',
                discovered_iteration TEXT NOT NULL DEFAULT '',
                resolved_version TEXT NOT NULL DEFAULT '',
                current_decision_json TEXT NOT NULL DEFAULT '{}',
                report_source TEXT NOT NULL DEFAULT 'workflow-ui',
                automation_context_json TEXT NOT NULL DEFAULT '{}',
                is_test_data INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        _ensure_column(conn, "defect_reports", "dts_id", "dts_id TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "defect_reports", "dts_sequence", "dts_sequence INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "defect_reports", "task_priority", "task_priority TEXT NOT NULL DEFAULT 'P1'")
        _ensure_column(conn, "defect_reports", "reported_at", "reported_at TEXT NOT NULL DEFAULT ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_defect_reports_updated ON defect_reports(updated_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_defect_reports_status ON defect_reports(is_formal,status,updated_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_defect_reports_queue_sort ON defect_reports(status,task_priority,reported_at,dts_sequence,report_id)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_defect_reports_dts_id ON defect_reports(dts_id) WHERE dts_id<>''")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_defect_reports_dts_sequence ON defect_reports(dts_sequence) WHERE dts_sequence>0")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS defect_history (
                history_id TEXT PRIMARY KEY,
                report_id TEXT NOT NULL,
                entry_type TEXT NOT NULL,
                actor TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                detail_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_defect_history_report_time ON defect_history(report_id,created_at)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS defect_task_refs (
                ref_id TEXT PRIMARY KEY,
                report_id TEXT NOT NULL,
                ticket_id TEXT NOT NULL,
                focus_node_id TEXT NOT NULL DEFAULT '',
                action_kind TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                external_request_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_defect_task_refs_report_time ON defect_task_refs(report_id,updated_at DESC)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_defect_task_refs_unique ON defect_task_refs(report_id,ticket_id,focus_node_id,external_request_id)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS defect_queue_settings (
                settings_id TEXT PRIMARY KEY,
                sequential_task_creation_enabled INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        _ensure_defect_queue_settings_row(conn)
        _backfill_defect_report_defaults(conn)
        conn.commit()
    finally:
        conn.close()
    _DEFECT_TABLES_READY_ROOTS.add(cache_key)


def _ensure_defect_queue_settings_row(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT settings_id FROM defect_queue_settings WHERE settings_id=? LIMIT 1",
        (DEFECT_QUEUE_SETTINGS_ID,),
    ).fetchone()
    if row is not None:
        return
    conn.execute(
        """
        INSERT INTO defect_queue_settings(settings_id,sequential_task_creation_enabled,updated_at)
        VALUES (?,?,?)
        """,
        (DEFECT_QUEUE_SETTINGS_ID, 0, _now_text()),
    )


def _backfill_defect_report_defaults(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT report_id,defect_summary,report_text,current_decision_json,status,task_priority,reported_at,created_at
        FROM defect_reports
        WHERE COALESCE(task_priority,'')=''
           OR COALESCE(reported_at,'')=''
           OR COALESCE(defect_summary,'') LIKE '%[P%'
           OR COALESCE(report_text,'') LIKE '%优先级%'
        """
    ).fetchall()
    for row in rows:
        decision = _json_loads_object(row["current_decision_json"])
        priority, _source = _resolve_task_priority_truth(
            defect_summary=row["defect_summary"],
            report_text=row["report_text"],
            stored_priority=row["task_priority"],
            decision=decision,
            status=row["status"],
            strict=False,
        )
        reported_at = _normalize_reported_at(row["reported_at"], fallback=str(row["created_at"] or "").strip())
        report_id = str(row["report_id"] or "").strip()
        if priority != str(row["task_priority"] or "").strip() or reported_at != str(row["reported_at"] or "").strip():
            conn.execute(
                "UPDATE defect_reports SET task_priority=?, reported_at=? WHERE report_id=?",
                (priority, reported_at, report_id),
            )


def _report_row_to_payload(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    item = dict(row or {})
    status = str(item.get("status") or DEFECT_STATUS_NOT_FORMAL).strip().lower()
    task_priority, _source = _resolve_task_priority_truth(
        defect_summary=item.get("defect_summary"),
        report_text=item.get("report_text"),
        stored_priority=item.get("task_priority"),
        decision=_json_loads_object(item.get("current_decision_json")),
        status=status,
        strict=False,
    )
    reported_at = _normalize_reported_at(item.get("reported_at"), fallback=str(item.get("created_at") or "").strip())
    payload = {
        "report_id": str(item.get("report_id") or "").strip(),
        "dts_id": str(item.get("dts_id") or "").strip(),
        "dts_sequence": int(item.get("dts_sequence") or 0),
        "display_id": str(item.get("dts_id") or item.get("report_id") or "").strip(),
        "defect_summary": str(item.get("defect_summary") or "").strip(),
        "report_text": str(item.get("report_text") or "").strip(),
        "evidence_images": _normalize_image_evidence(_json_loads_list(item.get("evidence_images_json"))),
        "task_priority": task_priority,
        "reported_at": reported_at,
        "is_formal": bool(item.get("is_formal")),
        "status": status,
        "status_text": _status_text(status),
        "discovered_iteration": str(item.get("discovered_iteration") or "").strip(),
        "resolved_version": str(item.get("resolved_version") or "").strip(),
        "current_decision": _json_loads_object(item.get("current_decision_json")),
        "report_source": str(item.get("report_source") or "").strip(),
        "automation_context": _json_loads_object(item.get("automation_context_json")),
        "is_test_data": bool(item.get("is_test_data")),
        "created_at": str(item.get("created_at") or "").strip(),
        "updated_at": str(item.get("updated_at") or "").strip(),
    }
    payload["decision_title"] = str(payload["current_decision"].get("title") or "").strip()
    payload["decision_summary"] = str(payload["current_decision"].get("summary") or "").strip()
    payload["decision_source"] = str(payload["current_decision"].get("decision_source") or "").strip()
    payload["task_ref_total"] = int(item.get("task_ref_total") or 0)
    return payload


def _history_row_to_payload(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    item = dict(row or {})
    return {
        "history_id": str(item.get("history_id") or "").strip(),
        "report_id": str(item.get("report_id") or "").strip(),
        "entry_type": str(item.get("entry_type") or "").strip(),
        "actor": str(item.get("actor") or "").strip(),
        "title": str(item.get("title") or "").strip(),
        "detail": _json_loads_object(item.get("detail_json")),
        "created_at": str(item.get("created_at") or "").strip(),
    }


def _append_history(
    conn: sqlite3.Connection,
    report_id: str,
    *,
    entry_type: str,
    actor: str,
    title: str,
    detail: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO defect_history(history_id,report_id,entry_type,actor,title,detail_json,created_at)
        VALUES (?,?,?,?,?,?,?)
        """,
        (
            _defect_history_id(),
            report_id,
            str(entry_type or "").strip(),
            str(actor or "").strip(),
            str(title or "").strip(),
            _json_dumps(detail or {}, "{}"),
            str(created_at or _now_text()),
        ),
    )


def _load_report_row(
    conn: sqlite3.Connection,
    report_id: str,
    *,
    include_test_data: bool,
) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM defect_reports WHERE report_id=? LIMIT 1", (report_id,)).fetchone()
    if row is None:
        raise DefectCenterError(404, "defect report not found", "defect_report_not_found")
    if (not include_test_data) and bool(row["is_test_data"]):
        raise DefectCenterError(404, "defect report not found", "defect_report_not_found")
    return row


def _load_history_rows(conn: sqlite3.Connection, report_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM defect_history WHERE report_id=? ORDER BY created_at ASC, history_id ASC",
        (report_id,),
    ).fetchall()
    return [_history_row_to_payload(row) for row in rows]


def _load_task_ref_rows(conn: sqlite3.Connection, report_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM defect_task_refs WHERE report_id=? ORDER BY updated_at DESC, created_at DESC, ref_id DESC",
        (report_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _load_task_ref_counts(conn: sqlite3.Connection, report_ids: list[str]) -> dict[str, int]:
    keys = [str(report_id or "").strip() for report_id in report_ids if str(report_id or "").strip()]
    if not keys:
        return {}
    placeholders = ",".join(["?"] * len(keys))
    rows = conn.execute(
        f"""
        SELECT report_id,COUNT(*) AS total
        FROM defect_task_refs
        WHERE report_id IN ({placeholders})
        GROUP BY report_id
        """,
        tuple(keys),
    ).fetchall()
    return {
        str(row["report_id"] or "").strip(): int(row["total"] or 0)
        for row in rows
    }


def _defect_queue_state_payload(root: Path, *, include_test_data: bool = True) -> dict[str, Any]:
    _ensure_defect_tables(root)
    conn = connect_db(root)
    try:
        enabled_row = conn.execute(
            """
            SELECT sequential_task_creation_enabled,updated_at
            FROM defect_queue_settings
            WHERE settings_id=?
            LIMIT 1
            """,
            (DEFECT_QUEUE_SETTINGS_ID,),
        ).fetchone()
        enabled = bool(enabled_row["sequential_task_creation_enabled"]) if enabled_row is not None else False
        updated_at = str(enabled_row["updated_at"] or "").strip() if enabled_row is not None else ""
        sql = "SELECT * FROM defect_reports WHERE status IN (?,?)"
        params: list[Any] = [DEFECT_STATUS_UNRESOLVED, DEFECT_STATUS_DISPUTE]
        if not include_test_data:
            sql += " AND is_test_data=0"
        rows = conn.execute(sql, tuple(params)).fetchall()
        counts = _load_task_ref_counts(conn, [str(row["report_id"] or "").strip() for row in rows])
    finally:
        conn.close()
    candidates = []
    for row in rows:
        payload = _report_row_to_payload({**dict(row), "task_ref_total": counts.get(str(row["report_id"] or "").strip(), 0)})
        payload["queue_eligible"] = payload["status"] in DEFECT_QUEUE_ELIGIBLE_STATUSES
        if payload["queue_eligible"]:
            candidates.append(payload)
    candidates.sort(key=_report_sort_key)
    active = next((item for item in candidates if int(item.get("task_ref_total") or 0) > 0), None)
    next_pending = next(
        (
            item
            for item in candidates
            if str(item.get("report_id") or "").strip() != str((active or {}).get("report_id") or "").strip()
            and int(item.get("task_ref_total") or 0) <= 0
        ),
        None,
    )
    head_candidate = candidates[0] if candidates else None
    return {
        "enabled": enabled,
        "updated_at": updated_at,
        "candidate_total": len(candidates),
        "active_slot_busy": bool(active),
        "head_report_id": str((head_candidate or {}).get("report_id") or "").strip(),
        "active_report_id": str((active or {}).get("report_id") or "").strip(),
        "active_display_id": str((active or {}).get("display_id") or "").strip(),
        "active_summary": str((active or {}).get("defect_summary") or "").strip(),
        "active_task_priority": str((active or {}).get("task_priority") or "").strip(),
        "next_report_id": str((next_pending or {}).get("report_id") or "").strip(),
        "next_display_id": str((next_pending or {}).get("display_id") or "").strip(),
        "next_summary": str((next_pending or {}).get("defect_summary") or "").strip(),
        "next_task_priority": str((next_pending or {}).get("task_priority") or "").strip(),
        "next_reported_at": str((next_pending or {}).get("reported_at") or "").strip(),
    }


def _annotate_report_queue_state(
    report: dict[str, Any],
    *,
    queue_state: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(report or {})
    report_id = str(payload.get("report_id") or "").strip()
    task_ref_total = int(payload.get("task_ref_total") or 0)
    queue_eligible = str(payload.get("status") or "").strip().lower() in DEFECT_QUEUE_ELIGIBLE_STATUSES
    queue_enabled = bool(queue_state.get("enabled"))
    active_report_id = str(queue_state.get("active_report_id") or "").strip()
    next_report_id = str(queue_state.get("next_report_id") or "").strip()
    if queue_eligible and report_id and report_id == active_report_id:
        queue_mode = "active"
        queue_mode_text = "当前主动处理位"
    elif queue_eligible and not queue_enabled:
        queue_mode = "manual"
        queue_mode_text = "手动建单模式"
    elif queue_eligible and report_id and report_id == next_report_id:
        queue_mode = "next"
        queue_mode_text = "下一条待建单"
    elif queue_eligible:
        queue_mode = "queued"
        queue_mode_text = "排队中"
    else:
        queue_mode = "out_of_queue"
        queue_mode_text = "不在顺序建单队列"
    payload["queue_eligible"] = queue_eligible
    payload["has_task_chain"] = task_ref_total > 0
    payload["queue_mode"] = queue_mode
    payload["queue_mode_text"] = queue_mode_text
    return payload


def get_defect_queue_state(root: Path, *, include_test_data: bool = True) -> dict[str, Any]:
    return _defect_queue_state_payload(root, include_test_data=include_test_data)


def _defect_manual_task_gate(
    root: Path,
    report_id: str,
    *,
    include_test_data: bool = True,
) -> dict[str, Any]:
    queue_state = get_defect_queue_state(root, include_test_data=include_test_data)
    if not bool(queue_state.get("enabled")):
        return {"allowed": True, "queue": queue_state, "reason": "manual_mode"}
    active_report_id = str(queue_state.get("active_report_id") or "").strip()
    target_report_id = str(report_id or "").strip()
    if active_report_id and active_report_id != target_report_id:
        return {
            "allowed": False,
            "queue": queue_state,
            "reason": "active_slot_busy",
            "active_report_id": active_report_id,
        }
    head_report_id = str(queue_state.get("head_report_id") or "").strip()
    if not active_report_id and head_report_id and head_report_id != target_report_id:
        return {
            "allowed": False,
            "queue": queue_state,
            "reason": "not_queue_head",
            "head_report_id": head_report_id,
        }
    return {"allowed": True, "queue": queue_state, "reason": "queue_gate_pass"}


def set_defect_queue_mode(
    cfg: Any,
    *,
    enabled: bool,
) -> dict[str, Any]:
    root = Path(cfg.root)
    _ensure_defect_tables(root)
    now_text = _now_text()
    conn = connect_db(root)
    try:
        conn.execute("BEGIN")
        _ensure_defect_queue_settings_row(conn)
        conn.execute(
            """
            UPDATE defect_queue_settings
            SET sequential_task_creation_enabled=?, updated_at=?
            WHERE settings_id=?
            """,
            (1 if enabled else 0, now_text, DEFECT_QUEUE_SETTINGS_ID),
        )
        conn.commit()
    finally:
        conn.close()
    return get_defect_queue_state(root, include_test_data=True)


def ensure_defect_auto_queue(
    cfg: Any,
    *,
    include_test_data: bool = True,
) -> dict[str, Any]:
    root = Path(cfg.root)
    queue_state = get_defect_queue_state(root, include_test_data=include_test_data)
    if (not bool(queue_state.get("enabled"))) or bool(queue_state.get("active_slot_busy")):
        return queue_state
    head_report_id = str(queue_state.get("head_report_id") or "").strip()
    if not head_report_id:
        return queue_state
    detail = get_defect_detail(root, head_report_id, include_test_data=include_test_data)
    report = dict(detail.get("report") or {})
    status = str(report.get("status") or "").strip().lower()
    body = {"operator": "defect-auto-queue", "auto_queue": True}
    if status == DEFECT_STATUS_DISPUTE:
        create_defect_review_task(cfg, head_report_id, body, include_test_data=include_test_data)
    elif status == DEFECT_STATUS_UNRESOLVED:
        create_defect_process_task(cfg, head_report_id, body, include_test_data=include_test_data)
    return get_defect_queue_state(root, include_test_data=include_test_data)


def _next_dts_identity(conn: sqlite3.Connection) -> tuple[int, str]:
    row = conn.execute("SELECT COALESCE(MAX(dts_sequence), 0) + 1 AS next_sequence FROM defect_reports").fetchone()
    next_sequence = int(row["next_sequence"] if row is not None and row["next_sequence"] is not None else 1)
    return next_sequence, f"DTS-{next_sequence:05d}"


def _runtime_version_label() -> str:
    snapshot = runtime_upgrade_service.runtime_snapshot()
    current_version = str(snapshot.get("current_version") or "").strip()
    if current_version:
        return current_version
    current_rank = str(snapshot.get("current_version_rank") or "").strip()
    if current_rank:
        return current_rank
    env_version = str(os.getenv("WORKFLOW_RUNTIME_VERSION") or "").strip()
    if env_version:
        return env_version
    return "source-" + datetime.now().astimezone().strftime("%Y%m%d")


def _fallback_prejudge(report_text: str, images: list[dict[str, Any]]) -> dict[str, Any]:
    text = str(report_text or "").strip().lower()
    strong_hits = [token for token in ("bug", "异常", "报错", "失败", "无法", "崩溃", "卡死", "空白", "404", "500", "回退", "丢失", "不生效") if token in text]
    weak_hits = [token for token in ("显示", "错位", "慢", "超时", "刷新", "关闭", "升级", "路径", "进度条") if token in text]
    demand_hits = [token for token in ("需求", "建议", "优化", "新增", "希望", "想要") if token in text]
    score = len(strong_hits) * 2 + len(weak_hits) + (1 if images else 0)
    if demand_hits and not strong_hits and score < 3:
        score -= 2
    is_defect = score >= 2
    return {
        "decision_source": "fallback_rule",
        "decision": "defect" if is_defect else "not_defect",
        "title": "构成 workflow 缺陷" if is_defect else "当前不构成 workflow 缺陷",
        "summary": "命中异常/失败类线索，已按真实缺陷进入闭环。" if is_defect else "更像需求、建议或描述不足，先不进入正式缺陷链路。",
        "matched_rules": strong_hits + weak_hits + demand_hits,
        "confidence": "medium",
        "scored_images": len(images),
    }


def _available_agent_names(cfg: Any) -> list[str]:
    items: list[dict[str, Any]] = []
    fn = globals().get("list_available_agents")
    if callable(fn):
        try:
            items = fn(cfg, analyze_policy=False)
        except TypeError:
            try:
                items = fn(cfg)
            except Exception:
                items = []
        except Exception:
            items = []
    names = [str(item.get("agent_name") or item.get("agent_id") or "").strip() for item in items]
    names = [name for name in names if name]
    if names:
        return names
    conn = connect_db(Path(cfg.root))
    try:
        rows = conn.execute(
            """
            SELECT agent_name,agent_id,runtime_status
            FROM agent_registry
            WHERE COALESCE(runtime_status,'idle')<>'creating'
            ORDER BY updated_at DESC, agent_name ASC
            """
        ).fetchall()
        return [
            str(row["agent_name"] or row["agent_id"] or "").strip()
            for row in rows
            if str(row["agent_name"] or row["agent_id"] or "").strip()
        ]
    finally:
        conn.close()


def _default_assignee(cfg: Any) -> str:
    names = _available_agent_names(cfg)
    if not names:
        raise DefectCenterError(409, "no available agent for defect task", "defect_assignee_unavailable")
    for name in names:
        if str(name).strip().lower() == "workflow":
            return name
    return names[0]


class _DefectTaskRefEnricher:
    def __init__(self, root: Path, *, include_test_data: bool) -> None:
        self.root = Path(root)
        self.include_test_data = bool(include_test_data)
        self._snapshot_cache: dict[str, dict[str, Any]] = {}
        self._detail_cache: dict[tuple[str, str], dict[str, Any]] = {}

    def _snapshot(self, ticket_id: str) -> dict[str, Any]:
        cache_key = str(ticket_id or "").strip()
        cached = self._snapshot_cache.get(cache_key)
        if cached is not None:
            return cached
        snapshot = assignment_service._assignment_snapshot_from_files(
            self.root,
            cache_key,
            include_test_data=self.include_test_data,
            reconcile_running=True,
            include_scheduler=False,
            include_serialized_nodes=False,
        )
        self._snapshot_cache[cache_key] = snapshot
        return snapshot

    def _audit_refs(self, ticket_id: str, node_id: str) -> list[dict[str, Any]]:
        audit_refs = []
        for row in assignment_service._assignment_load_audit_records(
            self.root,
            ticket_id=ticket_id,
            node_id=node_id,
            limit=12,
        ):
            audit_refs.append(
                {
                    "audit_id": str(row.get("audit_id") or "").strip(),
                    "action": str(row.get("action") or "").strip(),
                    "operator": str(row.get("operator") or "").strip(),
                    "reason": str(row.get("reason") or "").strip(),
                    "target_status": str(row.get("target_status") or "").strip(),
                    "ref": str(row.get("ref") or "").strip(),
                    "created_at": str(row.get("created_at") or "").strip(),
                    "detail": dict(row.get("detail") or {}),
                }
            )
        return audit_refs

    def _detail_payload(self, ticket_id: str, node_id: str) -> dict[str, Any]:
        cache_key = (str(ticket_id or "").strip(), str(node_id or "").strip())
        cached = self._detail_cache.get(cache_key)
        if cached is not None:
            return cached
        snapshot = self._snapshot(cache_key[0])
        graph_row = dict(snapshot.get("graph_row") or {})
        selected_node = snapshot["node_map_by_id"].get(cache_key[1]) or (snapshot["nodes"][0] if snapshot["nodes"] else {})
        selected_serialized = (
            assignment_service._serialize_node(
                selected_node,
                node_map_by_id=snapshot["node_map_by_id"],
                upstream_map=snapshot["upstream_map"],
                downstream_map=snapshot["downstream_map"],
            )
            if selected_node
            else {}
        )
        blocking_reasons = list(selected_serialized.get("blocking_reasons") or [])
        available_actions = assignment_service._assignment_management_actions(
            selected_serialized,
            blocking_reasons=blocking_reasons,
        )
        if isinstance(selected_serialized, dict) and selected_serialized:
            selected_serialized["management_actions"] = list(available_actions)
        payload = {
            "graph_name": str(graph_row.get("graph_name") or graph_row.get("ticket_id") or "").strip(),
            "scheduler_state": str(graph_row.get("scheduler_state") or "").strip().lower(),
            "scheduler_state_text": assignment_service._scheduler_state_text(graph_row.get("scheduler_state") or "idle"),
            "selected_node": selected_serialized,
            "available_actions": list(available_actions),
            "audit_refs": self._audit_refs(
                cache_key[0],
                str(selected_serialized.get("node_id") or cache_key[1]).strip(),
            ) if selected_serialized else [],
            "blocking_reasons": blocking_reasons,
            "node_name": str(selected_serialized.get("node_name") or cache_key[1]).strip(),
            "node_status": str(selected_serialized.get("status") or "").strip(),
            "node_status_text": str(selected_serialized.get("status_text") or "").strip(),
        }
        self._detail_cache[cache_key] = payload
        return payload

    def enrich_row(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "ref_id": str(row.get("ref_id") or "").strip(),
            "report_id": str(row.get("report_id") or "").strip(),
            "ticket_id": str(row.get("ticket_id") or "").strip(),
            "focus_node_id": str(row.get("focus_node_id") or "").strip(),
            "action_kind": str(row.get("action_kind") or "").strip(),
            "title": str(row.get("title") or "").strip(),
            "external_request_id": str(row.get("external_request_id") or "").strip(),
            "created_at": str(row.get("created_at") or "").strip(),
            "updated_at": str(row.get("updated_at") or "").strip(),
            "graph_name": "",
            "scheduler_state": "",
            "scheduler_state_text": "",
            "node_name": "",
            "node_status": "",
            "node_status_text": "",
            "selected_node": {},
            "available_actions": [],
            "audit_refs": [],
            "blocking_reasons": [],
        }
        ticket_id = payload["ticket_id"]
        if not ticket_id:
            return payload
        try:
            payload.update(self._detail_payload(ticket_id, payload["focus_node_id"]))
        except Exception:
            if payload["focus_node_id"]:
                payload["node_name"] = payload["focus_node_id"]
        return payload


def _enrich_task_ref(root: Path, row: dict[str, Any], *, include_test_data: bool) -> dict[str, Any]:
    return _DefectTaskRefEnricher(root, include_test_data=include_test_data).enrich_row(row)


def _enrich_task_refs(root: Path, rows: list[dict[str, Any]], *, include_test_data: bool) -> list[dict[str, Any]]:
    enricher = _DefectTaskRefEnricher(root, include_test_data=include_test_data)
    return [enricher.enrich_row(item) for item in list(rows or [])]


def list_defect_reports(
    root: Path,
    *,
    include_test_data: bool = True,
    status_filter: str = "",
    keyword: str = "",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    _ensure_defect_tables(root)
    limit_value = max(1, min(200, int(limit or 100)))
    offset_value = max(0, int(offset or 0))
    status_key = str(status_filter or "").strip().lower()
    keyword_text = str(keyword or "").strip().lower()
    sql = " FROM defect_reports WHERE 1=1"
    params: list[Any] = []
    if not include_test_data:
        sql += " AND is_test_data=0"
    if status_key and status_key != "all":
        sql += " AND status=?"
        params.append(status_key)
    if keyword_text:
        keyword_like = f"%{keyword_text}%"
        sql += (
            " AND ("
            "LOWER(COALESCE(report_id,'')) LIKE ?"
            " OR LOWER(COALESCE(dts_id,'')) LIKE ?"
            " OR LOWER(COALESCE(defect_summary,'')) LIKE ?"
            " OR LOWER(COALESCE(report_text,'')) LIKE ?"
            " OR LOWER(COALESCE(current_decision_json,'')) LIKE ?"
            ")"
        )
        params.extend([keyword_like] * 5)
    conn = connect_db(root)
    try:
        total_row = conn.execute("SELECT COUNT(*) AS total" + sql, tuple(params)).fetchone()
        total = int(total_row["total"] if total_row is not None and total_row["total"] is not None else 0)
        page_rows = conn.execute(
            "SELECT *" + sql + _defect_order_by_sql() + " LIMIT ? OFFSET ?",
            (*params, limit_value, offset_value),
        ).fetchall()
        count_map = _load_task_ref_counts(conn, [str(row["report_id"] or "").strip() for row in page_rows])
    finally:
        conn.close()
    queue_state = get_defect_queue_state(root, include_test_data=include_test_data)
    items = [
        _annotate_report_queue_state(
            _report_row_to_payload({**dict(row), "task_ref_total": count_map.get(str(row["report_id"] or "").strip(), 0)}),
            queue_state=queue_state,
        )
        for row in page_rows
    ]
    returned = len(items)
    next_offset = offset_value + returned
    return {
        "items": items,
        "total": total,
        "returned": returned,
        "offset": offset_value,
        "limit": limit_value,
        "next_offset": next_offset,
        "has_more": next_offset < total,
        "status_filter": status_key,
        "keyword": keyword_text,
        "queue": queue_state,
    }


def get_defect_detail(
    root: Path,
    report_id: str,
    *,
    include_test_data: bool = True,
) -> dict[str, Any]:
    _ensure_defect_tables(root)
    report_key = _require_report_id(report_id)
    conn = connect_db(root)
    try:
        row = _load_report_row(conn, report_key, include_test_data=include_test_data)
        task_ref_rows = _load_task_ref_rows(conn, report_key)
        report = _report_row_to_payload({**dict(row), "task_ref_total": len(task_ref_rows)})
        history = _load_history_rows(conn, report_key)
        task_refs = _enrich_task_refs(root, task_ref_rows, include_test_data=include_test_data)
    finally:
        conn.close()
    queue_state = get_defect_queue_state(root, include_test_data=include_test_data)
    report = _annotate_report_queue_state(report, queue_state=queue_state)
    queue_enabled = bool(queue_state.get("enabled"))
    return {
        "report": report,
        "history": history,
        "task_refs": task_refs,
        "history_total": len(history),
        "task_ref_total": len(task_refs),
        "queue": queue_state,
        "show_re_review_input": report["status"] in {DEFECT_STATUS_DISPUTE, DEFECT_STATUS_RESOLVED, DEFECT_STATUS_NOT_FORMAL},
        "can_process": (not queue_enabled) and bool(report["is_formal"]) and report["status"] in {DEFECT_STATUS_UNRESOLVED, DEFECT_STATUS_DISPUTE},
        "can_review": (not queue_enabled) and report["status"] in {DEFECT_STATUS_DISPUTE, DEFECT_STATUS_RESOLVED, DEFECT_STATUS_NOT_FORMAL},
        "can_close": report["status"] == DEFECT_STATUS_RESOLVED,
    }


def get_defect_history(
    root: Path,
    report_id: str,
    *,
    include_test_data: bool = True,
) -> dict[str, Any]:
    detail = get_defect_detail(root, report_id, include_test_data=include_test_data)
    return {
        "report_id": str(detail["report"]["report_id"]),
        "history": list(detail["history"]),
        "total": len(detail["history"]),
        "queue": dict(detail.get("queue") or {}),
    }


def _write_report_update(
    conn: sqlite3.Connection,
    report_id: str,
    *,
    status: str | None = None,
    is_formal: bool | None = None,
    task_priority: str | None = None,
    reported_at: str | None = None,
    discovered_iteration: str | None = None,
    resolved_version: str | None = None,
    current_decision: dict[str, Any] | None = None,
    updated_at: str | None = None,
) -> None:
    row = _load_report_row(conn, report_id, include_test_data=True)
    next_status = str(status if status is not None else row["status"] or "").strip().lower()
    next_is_formal = bool(row["is_formal"] if is_formal is None else is_formal)
    next_task_priority = _normalize_task_priority(
        task_priority if task_priority is not None else row["task_priority"],
        default=DEFECT_DEFAULT_TASK_PRIORITY,
    )
    next_reported_at = _normalize_reported_at(
        reported_at if reported_at is not None else row["reported_at"],
        fallback=str(row["created_at"] or "").strip(),
    )
    next_discovered = str(row["discovered_iteration"] or "").strip() if discovered_iteration is None else str(discovered_iteration or "").strip()
    next_resolved = str(row["resolved_version"] or "").strip() if resolved_version is None else str(resolved_version or "").strip()
    next_decision = _json_loads_object(row["current_decision_json"]) if current_decision is None else dict(current_decision or {})
    conn.execute(
        """
        UPDATE defect_reports
        SET status=?, is_formal=?, task_priority=?, reported_at=?, discovered_iteration=?, resolved_version=?, current_decision_json=?, updated_at=?
        WHERE report_id=?
        """,
        (
            next_status,
            1 if next_is_formal else 0,
            next_task_priority,
            next_reported_at,
            next_discovered,
            next_resolved,
            _json_dumps(next_decision, "{}"),
            str(updated_at or _now_text()),
            report_id,
        ),
    )


def _formalize_report_if_needed(
    conn: sqlite3.Connection,
    report_id: str,
    *,
    actor: str,
    decision_title: str,
    decision_summary: str,
) -> dict[str, Any]:
    row = _load_report_row(conn, report_id, include_test_data=True)
    discovered_iteration = str(row["discovered_iteration"] or "").strip() or _runtime_version_label()
    dts_sequence, dts_id = _next_dts_identity(conn) if not str(row["dts_id"] or "").strip() else (int(row["dts_sequence"] or 0), str(row["dts_id"] or "").strip())
    if not str(row["dts_id"] or "").strip():
        conn.execute("UPDATE defect_reports SET dts_sequence=?, dts_id=? WHERE report_id=?", (dts_sequence, dts_id, report_id))
    current_decision = _json_loads_object(row["current_decision_json"])
    current_decision.update(
        {
            "decision_source": str(current_decision.get("decision_source") or "manual").strip() or "manual",
            "decision": "defect",
            "title": str(decision_title or "已转为正式缺陷").strip(),
            "summary": str(decision_summary or "").strip(),
            "formalized_at": _now_text(),
        }
    )
    _write_report_update(
        conn,
        report_id,
        is_formal=True,
        discovered_iteration=discovered_iteration,
        current_decision=current_decision,
    )
    _append_history(
        conn,
        report_id,
        entry_type="formalized",
        actor=actor,
        title="缺陷已转为正式记录",
        detail={"dts_id": dts_id, "dts_sequence": dts_sequence, "discovered_iteration": discovered_iteration},
    )
    return {"dts_id": dts_id, "dts_sequence": dts_sequence, "discovered_iteration": discovered_iteration}


from .defect_service_record_commands import (  # noqa: E402
    append_defect_images,
    append_defect_text,
    create_defect_report,
    mark_defect_dispute,
    update_defect_status,
    write_defect_resolved_version,
)
from .defect_service_task_commands import (  # noqa: E402
    create_defect_process_task,
    create_defect_review_task,
    repair_defect_assignment_state,
)
