from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from . import work_record_store_index as _record_index
from .work_record_store import (
    _STORE_LOCK,
    _SCHEMA_VERSION,
    _append_jsonl,
    _append_markdown,
    _load_json_dict,
    _load_jsonl,
    _normalize_bool,
    _now_ts,
    _write_json,
    _write_jsonl,
    change_log_path,
    ensure_store,
    failure_cases_path,
    ingress_requests_path,
    list_session_records,
    message_delete_audit_path,
    normalize_work_record_ref,
    policy_confirmation_audit_path,
    policy_patch_task_path,
    policy_patch_tasks_root,
    reconcile_runs_path,
    system_runs_root,
    web_e2e_path,
    workflow_events_path,
)


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


def append_message_delete_audit_record(root: Path, payload: dict[str, Any]) -> int:
    ensure_store(root)
    with _STORE_LOCK:
        rows = _load_jsonl(message_delete_audit_path(root))
        audit_id = len(rows) + 1
        row = dict(payload or {})
        row["ref"] = normalize_work_record_ref(root, str(row.get("ref") or ""))
        row["audit_id"] = audit_id
        rows.append(row)
        _write_jsonl(message_delete_audit_path(root), rows)
        _record_index.append_message_delete_audit_index(root, row)
        return audit_id


def append_policy_confirmation_audit_record(root: Path, payload: dict[str, Any]) -> int:
    ensure_store(root)
    with _STORE_LOCK:
        rows = _load_jsonl(policy_confirmation_audit_path(root))
        audit_id = len(rows) + 1
        row = dict(payload or {})
        row["ref"] = normalize_work_record_ref(root, str(row.get("ref") or ""))
        row["audit_id"] = audit_id
        rows.append(row)
        _write_jsonl(policy_confirmation_audit_path(root), rows)
        _record_index.append_policy_confirmation_audit_index(root, row)
        return audit_id


def create_policy_patch_task_record(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_store(root)
    patch_task_id = str(payload.get("patch_task_id") or "").strip()
    if not patch_task_id:
        raise RuntimeError("patch_task_id required")
    record = {"record_type": "policy_patch_task", "schema_version": _SCHEMA_VERSION, **dict(payload or {})}
    _write_json(policy_patch_task_path(root, patch_task_id), record)
    _record_index.sync_policy_patch_task(root, patch_task_id)
    return record


def list_policy_patch_task_records(root: Path, limit: int = 200) -> list[dict[str, Any]]:
    ensure_store(root)
    rows = _record_index.list_policy_patch_task_records_from_index(root, limit=limit)
    if rows:
        return rows
    fallback = [
        _load_json_dict(path)
        for path in sorted(policy_patch_tasks_root(root).glob("*.json"), key=lambda item: item.as_posix().lower())
    ]
    fallback = [row for row in fallback if row]
    fallback.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return fallback[: max(1, min(int(limit), 2000))]


def latest_policy_patch_task_for_session(root: Path, session_id: str) -> str:
    lookup = str(session_id or "").strip()
    for row in list_policy_patch_task_records(root, limit=20000):
        if str(row.get("source_session_id") or "") == lookup:
            return str(row.get("patch_task_id") or "")
    return ""


def policy_closure_stats_record(root: Path) -> dict[str, Any]:
    return _record_index.policy_closure_stats_from_index(root)


def append_workflow_event_log_record(root: Path, payload: dict[str, Any]) -> None:
    ensure_store(root)
    row = dict(payload or {})
    row["ref"] = normalize_work_record_ref(root, str(row.get("ref") or ""))
    _append_jsonl(workflow_events_path(root), row)
    _record_index.append_system_workflow_event_index(root, row)


def list_workflow_event_log_records(root: Path) -> list[dict[str, Any]]:
    ensure_store(root)
    return _load_jsonl(workflow_events_path(root))


def append_change_log_record(root: Path, title: str, detail: str) -> None:
    _append_markdown(change_log_path(root), "# Change Log", [f"## {_now_ts()} - {title}", f"- {detail}"])


def append_failure_case_record(root: Path, title: str, detail: str) -> None:
    _append_markdown(failure_cases_path(root), "# Failure Cases", [f"## {_now_ts()} - {title}", f"- detail: {detail}"])


def append_web_e2e_record(root: Path, lines: list[str]) -> str:
    _append_markdown(web_e2e_path(root), "# Web E2E", lines)
    return web_e2e_path(root).as_posix()


def unique_system_run_path(root: Path, prefix: str) -> Path:
    ts = datetime.now().astimezone()
    path = system_runs_root(root) / f"{prefix}-{ts.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def record_ingress_request(root: Path, payload: dict[str, Any]) -> None:
    ensure_store(root)
    _record_index.upsert_ingress_request_index(root, dict(payload or {}))


def mark_ingress_request_logged(root: Path, request_id: str) -> None:
    ensure_store(root)
    _record_index.mark_ingress_request_logged_index(root, request_id)


def list_ingress_request_records(root: Path) -> list[dict[str, Any]]:
    indexed_rows = _record_index.list_ingress_request_records_from_index(root, limit=0)
    if indexed_rows:
        return indexed_rows
    current = _load_json_dict(ingress_requests_path(root))
    items = current.get("items") if isinstance(current.get("items"), dict) else {}
    rows = [dict(item) for item in items.values()]
    rows.sort(key=lambda item: str(item.get("created_at") or ""))
    return rows


def pending_counts_indexed(root: Path, *, include_test_data: bool) -> tuple[int, int]:
    return _record_index.pending_counts_from_index(root, include_test_data=include_test_data)


def latest_results_indexed(root: Path, *, include_test_data: bool) -> tuple[str, str]:
    return _record_index.latest_results_from_index(root, include_test_data=include_test_data)


def new_sessions_24h_indexed(
    root: Path,
    *,
    include_test_data: bool,
    since: str,
    routes: tuple[str, ...],
) -> int:
    return _record_index.new_sessions_24h_from_index(
        root,
        include_test_data=include_test_data,
        since=since,
        routes=routes,
    )


def append_reconcile_run_record(root: Path, payload: dict[str, Any]) -> None:
    ensure_store(root)
    row = dict(payload or {})
    row["ref"] = normalize_work_record_ref(root, str(row.get("ref") or ""))
    _append_jsonl(reconcile_runs_path(root), row)
    ref = str(row.get("ref") or "")
    if ref:
        ref_path = Path(ref)
        if ref_path.suffix.lower() == ".md":
            _write_system_run_stub(
                ref_path,
                row,
            )
    _record_index.append_reconcile_run_index(root, row)


def latest_reconcile_run_record(root: Path) -> dict[str, Any] | None:
    rows = _load_jsonl(reconcile_runs_path(root))
    return rows[-1] if rows else None
