from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from . import work_record_store as _store


_INDEX_SCHEMA_VERSION = 2
_INDEX_DIR_NAME = ".index"
_INDEX_DB_NAME = "index.db"
_PREVIEW_LIMIT = 200


def sqlite_index_root(root: Path) -> Path:
    return _store.artifact_root(root) / _INDEX_DIR_NAME


def sqlite_index_path(root: Path) -> Path:
    return sqlite_index_root(root) / _INDEX_DB_NAME


def _connect(root: Path) -> sqlite3.Connection:
    sqlite_index_root(root).mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(sqlite_index_path(root), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _preview(value: Any, limit: int = _PREVIEW_LIMIT) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def _read_jsonl_with_lines(path: Path) -> list[tuple[int, dict[str, Any]]]:
    rows: list[tuple[int, dict[str, Any]]] = []
    if not path.exists() or not path.is_file():
        return rows
    try:
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            text = str(line or "").strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except Exception:
                continue
            if isinstance(payload, dict):
                rows.append((line_no, payload))
    except Exception:
        return []
    return rows


def _artifact_relpath(root: Path, path: Path | str) -> str:
    raw_path = Path(path).resolve(strict=False)
    base = _store.artifact_root(root).resolve(strict=False)
    try:
        return raw_path.relative_to(base).as_posix()
    except Exception:
        return ""


def _ref_relpath(root: Path, ref: str) -> str:
    normalized = _store.normalize_work_record_ref(root, ref)
    if not normalized:
        return ""
    return _artifact_relpath(root, normalized)


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _content_hash(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        size = int(path.stat().st_size or 0)
        if size > 1024 * 1024:
            return ""
        return hashlib.sha1(path.read_bytes()).hexdigest()
    except Exception:
        return ""


def _touch_source(
    conn: sqlite3.Connection,
    root: Path,
    path: Path,
    *,
    record_kind: str,
    entity_type: str,
    entity_id: str,
    parent_id: str = "",
) -> None:
    relpath = _artifact_relpath(root, path)
    if not relpath:
        return
    stat = path.stat() if path.exists() else None
    conn.execute(
        """
        INSERT INTO source_file_registry (
            source_relpath,record_kind,entity_type,entity_id,parent_id,
            source_mtime_ns,source_size_bytes,content_hash,indexed_at,last_seen_at,is_deleted
        ) VALUES (?,?,?,?,?,?,?,?,?,?,0)
        ON CONFLICT(source_relpath) DO UPDATE SET
            record_kind=excluded.record_kind,
            entity_type=excluded.entity_type,
            entity_id=excluded.entity_id,
            parent_id=excluded.parent_id,
            source_mtime_ns=excluded.source_mtime_ns,
            source_size_bytes=excluded.source_size_bytes,
            content_hash=excluded.content_hash,
            indexed_at=excluded.indexed_at,
            last_seen_at=excluded.last_seen_at,
            is_deleted=0
        """,
        (
            relpath,
            record_kind,
            entity_type,
            entity_id,
            parent_id,
            int(stat.st_mtime_ns) if stat else 0,
            int(stat.st_size) if stat else 0,
            _content_hash(path),
            _store._now_ts(),
            _store._now_ts(),
        ),
    )


def _mark_prefix_deleted(conn: sqlite3.Connection, prefix: str) -> None:
    conn.execute(
        """
        UPDATE source_file_registry
        SET is_deleted=1,last_seen_at=?
        WHERE source_relpath LIKE ?
        """,
        (_store._now_ts(), f"{str(prefix or '').strip()}%"),
    )


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS index_meta (
            meta_key TEXT PRIMARY KEY,
            meta_value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS source_file_registry (
            source_relpath TEXT PRIMARY KEY,
            record_kind TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            parent_id TEXT NOT NULL,
            source_mtime_ns INTEGER NOT NULL DEFAULT 0,
            source_size_bytes INTEGER NOT NULL DEFAULT 0,
            content_hash TEXT NOT NULL DEFAULT '',
            indexed_at TEXT NOT NULL DEFAULT '',
            last_seen_at TEXT NOT NULL DEFAULT '',
            is_deleted INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS task_index (
            ticket_id TEXT PRIMARY KEY,
            scheduler_state TEXT NOT NULL DEFAULT '',
            graph_name TEXT NOT NULL DEFAULT '',
            source_workflow TEXT NOT NULL DEFAULT '',
            summary_preview TEXT NOT NULL DEFAULT '',
            is_test_data INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT '',
            node_count INTEGER NOT NULL DEFAULT 0,
            running_node_count INTEGER NOT NULL DEFAULT 0,
            success_node_count INTEGER NOT NULL DEFAULT 0,
            failed_node_count INTEGER NOT NULL DEFAULT 0,
            blocked_node_count INTEGER NOT NULL DEFAULT 0,
            task_relpath TEXT NOT NULL DEFAULT '',
            task_structure_relpath TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS task_node_index (
            ticket_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT '',
            assigned_agent_id TEXT NOT NULL DEFAULT '',
            delivery_mode TEXT NOT NULL DEFAULT '',
            artifact_delivery_status TEXT NOT NULL DEFAULT '',
            priority INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT '',
            completed_at TEXT NOT NULL DEFAULT '',
            node_name TEXT NOT NULL DEFAULT '',
            assigned_agent_name TEXT NOT NULL DEFAULT '',
            expected_artifact_preview TEXT NOT NULL DEFAULT '',
            success_reason_preview TEXT NOT NULL DEFAULT '',
            failure_reason_preview TEXT NOT NULL DEFAULT '',
            result_ref_relpath TEXT NOT NULL DEFAULT '',
            upstream_count INTEGER NOT NULL DEFAULT 0,
            downstream_count INTEGER NOT NULL DEFAULT 0,
            artifact_count INTEGER NOT NULL DEFAULT 0,
            node_relpath TEXT NOT NULL DEFAULT '',
            artifact_output_dir_relpath TEXT NOT NULL DEFAULT '',
            artifact_delivery_dir_relpath TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (ticket_id, node_id)
        );

        CREATE TABLE IF NOT EXISTS assignment_run_index (
            run_id TEXT PRIMARY KEY,
            ticket_id TEXT NOT NULL DEFAULT '',
            node_id TEXT NOT NULL DEFAULT '',
            provider TEXT NOT NULL DEFAULT '',
            workspace_path TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT '',
            command_summary TEXT NOT NULL DEFAULT '',
            result_summary TEXT NOT NULL DEFAULT '',
            latest_event TEXT NOT NULL DEFAULT '',
            latest_event_at TEXT NOT NULL DEFAULT '',
            exit_code INTEGER NOT NULL DEFAULT 0,
            started_at TEXT NOT NULL DEFAULT '',
            finished_at TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT '',
            run_relpath TEXT NOT NULL DEFAULT '',
            prompt_relpath TEXT NOT NULL DEFAULT '',
            stdout_relpath TEXT NOT NULL DEFAULT '',
            stderr_relpath TEXT NOT NULL DEFAULT '',
            result_json_relpath TEXT NOT NULL DEFAULT '',
            result_md_relpath TEXT NOT NULL DEFAULT '',
            events_relpath TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS session_index (
            session_id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT '',
            agent_name TEXT NOT NULL DEFAULT '',
            agents_version TEXT NOT NULL DEFAULT '',
            is_test_data INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT '',
            last_message_at TEXT NOT NULL DEFAULT '',
            message_count INTEGER NOT NULL DEFAULT 0,
            work_record_count INTEGER NOT NULL DEFAULT 0,
            last_message_preview TEXT NOT NULL DEFAULT '',
            session_relpath TEXT NOT NULL DEFAULT '',
            messages_relpath TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS conversation_message_index (
            session_id TEXT NOT NULL,
            message_id INTEGER NOT NULL,
            role TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT '',
            analysis_state TEXT NOT NULL DEFAULT '',
            analysis_run_id TEXT NOT NULL DEFAULT '',
            analysis_updated_at TEXT NOT NULL DEFAULT '',
            content_preview TEXT NOT NULL DEFAULT '',
            content_length INTEGER NOT NULL DEFAULT 0,
            source_relpath TEXT NOT NULL DEFAULT '',
            source_line_no INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (session_id, message_id)
        );

        CREATE TABLE IF NOT EXISTS analysis_index (
            analysis_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT '',
            decision TEXT NOT NULL DEFAULT '',
            workflow_id TEXT NOT NULL DEFAULT '',
            workflow_status TEXT NOT NULL DEFAULT '',
            training_id TEXT NOT NULL DEFAULT '',
            training_status TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT '',
            decision_reason_preview TEXT NOT NULL DEFAULT '',
            analysis_summary_preview TEXT NOT NULL DEFAULT '',
            analysis_recommendation_preview TEXT NOT NULL DEFAULT '',
            latest_analysis_run_id TEXT NOT NULL DEFAULT '',
            train_result_summary TEXT NOT NULL DEFAULT '',
            analysis_relpath TEXT NOT NULL DEFAULT '',
            workflow_relpath TEXT NOT NULL DEFAULT '',
            training_relpath TEXT NOT NULL DEFAULT '',
            workflow_events_relpath TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS analysis_run_index (
            analysis_run_id TEXT PRIMARY KEY,
            analysis_id TEXT NOT NULL DEFAULT '',
            workflow_id TEXT NOT NULL DEFAULT '',
            session_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT '',
            plan_item_count INTEGER NOT NULL DEFAULT 0,
            context_message_count INTEGER NOT NULL DEFAULT 0,
            target_message_count INTEGER NOT NULL DEFAULT 0,
            no_value_reason TEXT NOT NULL DEFAULT '',
            error_text_preview TEXT NOT NULL DEFAULT '',
            analysis_run_relpath TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS task_run_index (
            task_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL DEFAULT '',
            agent_name TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT '',
            start_at TEXT NOT NULL DEFAULT '',
            end_at TEXT NOT NULL DEFAULT '',
            duration_ms INTEGER NOT NULL DEFAULT 0,
            summary_preview TEXT NOT NULL DEFAULT '',
            run_relpath TEXT NOT NULL DEFAULT '',
            stdout_relpath TEXT NOT NULL DEFAULT '',
            stderr_relpath TEXT NOT NULL DEFAULT '',
            trace_relpath TEXT NOT NULL DEFAULT '',
            events_relpath TEXT NOT NULL DEFAULT '',
            summary_relpath TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS audit_index (
            audit_key TEXT PRIMARY KEY,
            audit_type TEXT NOT NULL DEFAULT '',
            session_id TEXT NOT NULL DEFAULT '',
            analysis_id TEXT NOT NULL DEFAULT '',
            ticket_id TEXT NOT NULL DEFAULT '',
            node_id TEXT NOT NULL DEFAULT '',
            action TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT '',
            operator TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT '',
            reason_preview TEXT NOT NULL DEFAULT '',
            manual_fallback INTEGER NOT NULL DEFAULT 0,
            ref_relpath TEXT NOT NULL DEFAULT '',
            source_relpath TEXT NOT NULL DEFAULT '',
            source_line_no INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS ingress_request_index (
            request_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL DEFAULT '',
            route TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT '',
            event_logged INTEGER NOT NULL DEFAULT 0,
            source_relpath TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS event_index (
            event_key TEXT PRIMARY KEY,
            stream_type TEXT NOT NULL DEFAULT '',
            ticket_id TEXT NOT NULL DEFAULT '',
            node_id TEXT NOT NULL DEFAULT '',
            run_id TEXT NOT NULL DEFAULT '',
            task_id TEXT NOT NULL DEFAULT '',
            session_id TEXT NOT NULL DEFAULT '',
            analysis_id TEXT NOT NULL DEFAULT '',
            workflow_id TEXT NOT NULL DEFAULT '',
            event_type TEXT NOT NULL DEFAULT '',
            level TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT '',
            message_preview TEXT NOT NULL DEFAULT '',
            detail_preview TEXT NOT NULL DEFAULT '',
            related_status TEXT NOT NULL DEFAULT '',
            source_relpath TEXT NOT NULL DEFAULT '',
            source_line_no INTEGER NOT NULL DEFAULT 0,
            run_relpath TEXT NOT NULL DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_task_index_updated_at ON task_index(updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_task_node_status ON task_node_index(ticket_id,status,updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_assignment_run_ticket_node ON assignment_run_index(ticket_id,node_id,created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_session_index_status ON session_index(status,last_message_at DESC);
        CREATE INDEX IF NOT EXISTS idx_message_index_session ON conversation_message_index(session_id,message_id);
        CREATE INDEX IF NOT EXISTS idx_analysis_index_session ON analysis_index(session_id,updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_analysis_run_index_analysis ON analysis_run_index(analysis_id,created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_task_run_index_session ON task_run_index(session_id,created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_audit_index_lookup ON audit_index(audit_type,session_id,ticket_id,created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_ingress_request_index_created_at ON ingress_request_index(created_at DESC, route, event_logged);
        CREATE INDEX IF NOT EXISTS idx_event_index_lookup ON event_index(stream_type,session_id,ticket_id,analysis_id,created_at DESC);
        """
    )
    conn.execute(
        """
        INSERT INTO index_meta(meta_key, meta_value) VALUES ('schema_version', ?)
        ON CONFLICT(meta_key) DO UPDATE SET meta_value=excluded.meta_value
        """,
        (str(_INDEX_SCHEMA_VERSION),),
    )


def _clear_index_tables(conn: sqlite3.Connection) -> None:
    for table in (
        "source_file_registry",
        "task_index",
        "task_node_index",
        "assignment_run_index",
        "session_index",
        "conversation_message_index",
        "analysis_index",
        "analysis_run_index",
        "task_run_index",
        "audit_index",
        "ingress_request_index",
        "event_index",
    ):
        conn.execute(f"DELETE FROM {table}")


def _set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO index_meta(meta_key, meta_value) VALUES (?, ?)
        ON CONFLICT(meta_key) DO UPDATE SET meta_value=excluded.meta_value
        """,
        (key, value),
    )


def _read_meta(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute("SELECT meta_value FROM index_meta WHERE meta_key=?", (key,)).fetchone()
    return str(row["meta_value"] or "") if row else ""


def _load_json_index(path: Path) -> dict[str, Any]:
    payload = _store._load_json_dict(path)
    items = payload.get("items")
    if not isinstance(items, list):
        payload["items"] = []
    return payload


def _write_json_index(path: Path, items: list[dict[str, Any]]) -> None:
    _store._write_json(path, {"generated_at": _store._now_ts(), "items": items})


def _upsert_json_index_item(path: Path, key: str, item: dict[str, Any]) -> None:
    payload = _load_json_index(path)
    items = [row for row in list(payload.get("items") or []) if str(row.get(key) or "") != str(item.get(key) or "")]
    items.append(dict(item))
    items.sort(
        key=lambda row: (
            str(row.get("updated_at") or row.get("created_at") or row.get("completed_at") or ""),
            str(row.get(key) or ""),
        ),
        reverse=True,
    )
    _write_json_index(path, items)


def _remove_json_index_item(path: Path, key: str, value: str) -> None:
    payload = _load_json_index(path)
    items = [row for row in list(payload.get("items") or []) if str(row.get(key) or "") != str(value or "")]
    _write_json_index(path, items)


def _write_records_manifest(root: Path) -> None:
    _store._write_json(
        _store.records_index_path(root),
        {
            "generated_at": _store._now_ts(),
            "structure_file": _store.work_records_structure_path(root).as_posix(),
            "sessions_index": _store.sessions_index_path(root).as_posix(),
            "analysis_index": _store.analysis_index_path(root).as_posix(),
            "runs_index": _store.runs_index_path(root).as_posix(),
            "policy_patch_index": _store.policy_patch_index_path(root).as_posix(),
            "sqlite_index": sqlite_index_path(root).as_posix(),
        },
    )


def _session_summary(record: dict[str, Any]) -> dict[str, Any]:
    item = dict(record)
    item.pop("policy_snapshot_json", None)
    return item


def _analysis_summary(analysis: dict[str, Any], workflow: dict[str, Any], training: dict[str, Any]) -> dict[str, Any]:
    return {
        "analysis_id": str(analysis.get("analysis_id") or ""),
        "session_id": str(analysis.get("session_id") or ""),
        "status": str(analysis.get("status") or ""),
        "decision": str(analysis.get("decision") or ""),
        "updated_at": str(analysis.get("updated_at") or ""),
        "workflow_id": str(workflow.get("workflow_id") or ""),
        "workflow_status": str(workflow.get("status") or workflow.get("workflow_status") or ""),
        "training_id": str(training.get("training_id") or ""),
        "training_status": str(training.get("status") or ""),
    }


def _run_summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": str(record.get("task_id") or ""),
        "session_id": str(record.get("session_id") or ""),
        "agent_name": str(record.get("agent_name") or ""),
        "status": str(record.get("status") or ""),
        "created_at": str(record.get("created_at") or ""),
        "updated_at": str(record.get("updated_at") or ""),
    }


def _policy_patch_summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "patch_task_id": str(record.get("patch_task_id") or ""),
        "status": str(record.get("status") or ""),
        "source_session_id": str(record.get("source_session_id") or ""),
        "confirmation_audit_id": int(record.get("confirmation_audit_id") or 0),
        "agent_name": str(record.get("agent_name") or ""),
        "agents_version": str(record.get("agents_version") or ""),
        "created_at": str(record.get("created_at") or ""),
        "updated_at": str(record.get("updated_at") or ""),
        "completed_at": str(record.get("completed_at") or ""),
    }


def _structure_markdown(root: Path) -> str:
    base = _store.artifact_root(root).resolve(strict=False)
    records = _store.records_root(root).resolve(strict=False)
    return "\n".join(
        [
            "# 工作记录目录结构说明",
            "",
            "该文件由 workflow 自动维护。",
            "任务中心之外的会话、分析、运行、审计和系统级工作记录统一落在本目录契约中。",
            "",
            "## 当前配置",
            f"- 任务产物路径: {base.as_posix()}",
            f"- 工作记录根目录: {records.as_posix()}",
            f"- 顶层入口索引: {_store.records_index_path(root).as_posix()}",
            f"- 会话索引: {_store.sessions_index_path(root).as_posix()}",
            f"- 分析索引: {_store.analysis_index_path(root).as_posix()}",
            f"- 运行索引: {_store.runs_index_path(root).as_posix()}",
            f"- SQLite 辅助索引: {sqlite_index_path(root).as_posix()}",
            "",
            "## 稳定目录契约",
            "- `<任务产物路径>/tasks/<ticket_id>/...`: 任务中心任务图、节点、执行链路与产物。",
            "- `<任务产物路径>/records/sessions/<session_id>/session.json`: 会话头信息与索引字段。",
            "- `<任务产物路径>/records/sessions/<session_id>/messages.jsonl`: 会话消息与分析状态。",
            "- `<任务产物路径>/records/analysis/<analysis_id>/analysis.json`: 分析任务主记录。",
            "- `<任务产物路径>/records/analysis/<analysis_id>/workflow.json`: 工作记录与训练编排状态。",
            "- `<任务产物路径>/records/analysis/<analysis_id>/runs/<analysis_run_id>.json`: 单次分析运行记录。",
            "- `<任务产物路径>/records/analysis/<analysis_id>/workflow-events.jsonl`: 分析/计划/执行链路事件。",
            "- `<任务产物路径>/records/runs/<task_id>/run.json`: 会话任务运行头信息。",
            "- `<任务产物路径>/records/runs/<task_id>/{stdout.txt,stderr.txt,trace.json,events.log,summary.md}`: 会话任务执行证据。",
            "- `<任务产物路径>/records/audit/message-delete.jsonl`: 消息删除审计。",
            "- `<任务产物路径>/records/audit/policy-confirmation.jsonl`: 策略确认审计。",
            "- `<任务产物路径>/records/audit/policy-patch-tasks/*.json`: 策略补丁任务记录。",
            "- `<任务产物路径>/records/system/workflow-events.jsonl`: 全局工作事件留痕。",
            f"- `<任务产物路径>/{_INDEX_DIR_NAME}/{_INDEX_DB_NAME}`: 只读辅助索引层，丢失后可由文件重建。",
            "",
            "## 使用规则",
            "- `workflow/state/`、`workflow/.runtime/state/`、`workflow/logs/` 不再持久化用户工作记录明文。",
            "- 页面刷新或服务重启后，工作记录页签应从本目录动态加载。",
            "- 其他 agent 做工作记录分析时，先看本文件，再看顶层入口索引和 SQLite 辅助索引契约。",
        ]
    ).strip() + "\n"


def write_structure_file(root: Path) -> Path:
    path = _store.work_records_structure_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_structure_markdown(root), encoding="utf-8")
    return path


