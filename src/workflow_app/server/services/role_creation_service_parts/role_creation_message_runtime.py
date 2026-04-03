from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any


def _persist_role_creation_dialogue_fields(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    dialogue_agent_name: str,
    dialogue_agent_workspace_path: str,
    dialogue_provider: str,
    trace_ref: str,
    updated_at: str,
    stage_key: str = "",
    stage_index: int = 0,
) -> None:
    if stage_key:
        conn.execute(
            """
            UPDATE role_creation_sessions
            SET dialogue_agent_name=?,dialogue_agent_workspace_path=?,dialogue_provider=?,last_dialogue_trace_ref=?,
                current_stage_key=?,current_stage_index=?,updated_at=?
            WHERE session_id=?
            """,
            (
                dialogue_agent_name,
                dialogue_agent_workspace_path,
                dialogue_provider,
                trace_ref,
                stage_key,
                stage_index,
                updated_at,
                session_id,
            ),
        )
        return
    conn.execute(
        """
        UPDATE role_creation_sessions
        SET dialogue_agent_name=?,dialogue_agent_workspace_path=?,dialogue_provider=?,last_dialogue_trace_ref=?,updated_at=?
        WHERE session_id=?
        """,
        (
            dialogue_agent_name,
            dialogue_agent_workspace_path,
            dialogue_provider,
            trace_ref,
            updated_at,
            session_id,
        ),
    )


def _pick_role_creation_turn_stage_key(
    *,
    session_summary: dict[str, Any],
    analyst_turn: dict[str, Any],
    created_tasks: list[dict[str, Any]],
) -> str:
    if _normalize_session_status(session_summary.get("status")) != "creating":
        return ""
    candidate = str(analyst_turn.get("suggested_stage_key") or "").strip().lower()
    if candidate not in ROLE_CREATION_ANALYST_STAGE_KEYS:
        candidate = ""
    if not candidate and created_tasks:
        candidate = str(created_tasks[-1].get("stage_key") or "").strip().lower()
    if candidate in {"", "workspace_init", "complete_creation"}:
        return ""
    if candidate not in ROLE_CREATION_STAGE_BY_KEY:
        return ""
    if candidate == str(session_summary.get("current_stage_key") or "").strip().lower():
        return ""
    return candidate


def _append_role_creation_scheduler_message(
    root: Path,
    *,
    session_id: str,
    content: str,
    meta: dict[str, Any],
) -> None:
    conn = connect_db(root)
    try:
        conn.execute("BEGIN")
        _append_message(
            conn,
            session_id=session_id,
            role="system",
            content=content,
            attachments=[],
            message_type="system_task_update",
            meta=meta,
        )
        conn.commit()
    finally:
        conn.close()


def _resume_role_creation_scheduler(
    cfg: Any,
    *,
    session_id: str,
    ticket_id: str,
    operator: str,
) -> dict[str, Any]:
    try:
        result = assignment_service.resume_assignment_scheduler(
            cfg.root,
            ticket_id_text=ticket_id,
            operator=operator,
            include_test_data=True,
        )
    except Exception as exc:
        _append_role_creation_scheduler_message(
            cfg.root,
            session_id=session_id,
            content="任务图已生成，但自动调度启动失败。",
            meta={
                "assignment_ticket_id": ticket_id,
                "scheduler_state": "idle",
                "scheduler_error": str(exc),
            },
        )
        return {}
    dispatched = list(result.get("dispatch_result", {}).get("dispatched") or [])
    if dispatched:
        _append_role_creation_scheduler_message(
            cfg.root,
            session_id=session_id,
            content="已启动后台任务：" + "；".join(
                [
                    str(item.get("node_name") or item.get("task_name") or item.get("node_id") or "").strip()
                    for item in dispatched[:3]
                    if str(item.get("node_name") or item.get("task_name") or item.get("node_id") or "").strip()
                ]
            ),
            meta={
                "assignment_ticket_id": ticket_id,
                "scheduler_state": "running",
                "task_ids": [
                    str(item.get("node_id") or "").strip()
                    for item in dispatched
                    if str(item.get("node_id") or "").strip()
                ],
                "dispatch_result": result.get("dispatch_result") or {},
            },
        )
    return result


def _dispatch_role_creation_scheduler(
    cfg: Any,
    *,
    ticket_id: str,
    operator: str,
) -> dict[str, Any]:
    try:
        return assignment_service.dispatch_assignment_next(
            cfg.root,
            ticket_id_text=ticket_id,
            operator=operator,
            include_test_data=True,
        )
    except Exception:
        return {}


def _finalize_role_creation_message_processing_failure(
    cfg: Any,
    *,
    session_id: str,
    message_ids: list[str],
    batch_id: str,
    operator: str,
    error_text: str,
    dialogue_error: str = "",
    trace_ref: str = "",
    dialogue_agent_name: str = "",
    dialogue_agent_workspace_path: str = "",
    dialogue_provider: str = "",
) -> None:
    session_key = safe_token(session_id, "", 160)
    if not session_key:
        return
    normalized_error = _normalize_text(error_text, max_len=2000) or "未知错误"
    normalized_dialogue_error = _normalize_text(dialogue_error, max_len=200) or normalized_error
    normalized_trace_ref = str(trace_ref or "").strip()
    normalized_dialogue_agent_name = str(dialogue_agent_name or "").strip()
    normalized_dialogue_agent_workspace_path = str(dialogue_agent_workspace_path or "").strip()
    normalized_dialogue_provider = str(dialogue_provider or ROLE_CREATION_ANALYST_PROVIDER).strip() or ROLE_CREATION_ANALYST_PROVIDER
    now_text = _tc_now_text()
    conn = connect_db(cfg.root)
    try:
        conn.execute("BEGIN")
        try:
            _fetch_session_row(conn, session_key)
        except TrainingCenterError as exc:
            if str(getattr(exc, "code", "") or "").strip() == "role_creation_session_not_found":
                conn.rollback()
                return
            raise
        if (
            normalized_trace_ref
            or normalized_dialogue_agent_name
            or normalized_dialogue_agent_workspace_path
            or normalized_dialogue_provider
        ):
            _persist_role_creation_dialogue_fields(
                conn,
                session_id=session_key,
                dialogue_agent_name=normalized_dialogue_agent_name,
                dialogue_agent_workspace_path=normalized_dialogue_agent_workspace_path,
                dialogue_provider=normalized_dialogue_provider,
                trace_ref=normalized_trace_ref,
                updated_at=now_text,
            )
        _update_role_creation_user_message_processing_state(
            conn,
            session_id=session_key,
            message_ids=message_ids,
            processing_state="failed",
            batch_id=batch_id,
            error_text=normalized_error,
            started_at=now_text,
        )
        _append_message(
            conn,
            session_id=session_key,
            role="assistant",
            content="这轮分析暂时失败了。你可以继续补充消息，我会把未处理内容重新合并后再分析一次。",
            attachments=[],
            message_type="chat",
            meta={
                "dialogue_error": normalized_dialogue_error,
                "processing_error": normalized_error,
                "processing_batch_id": batch_id,
                "processing_failure": True,
                "trace_ref": normalized_trace_ref,
                "dialogue_agent_name": normalized_dialogue_agent_name,
                "dialogue_agent_workspace_path": normalized_dialogue_agent_workspace_path,
                "dialogue_provider": normalized_dialogue_provider,
            },
            created_at=now_text,
        )
        failure_messages = _list_session_messages(conn, session_key)
        _update_role_creation_message_queue_state(
            conn,
            session_id=session_key,
            queue_status="failed",
            queue_error=normalized_error,
            batch_id=batch_id,
            started_at=now_text,
            updated_at=now_text,
            messages=failure_messages,
        )
        conn.commit()
    finally:
        conn.close()
    append_training_center_audit(
        cfg.root,
        action="role_creation_message_batch_failed",
        operator=operator,
        target_id=session_key,
        detail={
            "session_id": session_key,
            "message_ids": list(message_ids or []),
            "processing_batch_id": batch_id,
            "error": normalized_error,
        },
    )


def _process_role_creation_message_batch(
    cfg: Any,
    *,
    session_id: str,
    operator: str,
) -> bool:
    time.sleep(ROLE_CREATION_MESSAGE_BATCH_DEBOUNCE_S)
    session_key = safe_token(session_id, "", 160)
    if not session_key:
        return False
    batch_started_at = _tc_now_text()
    batch_id = safe_token(f"rcmb-{uuid.uuid4().hex[:10]}", f"rcmb-{uuid.uuid4().hex[:10]}", 120)
    batch_messages: list[dict[str, Any]] = []
    current_detail: dict[str, Any] = {}
    session_summary: dict[str, Any] = {}
    role_spec: dict[str, Any] = {}
    missing_fields: list[str] = []
    session_title = ""
    task_refs: list[dict[str, Any]] = []
    created_tasks: list[dict[str, Any]] = []
    analyst_turn: dict[str, Any] = {}
    conn = connect_db(cfg.root)
    try:
        conn.execute("BEGIN")
        _row, session_summary, messages, task_refs, role_spec, missing_fields = _load_session_context(conn, session_key)
        if _normalize_session_status(session_summary.get("status")) == "completed":
            _update_role_creation_message_queue_state(
                conn,
                session_id=session_key,
                queue_status="idle",
                updated_at=batch_started_at,
                messages=messages,
            )
            conn.commit()
            return False
        batch_messages = _role_creation_pending_batch_messages(messages)
        if not batch_messages:
            _update_role_creation_message_queue_state(
                conn,
                session_id=session_key,
                queue_status="idle",
                updated_at=batch_started_at,
                messages=messages,
            )
            conn.commit()
            return False
        _update_role_creation_user_message_processing_state(
            conn,
            session_id=session_key,
            message_ids=[str(item.get("message_id") or "").strip() for item in batch_messages],
            processing_state="processing",
            batch_id=batch_id,
            started_at=batch_started_at,
        )
        processing_messages = _list_session_messages(conn, session_key)
        _update_role_creation_message_queue_state(
            conn,
            session_id=session_key,
            queue_status="running",
            queue_error="",
            batch_id=batch_id,
            started_at=batch_started_at,
            updated_at=batch_started_at,
            messages=processing_messages,
        )
        conn.commit()
    finally:
        conn.close()
    try:
        current_detail = get_role_creation_session_detail(cfg.root, session_key)
        session_summary = dict(current_detail.get("session") or {})
        role_spec = dict(current_detail.get("role_spec") or {})
        missing_fields = list((current_detail.get("profile") or {}).get("missing_fields") or [])
        session_title = str(session_summary.get("session_title") or "").strip()
        task_refs = list(current_detail.get("task_refs") or [])
        batch_text = _role_creation_batch_prompt_text(batch_messages)
        analyst_turn = run_role_creation_analyst_dialogue(
            cfg,
            detail=current_detail,
            latest_user_message=batch_text,
            operator=operator,
        )
        dialogue_error = str(analyst_turn.get("error") or "").strip()
        if dialogue_error:
            _finalize_role_creation_message_processing_failure(
                cfg,
                session_id=session_key,
                message_ids=[str(item.get("message_id") or "").strip() for item in batch_messages],
                batch_id=batch_id,
                operator=operator,
                error_text=str(analyst_turn.get("assistant_reply") or "").strip() or dialogue_error,
                dialogue_error=dialogue_error,
                trace_ref=str(analyst_turn.get("trace_ref") or "").strip(),
                dialogue_agent_name=str(analyst_turn.get("dialogue_agent_name") or "").strip(),
                dialogue_agent_workspace_path=str(analyst_turn.get("dialogue_agent_workspace_path") or "").strip(),
                dialogue_provider=str(analyst_turn.get("provider") or ROLE_CREATION_ANALYST_PROVIDER).strip(),
            )
            return False
        created_tasks = _create_role_creation_tasks_from_intents(
            cfg,
            session_summary=session_summary,
            task_refs=task_refs,
            task_intents=list(analyst_turn.get("delegate_tasks") or []),
            operator=operator,
        )
        if not created_tasks:
            created_tasks = _maybe_create_delegate_tasks(
                cfg,
                session_summary=session_summary,
                task_refs=task_refs,
                role_spec=role_spec,
                message_text=batch_text,
                operator=operator,
            )
        assistant_reply = str(analyst_turn.get("assistant_reply") or "").strip()
        if not assistant_reply:
            assistant_reply = _build_assistant_reply(
                session_summary={**session_summary, "session_title": session_title},
                role_spec=role_spec,
                missing_fields=missing_fields,
                created_tasks=created_tasks,
            )
        next_stage_key = _pick_role_creation_turn_stage_key(
            session_summary=session_summary,
            analyst_turn=analyst_turn,
            created_tasks=created_tasks,
        )
        next_stage_index = int((ROLE_CREATION_STAGE_BY_KEY.get(next_stage_key) or {}).get("index") or 0)
        dialogue_trace_ref = str(analyst_turn.get("trace_ref") or "").strip()
        assistant_message: dict[str, Any] = {}
        assistant_created_at = _tc_now_text()
        final_counts: dict[str, int] = {}
        conn = connect_db(cfg.root)
        try:
            conn.execute("BEGIN")
            _persist_role_creation_dialogue_fields(
                conn,
                session_id=session_key,
                dialogue_agent_name=str(analyst_turn.get("dialogue_agent_name") or "").strip(),
                dialogue_agent_workspace_path=str(analyst_turn.get("dialogue_agent_workspace_path") or "").strip(),
                dialogue_provider=str(analyst_turn.get("provider") or ROLE_CREATION_ANALYST_PROVIDER).strip(),
                trace_ref=dialogue_trace_ref,
                updated_at=assistant_created_at,
                stage_key=next_stage_key,
                stage_index=next_stage_index,
            )
            if next_stage_key:
                _append_message(
                    conn,
                    session_id=session_key,
                    role="system",
                    content=_role_creation_stage_update_text(next_stage_key),
                    attachments=[],
                    message_type="system_stage_update",
                    meta={
                        "stage_key": next_stage_key,
                        "source": "analyst_dialogue",
                        "trace_ref": dialogue_trace_ref,
                        "processing_batch_id": batch_id,
                    },
                    created_at=assistant_created_at,
                )
            if created_tasks:
                task_names = [
                    str(item.get("task_name") or "").strip()
                    for item in created_tasks
                    if str(item.get("task_name") or "").strip()
                ]
                _append_message(
                    conn,
                    session_id=session_key,
                    role="system",
                    content="已创建后台任务：" + "；".join(task_names[:3]),
                    attachments=[],
                    message_type="system_task_update",
                    meta={
                        "created_tasks": created_tasks,
                        "task_ids": [
                            str(item.get("task_id") or "").strip()
                            for item in created_tasks
                            if str(item.get("task_id") or "").strip()
                        ],
                        "processing_batch_id": batch_id,
                    },
                    created_at=assistant_created_at,
                )
            assistant_message = _append_message(
                conn,
                session_id=session_key,
                role="assistant",
                content=assistant_reply,
                attachments=[],
                message_type="chat",
                meta={
                    "dialogue_agent_name": str(analyst_turn.get("dialogue_agent_name") or "").strip(),
                    "dialogue_agent_workspace_path": str(analyst_turn.get("dialogue_agent_workspace_path") or "").strip(),
                    "dialogue_provider": str(analyst_turn.get("provider") or ROLE_CREATION_ANALYST_PROVIDER).strip(),
                    "trace_ref": dialogue_trace_ref,
                    "delegate_task_count": len(created_tasks),
                    "contract_has_json": bool(analyst_turn.get("contract_has_json")),
                    "dialogue_error": str(analyst_turn.get("error") or "").strip(),
                    "processing_batch_id": batch_id,
                    "handled_message_ids": [
                        str(item.get("message_id") or "").strip()
                        for item in batch_messages
                        if str(item.get("message_id") or "").strip()
                    ],
                },
                created_at=assistant_created_at,
            )
            _update_role_creation_user_message_processing_state(
                conn,
                session_id=session_key,
                message_ids=[str(item.get("message_id") or "").strip() for item in batch_messages],
                processing_state="processed",
                batch_id=batch_id,
                started_at=batch_started_at,
                processed_at=assistant_created_at,
                assistant_message_id=str(assistant_message.get("message_id") or "").strip(),
            )
            final_messages = _list_session_messages(conn, session_key)
            pending_counts = _role_creation_user_message_counts(final_messages)
            final_counts = _update_role_creation_message_queue_state(
                conn,
                session_id=session_key,
                queue_status="pending" if pending_counts["unhandled"] > 0 else "idle",
                queue_error="",
                updated_at=assistant_created_at,
                messages=final_messages,
            )
            conn.commit()
        finally:
            conn.close()
        if created_tasks and str(session_summary.get("assignment_ticket_id") or "").strip():
            _dispatch_role_creation_scheduler(
                cfg,
                ticket_id=str(session_summary.get("assignment_ticket_id") or "").strip(),
                operator=operator,
            )
        if str(session_summary.get("created_agent_workspace_path") or "").strip():
            _sync_workspace_profile(cfg.root, session_summary, role_spec)
        append_training_center_audit(
            cfg.root,
            action="role_creation_message_batch_processed",
            operator=operator,
            target_id=session_key,
            detail={
                "session_id": session_key,
                "processing_batch_id": batch_id,
                "message_ids": [
                    str(item.get("message_id") or "").strip()
                    for item in batch_messages
                    if str(item.get("message_id") or "").strip()
                ],
                "assistant_message_id": str(assistant_message.get("message_id") or "").strip(),
                "created_task_count": len(created_tasks),
                "dialogue_agent_name": str(analyst_turn.get("dialogue_agent_name") or "").strip(),
                "dialogue_agent_workspace_path": str(analyst_turn.get("dialogue_agent_workspace_path") or "").strip(),
                "dialogue_provider": str(analyst_turn.get("provider") or "").strip(),
                "dialogue_trace_ref": str(analyst_turn.get("trace_ref") or "").strip(),
                "dialogue_error": str(analyst_turn.get("error") or "").strip(),
                "unhandled_user_message_count": int(final_counts.get("unhandled") or 0),
            },
        )
        return int(final_counts.get("unhandled") or 0) > 0
    except TrainingCenterError as exc:
        if str(getattr(exc, "code", "") or "").strip() == "role_creation_session_not_found":
            return False
        _finalize_role_creation_message_processing_failure(
            cfg,
            session_id=session_key,
            message_ids=[str(item.get("message_id") or "").strip() for item in batch_messages],
            batch_id=batch_id,
            operator=operator,
            error_text=str(exc),
        )
        return False
    except Exception as exc:
        _finalize_role_creation_message_processing_failure(
            cfg,
            session_id=session_key,
            message_ids=[str(item.get("message_id") or "").strip() for item in batch_messages],
            batch_id=batch_id,
            operator=operator,
            error_text=str(exc),
        )
        return False


def _run_role_creation_message_worker(
    cfg: Any,
    *,
    session_id: str,
    operator: str,
) -> None:
    try:
        while True:
            has_more = _process_role_creation_message_batch(
                cfg,
                session_id=session_id,
                operator=operator,
            )
            if not has_more:
                break
    finally:
        with _ROLE_CREATION_MESSAGE_WORKER_LOCK:
            current = _ROLE_CREATION_MESSAGE_WORKERS.get(session_id)
            if current is threading.current_thread():
                _ROLE_CREATION_MESSAGE_WORKERS.pop(session_id, None)


def _ensure_role_creation_message_worker(
    cfg: Any,
    *,
    session_id: str,
    operator: str,
) -> bool:
    session_key = safe_token(session_id, "", 160)
    if not session_key:
        return False
    with _ROLE_CREATION_MESSAGE_WORKER_LOCK:
        current = _ROLE_CREATION_MESSAGE_WORKERS.get(session_key)
        if current and current.is_alive():
            return False
        worker = threading.Thread(
            target=_run_role_creation_message_worker,
            kwargs={"cfg": cfg, "session_id": session_key, "operator": operator},
            name=f"role-creation-message-{session_key}",
            daemon=True,
        )
        _ROLE_CREATION_MESSAGE_WORKERS[session_key] = worker
        worker.start()
        return True


ROLE_CREATION_ASSIGNMENT_GRAPH_NAME = "任务中心全局主图"
ROLE_CREATION_ASSIGNMENT_SOURCE_WORKFLOW = "workflow-ui"
ROLE_CREATION_ASSIGNMENT_GRAPH_REQUEST_ID = "workflow-ui-global-graph-v1"


def _ensure_role_creation_assignment_graph(cfg: Any, *, operator: str) -> str:
    created = assignment_service.create_assignment_graph(
        cfg,
        {
            "graph_name": ROLE_CREATION_ASSIGNMENT_GRAPH_NAME,
            "source_workflow": ROLE_CREATION_ASSIGNMENT_SOURCE_WORKFLOW,
            "summary": "任务中心手动创建（全局主图）",
            "review_mode": "none",
            "external_request_id": ROLE_CREATION_ASSIGNMENT_GRAPH_REQUEST_ID,
            "operator": operator,
        },
    )
    ticket_id = str(created.get("ticket_id") or "").strip()
    if not ticket_id:
        raise TrainingCenterError(500, "任务中心全局主图不存在", "role_creation_global_graph_missing")
    return ticket_id


def _create_role_creation_assignment_nodes(
    cfg: Any,
    *,
    ticket_id: str,
    starter_nodes: list[dict[str, Any]],
    operator: str,
) -> list[dict[str, Any]]:
    created_nodes: list[dict[str, Any]] = []
    try:
        batch_body = {
            "operator": operator,
            "nodes": [
                {
                    "node_id": str(item.get("node_id") or "").strip(),
                    "node_name": str(item.get("node_name") or "").strip(),
                    "assigned_agent_id": str(item.get("assigned_agent_id") or "").strip(),
                    "node_goal": str(item.get("node_goal") or "").strip(),
                    "expected_artifact": str(item.get("expected_artifact") or "").strip(),
                    "priority": str(item.get("priority") or "P1").strip(),
                    "upstream_node_ids": list(item.get("upstream_node_ids") or []),
                    "allow_creating_agent": True,
                }
                for item in list(starter_nodes or [])
            ],
        }
        create_batch_fn = getattr(assignment_service, "create_assignment_nodes_batch", None)
        if callable(create_batch_fn) and batch_body["nodes"]:
            batch_result = create_batch_fn(
                cfg,
                ticket_id,
                batch_body,
                include_test_data=True,
            )
            for item in list(batch_result.get("nodes") or []):
                created_nodes.append(
                    {
                        "node_id": str(item.get("node_id") or "").strip(),
                        "node_name": str(item.get("node_name") or item.get("task_name") or "").strip(),
                    }
                )
            if created_nodes:
                return created_nodes
        for item in list(starter_nodes or []):
            created = assignment_service.create_assignment_node(
                cfg,
                ticket_id,
                {
                    "node_id": str(item.get("node_id") or "").strip(),
                    "node_name": str(item.get("node_name") or "").strip(),
                    "assigned_agent_id": str(item.get("assigned_agent_id") or "").strip(),
                    "node_goal": str(item.get("node_goal") or "").strip(),
                    "expected_artifact": str(item.get("expected_artifact") or "").strip(),
                    "priority": str(item.get("priority") or "P1").strip(),
                    "upstream_node_ids": list(item.get("upstream_node_ids") or []),
                    "operator": operator,
                    "allow_creating_agent": True,
                },
                include_test_data=True,
            )
            created_nodes.append(
                {
                    "node_id": str((created.get("node") or {}).get("node_id") or item.get("node_id") or "").strip(),
                    "node_name": str((created.get("node") or {}).get("node_name") or item.get("node_name") or "").strip(),
                }
            )
    except Exception:
        for item in reversed(created_nodes):
            node_id = str(item.get("node_id") or "").strip()
            if not node_id:
                continue
            try:
                assignment_service.delete_assignment_node(
                    cfg.root,
                    ticket_id_text=ticket_id,
                    node_id_text=node_id,
                    operator=operator,
                    reason="rollback role creation starter nodes",
                    include_test_data=True,
                )
            except Exception:
                pass
        raise
    return created_nodes


_ROLE_CREATION_MESSAGE_WORKER_LOCK = threading.Lock()
_ROLE_CREATION_MESSAGE_WORKERS: dict[str, threading.Thread] = {}
