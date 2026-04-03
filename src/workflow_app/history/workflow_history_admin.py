#!/usr/bin/env python3
from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ..server.services.work_record_store import (
    _load_json_dict,
    _load_jsonl,
    _write_json,
    _write_jsonl,
    analysis_dir,
    analysis_record_path,
    analysis_root,
    analysis_workflow_events_path,
    artifact_root,
    get_training_task_record,
    ingress_requests_path,
    list_analysis_records,
    list_session_message_records,
    list_session_records,
    list_task_run_event_records,
    list_task_run_records,
    list_workflow_records,
    message_delete_audit_path,
    policy_confirmation_audit_path,
    run_dir,
    session_dir,
    workflow_events_path,
)


def _delete_path(path: Path) -> bool:
    if not path.exists():
        return False
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)
    return True


def _rewrite_jsonl(path: Path, keep: list[dict[str, Any]]) -> int:
    existing = _load_jsonl(path)
    removed = max(0, len(existing) - len(keep))
    if removed <= 0:
        return 0
    if keep:
        _write_jsonl(path, keep)
    elif path.exists():
        path.unlink(missing_ok=True)
    return removed


def _remove_session_from_ingress(root: Path, session_id: str) -> int:
    current = _load_json_dict(ingress_requests_path(root))
    items = current.get("items") if isinstance(current.get("items"), dict) else {}
    next_items = {
        key: value
        for key, value in items.items()
        if str((value or {}).get("session_id") or "") != str(session_id or "")
    }
    removed = max(0, len(items) - len(next_items))
    if removed > 0:
        _write_json(ingress_requests_path(root), {"updated_at": datetime.now().astimezone().isoformat(timespec="seconds"), "items": next_items})
    return removed


def _remove_session_from_global_events(
    root: Path,
    session_id: str,
    *,
    task_ids: set[str],
    analysis_ids: set[str],
    workflow_ids: set[str],
) -> int:
    rows = _load_jsonl(workflow_events_path(root))
    keep: list[dict[str, Any]] = []
    removed = 0
    for row in rows:
        row_session_id = str(row.get("session_id") or "")
        row_task_id = str(row.get("task_id") or "")
        if row_session_id == session_id or row_task_id in task_ids or row_task_id in analysis_ids or row_task_id in workflow_ids:
            removed += 1
            continue
        keep.append(row)
    if removed > 0:
        _rewrite_jsonl(workflow_events_path(root), keep)
    return removed


def _remove_session_from_audit(root: Path, session_id: str) -> tuple[int, int]:
    delete_rows = [row for row in _load_jsonl(message_delete_audit_path(root)) if str(row.get("session_id") or "") != session_id]
    confirm_rows = [row for row in _load_jsonl(policy_confirmation_audit_path(root)) if str(row.get("session_id") or "") != session_id]
    deleted_delete_audit = _rewrite_jsonl(message_delete_audit_path(root), delete_rows)
    deleted_confirmation = _rewrite_jsonl(policy_confirmation_audit_path(root), confirm_rows)
    return deleted_delete_audit, deleted_confirmation


def delete_session_history(root: Path, session_id: str, *, delete_artifacts: bool = True) -> dict[str, Any]:
    session_id = str(session_id or "").strip()
    if not session_id:
        raise RuntimeError("session_id required")

    session = next((item for item in list_session_records(root, include_test_data=True, limit=100000) if str(item.get("session_id") or "") == session_id), None)
    if not session:
        raise RuntimeError("session not found")

    task_runs = list_task_run_records(root, session_id=session_id, limit=100000)
    task_ids = {str(item.get("task_id") or "") for item in task_runs if str(item.get("task_id") or "")}
    analyses = [item for item in list_analysis_records(root) if str(item.get("session_id") or "") == session_id]
    analysis_ids = {str(item.get("analysis_id") or "") for item in analyses if str(item.get("analysis_id") or "")}
    workflows = [
        item
        for item in list_workflow_records(root)
        if str(item.get("session_id") or "") == session_id or str(item.get("analysis_id") or "") in analysis_ids
    ]
    workflow_ids = {str(item.get("workflow_id") or "") for item in workflows if str(item.get("workflow_id") or "")}

    result = {
        "session_id": session_id,
        "deleted_chat_sessions": 0,
        "deleted_messages": len(list_session_message_records(root, session_id)),
        "deleted_events": 0,
        "deleted_ingress": 0,
        "deleted_analysis_tasks": 0,
        "deleted_training_tasks": 0,
        "deleted_workflows": 0,
        "deleted_workflow_events": 0,
        "deleted_task_runs": 0,
        "deleted_task_events": 0,
        "deleted_artifacts": 0,
    }

    for run in task_runs:
        task_id = str(run.get("task_id") or "")
        if not task_id:
            continue
        result["deleted_task_events"] += len(list_task_run_event_records(root, task_id, since_id=0, limit=100000))
        if _delete_path(run_dir(root, task_id)):
            result["deleted_task_runs"] += 1
            if delete_artifacts:
                result["deleted_artifacts"] += 1

    for analysis in analyses:
        analysis_id = str(analysis.get("analysis_id") or "")
        if not analysis_id:
            continue
        training = get_training_task_record(root, analysis_id) or {}
        if training:
            result["deleted_training_tasks"] += 1
        result["deleted_workflow_events"] += len(_load_jsonl(analysis_workflow_events_path(root, analysis_id)))
        workflow_path = analysis_dir(root, analysis_id) / "workflow.json"
        if workflow_path.exists():
            result["deleted_workflows"] += 1
        if _delete_path(analysis_dir(root, analysis_id)):
            result["deleted_analysis_tasks"] += 1
            if delete_artifacts:
                result["deleted_artifacts"] += 1

    result["deleted_ingress"] = _remove_session_from_ingress(root, session_id)
    result["deleted_events"] = _remove_session_from_global_events(
        root,
        session_id,
        task_ids=task_ids,
        analysis_ids=analysis_ids,
        workflow_ids=workflow_ids,
    )
    deleted_delete_audit, deleted_confirmation = _remove_session_from_audit(root, session_id)
    result["deleted_events"] += deleted_delete_audit + deleted_confirmation

    if _delete_path(session_dir(root, session_id)):
        result["deleted_chat_sessions"] = 1
        if delete_artifacts:
            result["deleted_artifacts"] += 1

    return result


def delete_training_content(root: Path, workflow_id: str, *, delete_artifacts: bool = True) -> dict[str, Any]:
    workflow_id = str(workflow_id or "").strip()
    if not workflow_id:
        raise RuntimeError("workflow_id required")

    workflow = next((item for item in list_workflow_records(root) if str(item.get("workflow_id") or "") == workflow_id), None)
    if not workflow:
        raise RuntimeError("workflow not found")

    analysis_id = str(workflow.get("analysis_id") or "")
    session_id = str(workflow.get("session_id") or "")
    training_record = get_training_task_record(root, analysis_id) or {}
    analysis_record = _load_json_dict(analysis_record_path(root, analysis_id))
    workflow_path = analysis_dir(root, analysis_id) / "workflow.json"
    training_path = analysis_dir(root, analysis_id) / "training.json"
    runs_path = analysis_dir(root, analysis_id) / "runs"
    events_path = analysis_workflow_events_path(root, analysis_id)

    deleted_workflow_events = len(_load_jsonl(events_path))
    deleted_artifacts = 0
    if _delete_path(events_path) and delete_artifacts:
        deleted_artifacts += 1
    if _delete_path(runs_path) and delete_artifacts:
        deleted_artifacts += 1
    deleted_workflows = 1 if _delete_path(workflow_path) else 0
    deleted_training_tasks = 1 if _delete_path(training_path) else 0
    if delete_artifacts and deleted_workflows:
        deleted_artifacts += 1
    if delete_artifacts and deleted_training_tasks:
        deleted_artifacts += 1

    if analysis_record:
        analysis_record["status"] = "pending"
        analysis_record["decision"] = ""
        analysis_record["decision_reason"] = ""
        analysis_record["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        _write_json(analysis_record_path(root, analysis_id), analysis_record)

    return {
        "workflow_id": workflow_id,
        "analysis_id": analysis_id,
        "session_id": session_id,
        "deleted_training_tasks": deleted_training_tasks if training_record or deleted_training_tasks else 0,
        "deleted_workflow_events": deleted_workflow_events,
        "deleted_workflows": deleted_workflows,
        "deleted_events": 0,
        "deleted_artifacts": deleted_artifacts,
        "analysis_reset": 1 if analysis_record else 0,
    }


def cleanup_history(
    root: Path,
    *,
    mode: str = "closed_sessions",
    delete_artifacts: bool = True,
    delete_log_files: bool = False,
    max_age_hours: int = 168,
    include_active_test_sessions: bool = False,
) -> dict[str, Any]:
    mode_text = str(mode or "").strip().lower()
    if mode_text not in {"closed_sessions", "all", "test_data"}:
        raise RuntimeError("invalid cleanup mode")

    result: dict[str, Any] = {
        "mode": mode_text,
        "deleted_sessions": 0,
        "deleted_workflows": 0,
        "deleted_logs": 0,
    }

    sessions = list_session_records(root, include_test_data=True, limit=100000)

    if mode_text == "closed_sessions":
        session_ids = [str(item.get("session_id") or "") for item in sessions if str(item.get("status") or "") == "closed"]
        for session_id in session_ids:
            delete_session_history(root, session_id, delete_artifacts=delete_artifacts)
            result["deleted_sessions"] += 1
        return result

    if mode_text == "test_data":
        cutoff_hours = max(0, int(max_age_hours or 0))
        now_ts = datetime.now().astimezone()
        cutoff_dt = now_ts - timedelta(hours=cutoff_hours)
        candidates: list[str] = []
        skipped_active = 0
        skipped_recent = 0
        skipped_invalid_ts = 0
        for row in sessions:
            if not bool(row.get("is_test_data")):
                continue
            session_id = str(row.get("session_id") or "").strip()
            if not session_id:
                continue
            status = str(row.get("status") or "active").strip().lower() or "active"
            if (not include_active_test_sessions) and status == "active":
                skipped_active += 1
                continue
            if cutoff_hours > 0:
                created_text = str(row.get("created_at") or "").strip()
                try:
                    created_dt = datetime.fromisoformat(created_text)
                    if created_dt.tzinfo is None:
                        created_dt = created_dt.replace(tzinfo=now_ts.tzinfo)
                    created_dt = created_dt.astimezone(now_ts.tzinfo)
                except Exception:
                    skipped_invalid_ts += 1
                    continue
                if created_dt > cutoff_dt:
                    skipped_recent += 1
                    continue
            candidates.append(session_id)

        for session_id in candidates:
            try:
                delete_session_history(root, session_id, delete_artifacts=delete_artifacts)
                result["deleted_sessions"] += 1
            except RuntimeError:
                continue

        result["candidate_sessions"] = len(candidates)
        result["max_age_hours"] = cutoff_hours
        result["include_active_test_sessions"] = bool(include_active_test_sessions)
        result["skipped_active"] = skipped_active
        result["skipped_recent"] = skipped_recent
        result["skipped_invalid_ts"] = skipped_invalid_ts
        return result

    session_ids = [str(item.get("session_id") or "") for item in sessions if str(item.get("session_id") or "")]
    for session_id in session_ids:
        try:
            delete_session_history(root, session_id, delete_artifacts=delete_artifacts)
            result["deleted_sessions"] += 1
        except RuntimeError:
            continue

    if delete_log_files:
        for rel in ["logs/events", "logs/decisions", "logs/runs", "logs/summaries"]:
            folder = root / rel
            if not folder.exists():
                continue
            for item in folder.iterdir():
                if item.is_file():
                    item.unlink(missing_ok=True)
                    result["deleted_logs"] += 1
                elif item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                    result["deleted_logs"] += 1
    result["deleted_workflows"] = result["deleted_sessions"]
    return result
