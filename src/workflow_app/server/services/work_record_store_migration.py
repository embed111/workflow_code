from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
from typing import Any

from . import work_record_store as _work_record_store
from .work_record_store import (
    _load_json_dict,
    _load_jsonl,
    _parse_json_dict,
    _parse_json_list,
    _refresh_session_counters,
    _write_json,
    _write_jsonl,
    analysis_run_record_path,
    append_task_run_event_record,
    append_workflow_event_record,
    artifact_root,
    change_log_path,
    create_analysis_run_record,
    create_or_load_session_record,
    create_task_run_record,
    daily_summary_path,
    ensure_store,
    ensure_workflow_record,
    failure_cases_path,
    list_session_message_records,
    message_delete_audit_path,
    normalize_work_record_ref,
    policy_confirmation_audit_path,
    rebuild_record_indexes,
    replace_analysis_run_plan_items_record,
    reconcile_runs_path,
    run_events_path,
    run_record_path,
    session_snapshot_path,
    session_messages_path,
    upsert_analysis_record,
    upsert_training_task_record,
    update_task_run_result_files,
    workflow_events_path,
)
from .work_record_store_system import (
    append_reconcile_run_record,
    append_workflow_event_log_record,
    create_policy_patch_task_record,
    record_ingress_request,
)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    try:
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (str(table or ""),)).fetchone()
        return row is not None
    except Exception:
        return False


def _session_message_rows_from_db(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    try:
        rows = conn.execute(
            """
            SELECT
                message_id,session_id,role,content,created_at,
                COALESCE(analysis_state,'') AS analysis_state,
                COALESCE(analysis_reason,'') AS analysis_reason,
                COALESCE(analysis_run_id,'') AS analysis_run_id,
                COALESCE(analysis_updated_at,'') AS analysis_updated_at
            FROM conversation_messages
            WHERE session_id=?
            ORDER BY message_id ASC
            """,
            (session_id,),
        ).fetchall()
    except Exception:
        return []
    return [{key: row[key] for key in row.keys()} for row in rows]


def _drop_legacy_tables(conn: sqlite3.Connection) -> None:
    for table in (
        "task_events",
        "task_runs",
        "training_workflow_events",
        "training_workflows",
        "training_tasks",
        "analysis_run_plan_items",
        "analysis_runs",
        "analysis_tasks",
        "conversation_messages",
        "chat_sessions",
        "conversation_events",
        "ingress_requests",
        "message_delete_audit",
        "policy_confirmation_audit",
        "agent_policy_patch_tasks",
        "reconcile_runs",
    ):
        conn.execute(f"DROP TABLE IF EXISTS {table}")


def _append_or_remove_markdown(src: Path, dst: Path) -> None:
    if not src.exists() or not src.is_file():
        return
    text = src.read_text(encoding="utf-8")
    if not text.strip():
        src.unlink(missing_ok=True)
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        shutil.move(src.as_posix(), dst.as_posix())
        return
    with dst.open("a", encoding="utf-8") as handle:
        handle.write("\n\n")
        handle.write(f"<!-- imported from {src.as_posix()} -->\n")
        handle.write(text.rstrip() + "\n")
    src.unlink(missing_ok=True)


def _cleanup_local_runtime_files(source_root: Path, root: Path) -> None:
    _append_or_remove_markdown(source_root / "state" / "change-log.md", change_log_path(root))
    _append_or_remove_markdown(source_root / "state" / "session-snapshot.md", session_snapshot_path(root))
    _append_or_remove_markdown(source_root / "logs" / "summaries" / "daily-summary.md", daily_summary_path(root))
    _append_or_remove_markdown(source_root / "logs" / "summaries" / "failure-cases.md", failure_cases_path(root))

    for rel in ("logs/events", "logs/decisions", "logs/runs"):
        src = source_root / rel
        if src.exists():
            shutil.rmtree(src, ignore_errors=True)

    for rel in ("logs/summaries", "logs", "state"):
        src = source_root / rel
        if src.exists() and src.is_dir():
            try:
                next(src.iterdir())
            except StopIteration:
                src.rmdir()
            except Exception:
                continue

    legacy_root = artifact_root(root) / "records" / "system" / "legacy-local"
    if legacy_root.exists():
        shutil.rmtree(legacy_root, ignore_errors=True)


def _write_system_run_stub(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# 系统运行记录", ""]
    for key in ("run_id", "run_at", "reason", "status", "notes"):
        value = str(payload.get(key) or "").strip()
        if value:
            lines.append(f"- {key}: {value}")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def normalize_external_work_record_refs(root: Path) -> dict[str, int]:
    ensure_store(root)
    result = {
        "run_records": 0,
        "run_events": 0,
        "workflow_events": 0,
        "reconcile_runs": 0,
        "policy_confirmation": 0,
    }

    for path in (artifact_root(root) / "records" / "runs").glob("*/run.json"):
        record = _load_json_dict(path)
        if not record:
            continue
        task_id = str(record.get("task_id") or path.parent.name)
        normalized_ref = normalize_work_record_ref(root, str(record.get("ref") or ""), task_id=task_id)
        if normalized_ref and normalized_ref != str(record.get("ref") or ""):
            record["ref"] = normalized_ref
            _write_json(path, record)
            result["run_records"] += 1

    for path in (artifact_root(root) / "records" / "runs").glob("*/events.log"):
        rows = _load_jsonl(path)
        changed = False
        task_id = path.parent.name
        for row in rows:
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else None
            if not payload or not payload.get("ref"):
                continue
            normalized_ref = normalize_work_record_ref(root, str(payload.get("ref") or ""), task_id=task_id)
            if normalized_ref != str(payload.get("ref") or ""):
                payload["ref"] = normalized_ref
                row["payload"] = payload
                changed = True
        if changed:
            _write_jsonl(path, rows)
            result["run_events"] += 1

    for path_key, result_key in (
        (workflow_events_path(root), "workflow_events"),
        (policy_confirmation_audit_path(root), "policy_confirmation"),
    ):
        rows = _load_jsonl(path_key)
        changed = False
        for row in rows:
            normalized_ref = normalize_work_record_ref(root, str(row.get("ref") or ""))
            if normalized_ref != str(row.get("ref") or ""):
                row["ref"] = normalized_ref
                changed = True
        if changed:
            _write_jsonl(path_key, rows)
            result[result_key] += 1

    rows = _load_jsonl(reconcile_runs_path(root))
    changed = False
    for row in rows:
        original_ref = str(row.get("ref") or "")
        normalized_ref = normalize_work_record_ref(root, original_ref)
        if normalized_ref != original_ref:
            row["ref"] = normalized_ref
            changed = True
        if normalized_ref:
            ref_path = Path(normalized_ref)
            if ref_path.suffix.lower() == ".md":
                _write_system_run_stub(ref_path, row)
    if changed:
        _write_jsonl(reconcile_runs_path(root), rows)
        result["reconcile_runs"] += 1

    legacy_root = artifact_root(root) / "records" / "system" / "legacy-local"
    if legacy_root.exists():
        shutil.rmtree(legacy_root, ignore_errors=True)
    return result


def migrate_legacy_local_work_records(root: Path) -> dict[str, Any]:
    ensure_store(root)
    current = Path(root).resolve(strict=False)
    source_roots: list[Path] = []
    candidates = [current]
    if current.name == ".runtime":
        candidates.append(current.parent.resolve(strict=False))
    else:
        candidates.append((current / ".runtime").resolve(strict=False))
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.as_posix()
        if key in seen:
            continue
        seen.add(key)
        source_roots.append(candidate)
    result = {"migrated_roots": [], "migrated_sessions": 0, "migrated_runs": 0, "migrated_analyses": 0}
    original_rebuild = _work_record_store.rebuild_record_indexes
    _work_record_store.rebuild_record_indexes = lambda _root: None
    try:
        for source_root in source_roots:
            db_path = source_root / "state" / "workflow.db"
            if not db_path.exists():
                continue
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                for row in conn.execute("SELECT * FROM chat_sessions").fetchall() if _table_exists(conn, "chat_sessions") else []:
                    payload = {key: row[key] for key in row.keys()}
                    session, _created = create_or_load_session_record(root, payload)
                    messages = _session_message_rows_from_db(conn, str(payload.get("session_id") or ""))
                    existing = {int(item.get("message_id") or 0) for item in list_session_message_records(root, str(payload.get("session_id") or ""))}
                    if messages:
                        merged = list_session_message_records(root, str(payload.get("session_id") or ""))
                        for message in messages:
                            if int(message.get("message_id") or 0) in existing:
                                continue
                            merged.append(dict(message))
                        merged.sort(key=lambda item: int(item.get("message_id") or 0))
                        _write_jsonl(session_messages_path(root, str(payload.get("session_id") or "")), merged)
                        _refresh_session_counters(root, str(payload.get("session_id") or ""), session)
                    result["migrated_sessions"] += 1
                for row in conn.execute("SELECT * FROM analysis_tasks").fetchall() if _table_exists(conn, "analysis_tasks") else []:
                    payload = {key: row[key] for key in row.keys()}
                    upsert_analysis_record(root, str(payload.get("analysis_id") or ""), payload)
                    result["migrated_analyses"] += 1
                for row in conn.execute("SELECT * FROM training_workflows").fetchall() if _table_exists(conn, "training_workflows") else []:
                    payload = {key: row[key] for key in row.keys()}
                    ensure_workflow_record(root, str(payload.get("workflow_id") or ""), payload)
                for row in conn.execute("SELECT * FROM analysis_runs").fetchall() if _table_exists(conn, "analysis_runs") else []:
                    payload = {key: row[key] for key in row.keys()}
                    existing = analysis_run_record_path(root, str(payload.get("analysis_id") or ""), str(payload.get("analysis_run_id") or ""))
                    if existing.exists():
                        continue
                    create_analysis_run_record(root, payload)
                if _table_exists(conn, "analysis_run_plan_items"):
                    grouped: dict[str, list[dict[str, Any]]] = {}
                    for row in conn.execute("SELECT * FROM analysis_run_plan_items ORDER BY created_at ASC").fetchall():
                        item = {key: row[key] for key in row.keys()}
                        grouped.setdefault(str(item.get("analysis_run_id") or ""), []).append(
                            {
                                "plan_item_id": str(item.get("plan_item_id") or ""),
                                "item_id": str(item.get("item_key") or ""),
                                "title": str(item.get("title") or ""),
                                "kind": str(item.get("kind") or ""),
                                "decision": str(item.get("decision") or ""),
                                "description": str(item.get("description") or ""),
                                "message_ids": _parse_json_list(item.get("message_ids_json")),
                                "selected": bool(item.get("selected")),
                            }
                        )
                    for run_id, items in grouped.items():
                        replace_analysis_run_plan_items_record(root, run_id, items)
                for row in conn.execute("SELECT * FROM training_tasks").fetchall() if _table_exists(conn, "training_tasks") else []:
                    payload = {key: row[key] for key in row.keys()}
                    upsert_training_task_record(root, str(payload.get("analysis_id") or ""), payload)
                for row in conn.execute("SELECT * FROM training_workflow_events ORDER BY event_id ASC").fetchall() if _table_exists(conn, "training_workflow_events") else []:
                    item = {key: row[key] for key in row.keys()}
                    append_workflow_event_record(
                        root,
                        str(item.get("workflow_id") or ""),
                        {
                            "created_at": str(item.get("created_at") or ""),
                            "workflow_id": str(item.get("workflow_id") or ""),
                            "analysis_id": str(item.get("analysis_id") or ""),
                            "session_id": str(item.get("session_id") or ""),
                            "stage": str(item.get("stage") or ""),
                            "status": str(item.get("status") or ""),
                            "payload": _parse_json_dict(item.get("payload_json")),
                        },
                    )
                for row in conn.execute("SELECT * FROM task_runs").fetchall() if _table_exists(conn, "task_runs") else []:
                    payload = {key: row[key] for key in row.keys()}
                    record = create_task_run_record(root, payload)
                    task_id = str(record.get("task_id") or "")
                    update_task_run_result_files(
                        root,
                        task_id,
                        stdout_text=str(payload.get("stdout") or ""),
                        stderr_text=str(payload.get("stderr") or ""),
                    )
                    result["migrated_runs"] += 1
                for row in conn.execute("SELECT * FROM task_events ORDER BY event_id ASC").fetchall() if _table_exists(conn, "task_events") else []:
                    payload = {key: row[key] for key in row.keys()}
                    append_task_run_event_record(
                        root,
                        str(payload.get("task_id") or ""),
                        {
                            "timestamp": str(payload.get("timestamp") or ""),
                            "event_type": str(payload.get("event_type") or ""),
                            "payload": _parse_json_dict(payload.get("payload_json")),
                        },
                    )
                for row in conn.execute("SELECT * FROM conversation_events ORDER BY timestamp ASC").fetchall() if _table_exists(conn, "conversation_events") else []:
                    append_workflow_event_log_record(root, {key: row[key] for key in row.keys()})
                for row in conn.execute("SELECT * FROM ingress_requests").fetchall() if _table_exists(conn, "ingress_requests") else []:
                    record_ingress_request(root, {key: row[key] for key in row.keys()})
                if _table_exists(conn, "message_delete_audit"):
                    rows = _load_jsonl(message_delete_audit_path(root))
                    existing_ids = {int(item.get("audit_id") or 0) for item in rows}
                    for row in conn.execute("SELECT * FROM message_delete_audit ORDER BY audit_id ASC").fetchall():
                        payload = {key: row[key] for key in row.keys()}
                        if int(payload.get("audit_id") or 0) in existing_ids:
                            continue
                        rows.append(payload)
                    _write_jsonl(message_delete_audit_path(root), rows)
                if _table_exists(conn, "policy_confirmation_audit"):
                    rows = _load_jsonl(policy_confirmation_audit_path(root))
                    existing_ids = {int(item.get("audit_id") or 0) for item in rows}
                    for row in conn.execute("SELECT * FROM policy_confirmation_audit ORDER BY audit_id ASC").fetchall():
                        payload = {key: row[key] for key in row.keys()}
                        if int(payload.get("audit_id") or 0) in existing_ids:
                            continue
                        rows.append(payload)
                    _write_jsonl(policy_confirmation_audit_path(root), rows)
                for row in conn.execute("SELECT * FROM agent_policy_patch_tasks").fetchall() if _table_exists(conn, "agent_policy_patch_tasks") else []:
                    payload = {key: row[key] for key in row.keys()}
                    create_policy_patch_task_record(root, payload)
                for row in conn.execute("SELECT * FROM reconcile_runs ORDER BY run_at ASC").fetchall() if _table_exists(conn, "reconcile_runs") else []:
                    append_reconcile_run_record(root, {key: row[key] for key in row.keys()})
                _drop_legacy_tables(conn)
                conn.commit()
            finally:
                conn.close()
            _cleanup_local_runtime_files(source_root, root)
            result["migrated_roots"].append(source_root.as_posix())
    finally:
        _work_record_store.rebuild_record_indexes = original_rebuild
    normalize_external_work_record_refs(root)
    rebuild_record_indexes(root)
    return result
