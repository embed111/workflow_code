from __future__ import annotations

from ..bootstrap.web_server_runtime import *  # noqa: F401,F403

def try_handle_task_crud_routes(self, cfg, state, path: str, body: dict[str, Any]) -> bool:
    mmd = re.fullmatch(r"/api/chat/sessions/([0-9A-Za-z._:-]+)/messages/([0-9]+)/delete", path)
    if mmd:
        session_id = safe_token(mmd.group(1), "", 140)
        message_id_text = safe_token(mmd.group(2), "", 40)
        if not session_id:
            self.send_json(400, {"ok": False, "error": "session_id required", "code": "session_required"})
            return True
        if not message_id_text.isdigit():
            self.send_json(400, {"ok": False, "error": "message_id required", "code": "message_required"})
            return True
        message_id_num = int(message_id_text)
        operator = safe_token(str(body.get("operator") or "web-user"), "web-user", 80)
        if has_session_runtime_task(state, session_id, root=cfg.root):
            ref = relative_to_root(cfg.root, event_file(cfg.root))
            workflow_meta = latest_workflow_for_session(cfg.root, session_id)
            audit_id = add_message_delete_audit(
                cfg.root,
                operator=operator,
                session_id=session_id,
                message_id=message_id_num,
                status="rejected",
                reason_code="session_busy",
                reason_text="当前会话有运行中的任务",
                impact_scope="none",
                workflow_id=str(workflow_meta.get("workflow_id") or ""),
                analysis_run_id_text=str(workflow_meta.get("analysis_run_id") or ""),
                training_plan_items=session_training_plan_item_count(cfg.root, session_id),
                ref=ref,
            )
            self.send_json(
                409,
                {
                    "ok": False,
                    "error": "当前会话有运行中的任务",
                    "code": "session_busy",
                    "audit_id": audit_id,
                    "session_id": session_id,
                    "message_id": message_id_num,
                },
            )
            return True
        try:
            result = delete_session_message_with_gate(
                cfg.root,
                session_id,
                message_id_num,
                operator=operator,
            )
            refresh_status(cfg)
            self.send_json(200, {"ok": True, **result})
        except WorkflowGateError as exc:
            ref = relative_to_root(cfg.root, event_file(cfg.root))
            if exc.code != "conversation_locked_by_training_plan":
                workflow_meta = latest_workflow_for_session(cfg.root, session_id)
                audit_id = add_message_delete_audit(
                    cfg.root,
                    operator=operator,
                    session_id=session_id,
                    message_id=message_id_num,
                    status="rejected",
                    reason_code=exc.code,
                    reason_text=str(exc),
                    impact_scope="none",
                    workflow_id=str(workflow_meta.get("workflow_id") or ""),
                    analysis_run_id_text=str(workflow_meta.get("analysis_run_id") or ""),
                    training_plan_items=session_training_plan_item_count(cfg.root, session_id),
                    ref=ref,
                )
                extra = dict(exc.extra or {})
                extra.setdefault("audit_id", audit_id)
            else:
                extra = dict(exc.extra or {})
            payload = {
                "ok": False,
                "error": str(exc),
                "code": exc.code,
                "session_id": session_id,
                "message_id": message_id_num,
            }
            payload.update(extra)
            self.send_json(exc.status_code, payload)
        except Exception as exc:
            append_failure_case(
                cfg.root,
                "message_delete_failed",
                f"session_id={session_id}, message_id={message_id_num}, err={exc}",
            )
            self.send_json(500, {"ok": False, "error": str(exc)})
        return True
    msd = re.fullmatch(r"/api/chat/sessions/([0-9A-Za-z._:-]+)/delete", path)
    if msd:
        session_id = safe_token(msd.group(1), "", 140)
        if not session_id:
            self.send_json(400, {"ok": False, "error": "session_id required", "code": "session_required"})
            return True
        if has_session_runtime_task(state, session_id, root=cfg.root):
            self.send_json(
                409,
                {
                    "ok": False,
                    "error": "当前会话有运行中的任务",
                    "code": "session_busy",
                    "session_id": session_id,
                },
            )
            return True
        delete_artifacts = bool(body.get("delete_artifacts", True))
        try:
            session_before_delete = get_session(cfg.root, session_id)
            manual_patch_task_id = ""
            if session_before_delete:
                manual_patch_task_id = ensure_manual_fallback_patch_task(
                    cfg.root,
                    session_before_delete,
                    reason="deleted",
                )
            result = delete_session_history(
                cfg.root,
                session_id,
                delete_artifacts=delete_artifacts,
            )
            ref = relative_to_root(cfg.root, event_file(cfg.root))
            append_admin_event(
                cfg.root,
                session_id=session_id,
                action="session_history_deleted",
                status="success",
                reason_tags=["session_deleted"] + ([f"patch_task:{manual_patch_task_id}"] if manual_patch_task_id else []),
                ref=ref,
            )
            append_change_log(
                cfg.root,
                "session history deleted",
                (
                    f"session_id={session_id}, deleted_messages={result.get('deleted_messages',0)}, "
                    f"deleted_task_runs={result.get('deleted_task_runs',0)}, deleted_workflows={result.get('deleted_workflows',0)}"
                ),
            )
            sync_analysis_tasks(cfg.root)
            sync_training_workflows(cfg.root)
            refresh_status(cfg)
            self.send_json(
                200,
                {
                    "ok": True,
                    "session_id": session_id,
                    "result": result,
                    "manual_fallback_patch_task_id": manual_patch_task_id,
                },
            )
        except Exception as exc:
            append_failure_case(
                cfg.root,
                "session_delete_failed",
                f"session_id={session_id}, err={exc}",
            )
            append_admin_event(
                cfg.root,
                session_id=session_id,
                action="session_history_deleted",
                status="failed",
                reason_tags=["session_delete_failed"],
                ref="",
            )
            self.send_json(500, {"ok": False, "error": str(exc)})
        return True
    mwd = re.fullmatch(r"/api/workflows/training/([0-9A-Za-z._:-]+)/delete", path)
    if mwd:
        workflow_id = safe_token(mwd.group(1), "", 120)
        if not workflow_id:
            self.send_json(400, {"ok": False, "error": "workflow_id required", "code": "workflow_required"})
            return True
        if training_workflow_has_running_task(cfg.root, state, workflow_id):
            self.send_json(
                409,
                {
                    "ok": False,
                    "error": "当前训练工作流有运行中的任务",
                    "code": "workflow_busy",
                    "workflow_id": workflow_id,
                },
            )
            return True
        delete_artifacts = bool(body.get("delete_artifacts", True))
        try:
            result = delete_training_content(
                cfg.root,
                workflow_id,
                delete_artifacts=delete_artifacts,
            )
            ref = relative_to_root(cfg.root, event_file(cfg.root))
            append_admin_event(
                cfg.root,
                session_id=str(result.get("session_id") or "sess-workflow"),
                action="training_content_deleted",
                status="success",
                reason_tags=["training_deleted"],
                ref=ref,
            )
            append_change_log(
                cfg.root,
                "training content deleted",
                (
                    f"workflow_id={workflow_id}, analysis_id={result.get('analysis_id','')}, "
                    f"deleted_training_tasks={result.get('deleted_training_tasks',0)}"
                ),
            )
            sync_training_workflows(cfg.root)
            refresh_status(cfg)
            self.send_json(200, {"ok": True, "workflow_id": workflow_id, "result": result})
        except Exception as exc:
            append_failure_case(
                cfg.root,
                "training_delete_failed",
                f"workflow_id={workflow_id}, err={exc}",
            )
            append_admin_event(
                cfg.root,
                session_id="sess-workflow",
                action="training_content_deleted",
                status="failed",
                reason_tags=["training_delete_failed"],
                ref="",
            )
            self.send_json(500, {"ok": False, "error": str(exc)})
        return True
    if path == "/api/admin/history/cleanup":
        mode = str(body.get("mode") or "closed_sessions").strip().lower()
        delete_artifacts = parse_bool_flag(body.get("delete_artifacts", True), default=True)
        delete_log_files = parse_bool_flag(body.get("delete_log_files", False), default=False)
        try:
            max_age_hours = max(1, int(body.get("max_age_hours") or TEST_DATA_MAX_AGE_HOURS))
        except Exception:
            self.send_json(400, {"ok": False, "error": "max_age_hours invalid", "code": "max_age_hours_invalid"})
            return True
        include_active_test_sessions = parse_bool_flag(
            body.get("include_active_test_sessions", False),
            default=False,
        )
        active_count = active_runtime_task_count(state, root=cfg.root)
        if active_count > 0:
            self.send_json(
                409,
                {
                    "ok": False,
                    "error": f"仍有运行中的任务: {active_count}",
                    "code": "active_tasks_running",
                },
            )
            return True
        try:
            result = admin_cleanup_history(
                cfg.root,
                mode=mode,
                delete_artifacts=delete_artifacts,
                delete_log_files=delete_log_files,
                max_age_hours=max_age_hours,
                include_active_test_sessions=include_active_test_sessions,
            )
            ref = relative_to_root(cfg.root, event_file(cfg.root))
            append_admin_event(
                cfg.root,
                session_id="sess-admin",
                action="history_cleanup",
                status="success",
                reason_tags=[f"mode:{mode}"],
                ref=ref,
            )
            append_change_log(
                cfg.root,
                "history cleanup",
                (
                    f"mode={mode}, deleted_sessions={result.get('deleted_sessions')}, "
                    f"deleted_logs={result.get('deleted_logs')}"
                ),
            )
            sync_analysis_tasks(cfg.root)
            sync_training_workflows(cfg.root)
            refresh_status(cfg)
            self.send_json(200, {"ok": True, "result": result})
        except Exception as exc:
            append_failure_case(
                cfg.root,
                "history_cleanup_failed",
                f"mode={mode}, err={exc}",
            )
            append_admin_event(
                cfg.root,
                session_id="sess-admin",
                action="history_cleanup",
                status="failed",
                reason_tags=["history_cleanup_failed"],
                ref="",
            )
            self.send_json(500, {"ok": False, "error": str(exc)})
        return True
        return False

