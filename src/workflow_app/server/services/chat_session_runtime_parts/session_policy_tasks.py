
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .work_record_store import (
    delete_session_message_record,
    list_policy_patch_task_records,
    list_session_message_records,
    list_workflow_records,
    session_work_record_count,
)


def list_agent_policy_patch_tasks(root: Path, limit: int = 200) -> list[dict[str, Any]]:
    rows = list_policy_patch_task_records(root, limit=max(1, min(int(limit), 2000)))
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            payload = json.loads(str(item.get("policy_json") or "{}"))
            item["policy"] = payload if isinstance(payload, dict) else {}
        except Exception:
            item["policy"] = {}
        out.append(item)
    return out


def latest_workflow_for_session(root: Path, session_id: str) -> dict[str, str]:
    rows = [
        dict(item)
        for item in list_workflow_records(root)
        if str(item.get("session_id") or "") == str(session_id or "")
    ]
    rows.sort(
        key=lambda item: (
            str(item.get("updated_at") or ""),
            str(item.get("created_at") or ""),
        ),
        reverse=True,
    )
    row = rows[0] if rows else {}
    return {
        "workflow_id": str(row.get("workflow_id") or ""),
        "analysis_id": str(row.get("analysis_id") or ""),
        "analysis_run_id": str(row.get("latest_analysis_run_id") or ""),
    }


def delete_session_message_with_gate(
    root: Path,
    session_id: str,
    message_id: int,
    *,
    operator: str,
) -> dict[str, Any]:
    workflow_meta = latest_workflow_for_session(root, session_id)
    workflow_id = str(workflow_meta.get("workflow_id") or "")
    analysis_run_id_text = str(workflow_meta.get("analysis_run_id") or "")
    ref = relative_to_root(root, event_file(root))
    training_plan_items = session_training_plan_item_count(root, session_id)

    row = next(
        (
            item
            for item in list_session_message_records(root, session_id)
            if int(item.get("message_id") or 0) == int(message_id)
        ),
        None,
    )
    if not row:
        raise WorkflowGateError(404, "message not found", "message_not_found")
    role = str(row.get("role") or "")
    if role not in {"user", "assistant"}:
        raise WorkflowGateError(400, "only user/assistant message can be deleted", "message_role_not_supported")

    if training_plan_items > 0:
        audit_id = add_message_delete_audit(
            root,
            operator=operator,
            session_id=session_id,
            message_id=int(message_id),
            status="rejected",
            reason_code="conversation_locked_by_training_plan",
            reason_text="会话已生成训练计划，禁止删除聊天记录",
            impact_scope="none",
            workflow_id=workflow_id,
            analysis_run_id_text=analysis_run_id_text,
            training_plan_items=training_plan_items,
            ref=ref,
        )
        persist_event(
            root,
            {
                "event_id": event_id(),
                "timestamp": iso_ts(now_local()),
                "session_id": session_id,
                "actor": "workflow",
                "stage": "governance",
                "action": "message_delete",
                "status": "failed",
                "latency_ms": 0,
                "task_id": workflow_id,
                "reason_tags": [
                    "conversation_locked_by_training_plan",
                    f"message_id:{int(message_id)}",
                    f"operator:{operator}",
                    f"audit_id:{audit_id}",
                ],
                "ref": ref,
            },
        )
        raise WorkflowGateError(
            409,
            "会话已生成训练计划，禁止删除聊天记录",
            "conversation_locked_by_training_plan",
            extra={
                "workflow_id": workflow_id,
                "training_plan_items": training_plan_items,
                "audit_id": audit_id,
            },
        )

    if not delete_session_message_record(root, session_id, int(message_id)):
        raise WorkflowGateError(404, "message not found", "message_not_found")
    remain = session_work_record_count(root, session_id)

    audit_id = add_message_delete_audit(
        root,
        operator=operator,
        session_id=session_id,
        message_id=int(message_id),
        status="success",
        reason_code="message_deleted",
        reason_text="删除成功",
        impact_scope="single_message",
        workflow_id=workflow_id,
        analysis_run_id_text=analysis_run_id_text,
        training_plan_items=training_plan_items,
        ref=ref,
    )
    persist_event(
        root,
        {
            "event_id": event_id(),
            "timestamp": iso_ts(now_local()),
            "session_id": session_id,
            "actor": "workflow",
            "stage": "governance",
            "action": "message_delete",
            "status": "success",
            "latency_ms": 0,
            "task_id": workflow_id,
            "reason_tags": [
                "message_deleted",
                f"message_id:{int(message_id)}",
                f"operator:{operator}",
                f"audit_id:{audit_id}",
            ],
            "ref": ref,
        },
    )
    sync_analysis_tasks(root)
    sync_training_workflows(root)
    return {
        "session_id": session_id,
        "message_id": int(message_id),
        "audit_id": audit_id,
        "remaining_work_records": remain,
        "training_plan_items": training_plan_items,
        "workflow_id": workflow_id,
    }
