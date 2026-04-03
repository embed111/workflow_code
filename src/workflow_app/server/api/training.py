from __future__ import annotations

import re

from ..bootstrap import web_server_runtime as ws


def try_handle_get(handler, cfg, state, ctx: dict) -> bool:
    path = str(ctx.get("path") or "")
    root_ready = bool(ctx.get("root_ready"))
    root_text = str(ctx.get("root_text") or "")
    query = ctx.get("query") or {}
    artifact_settings = ws.get_artifact_root_settings(cfg.root)
    execution_settings = ws.get_assignment_execution_settings(cfg.root)
    policy_fields = ws.show_test_data_policy_fields(cfg, state)

    if path == "/api/training/role-creation/sessions":
        if not root_ready:
            handler.send_json(
                200,
                {
                    "ok": True,
                    "items": [],
                    "total": 0,
                    "agent_search_root": root_text,
                    "agent_search_root_ready": False,
                    "features_locked": True,
                },
            )
            return True
        try:
            data = ws.list_role_creation_sessions(cfg.root)
            handler.send_json(
                200,
                {
                    "ok": True,
                    **data,
                    "agent_search_root": root_text,
                    "agent_search_root_ready": True,
                    "features_locked": False,
                },
            )
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mrcs = re.fullmatch(r"/api/training/role-creation/sessions/([0-9A-Za-z._:-]+)", path)
    if mrcs:
        if not root_ready:
            handler.send_json(409, handler.root_not_ready_payload())
            return True
        try:
            data = ws.get_role_creation_session_detail(
                cfg.root,
                ws.safe_token(mrcs.group(1), "", 160),
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    if path == "/api/training/agents":
        if not root_ready:
            handler.send_json(
                200,
                {
                    "ok": True,
                    "items": [],
                    "stats": {
                        "agent_total": 0,
                        "git_available_count": 0,
                        "latest_release_at": "",
                        "training_queue_pending": 0,
                    },
                    "agent_search_root": root_text,
                    "agent_search_root_ready": False,
                    "features_locked": True,
                    "artifact_root": str(artifact_settings.get("artifact_root") or ""),
                    "artifact_workspace_root": str(artifact_settings.get("workspace_root") or ""),
                    "artifact_root_default": str(artifact_settings.get("default_artifact_root") or ""),
                    "artifact_root_validation_status": str(artifact_settings.get("path_validation_status") or ""),
                    "assignment_execution_settings": execution_settings,
                    **policy_fields,
                    "include_test_data": bool(ws.current_show_test_data(cfg, state)),
                },
            )
            return True
        include_test_data = ws.resolve_include_test_data(query, cfg, state)
        data = ws.list_training_agents_overview(cfg, include_test_data=include_test_data)
        handler.send_json(
            200,
            {
                "ok": True,
                **data,
                "include_test_data": include_test_data,
                **policy_fields,
                "agent_search_root": root_text,
                "agent_search_root_ready": True,
                "features_locked": False,
                "artifact_root": str(artifact_settings.get("artifact_root") or ""),
                "artifact_workspace_root": str(artifact_settings.get("workspace_root") or ""),
                "artifact_root_default": str(artifact_settings.get("default_artifact_root") or ""),
                "artifact_root_validation_status": str(artifact_settings.get("path_validation_status") or ""),
                "assignment_execution_settings": execution_settings,
            },
        )
        return True

    mtr = re.fullmatch(r"/api/training/agents/([0-9A-Za-z._:-]+)/releases", path)
    if mtr:
        try:
            page = int((query.get("page") or ["1"])[0])
        except Exception:
            page = 1
        try:
            page_size = int((query.get("page_size") or ["50"])[0])
        except Exception:
            page_size = 50
        try:
            data = ws.list_training_agent_releases(
                cfg.root,
                ws.safe_token(mtr.group(1), "", 120),
                page=page,
                page_size=page_size,
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    if path == "/api/training/queue":
        if not root_ready:
            handler.send_json(
                200,
                {
                    "ok": True,
                    "items": [],
                    **policy_fields,
                    "include_test_data": bool(ws.current_show_test_data(cfg, state)),
                    "agent_search_root": root_text,
                    "agent_search_root_ready": False,
                    "features_locked": True,
                },
            )
            return True
        include_removed = ws.parse_query_bool(query, "include_removed", default=True)
        include_test_data = ws.resolve_include_test_data(query, cfg, state)
        handler.send_json(
            200,
            {
                "ok": True,
                "items": ws.list_training_queue_items(
                    cfg.root,
                    include_removed=include_removed,
                    include_test_data=include_test_data,
                ),
                "include_removed": include_removed,
                "include_test_data": include_test_data,
                **policy_fields,
            },
        )
        return True

    mtloop = re.fullmatch(r"/api/training/queue/([0-9A-Za-z._:-]+)/loop", path)
    if mtloop:
        if not root_ready:
            handler.send_json(
                200,
                {
                    "ok": True,
                    "queue_task_id": ws.safe_token(mtloop.group(1), "", 160),
                    "loop_id": "",
                    "current_node_id": "",
                    "nodes": [],
                    "edges": [],
                    "metrics_available": False,
                    "metrics_unavailable_reason": "agent_search_root_not_ready",
                    "is_test_data": False,
                    **policy_fields,
                    "include_test_data": bool(ws.current_show_test_data(cfg, state)),
                    "agent_search_root": root_text,
                    "agent_search_root_ready": False,
                    "features_locked": True,
                },
            )
            return True
        include_test_data = ws.resolve_include_test_data(query, cfg, state)
        try:
            data = ws.get_training_queue_loop(
                cfg.root,
                ws.safe_token(mtloop.group(1), "", 160),
                include_test_data=include_test_data,
            )
            handler.send_json(
                200,
                {
                    "ok": True,
                    **data,
                    "include_test_data": include_test_data,
                    **policy_fields,
                },
            )
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mtstatus = re.fullmatch(r"/api/training/queue/([0-9A-Za-z._:-]+)/status-detail", path)
    if mtstatus:
        if not root_ready:
            handler.send_json(
                200,
                {
                    "ok": True,
                    "queue_task_id": ws.safe_token(mtstatus.group(1), "", 160),
                    "loop_id": "",
                    "current_node_id": "",
                    "execution_engine": "workflow_native",
                    "current_overview": {},
                    "workset_changes": {},
                    "evaluations": [],
                    "history_records": [],
                    "capabilities": [],
                    "tasks_evolution": {
                        "default_tab": "tasks",
                        "current_stage": "",
                        "blockers": [],
                        "pending_nodes": [],
                        "auto_publish": {"status": "pending", "reason": "agent_search_root_not_ready"},
                    },
                    "baseline": {
                        "current_release_version": "",
                        "current_role_profile_summary": "",
                        "history_key_capabilities": [],
                        "regression_results": [],
                        "source": "agent_registry",
                    },
                    "is_test_data": False,
                    **policy_fields,
                    "include_test_data": bool(ws.current_show_test_data(cfg, state)),
                    "agent_search_root": root_text,
                    "agent_search_root_ready": False,
                    "features_locked": True,
                },
            )
            return True
        include_test_data = ws.resolve_include_test_data(query, cfg, state)
        try:
            data = ws.get_training_queue_status_detail(
                cfg.root,
                ws.safe_token(mtstatus.group(1), "", 160),
                include_test_data=include_test_data,
            )
            handler.send_json(
                200,
                {
                    "ok": True,
                    **data,
                    "include_test_data": include_test_data,
                    **policy_fields,
                },
            )
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mrun = re.fullmatch(r"/api/training/runs/([0-9A-Za-z._:-]+)", path)
    if mrun:
        data = ws.get_training_run_detail(cfg.root, ws.safe_token(mrun.group(1), "", 160))
        if data is None:
            handler.send_json(404, {"ok": False, "error": "run not found", "code": "run_not_found"})
            return True
        handler.send_json(200, {"ok": True, **data})
        return True

    if path == "/api/training/trainers":
        query_text = str((query.get("query") or [""])[0] or "").strip()
        handler.send_json(
            200,
            {
                "ok": True,
                "query": query_text,
                "source_root": ws.TRAINER_SOURCE_ROOT.as_posix(),
                "items": ws.discover_training_trainers(query=query_text, limit=100),
            },
        )
        return True

    mrr = re.fullmatch(r"/api/training/agents/([0-9A-Za-z._:-]+)/release-review", path)
    if mrr:
        try:
            data = ws.get_training_agent_release_review(
                cfg.root,
                ws.safe_token(mrr.group(1), "", 120),
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    return False


def try_handle_post(handler, cfg, state, ctx: dict) -> bool:
    path = str(ctx.get("path") or "")
    body = ctx.get("body") or {}

    if path.startswith("/api/training") and not handler.ensure_root_ready():
        return True

    if path == "/api/training/role-creation/sessions":
        try:
            data = ws.create_role_creation_session(cfg, body)
            handler.send_json(200, {"ok": True, **data})
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mrcsm = re.fullmatch(r"/api/training/role-creation/sessions/([0-9A-Za-z._:-]+)/messages", path)
    if mrcsm:
        try:
            data = ws.post_role_creation_message(
                cfg,
                ws.safe_token(mrcsm.group(1), "", 160),
                body,
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mrcsr = re.fullmatch(r"/api/training/role-creation/sessions/([0-9A-Za-z._:-]+)/retry-analysis", path)
    if mrcsr:
        try:
            data = ws.retry_role_creation_session_analysis(
                cfg,
                ws.safe_token(mrcsr.group(1), "", 160),
                body,
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mrcss = re.fullmatch(r"/api/training/role-creation/sessions/([0-9A-Za-z._:-]+)/start", path)
    if mrcss:
        try:
            data = ws.start_role_creation_session(
                cfg,
                ws.safe_token(mrcss.group(1), "", 160),
                body,
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mrcst = re.fullmatch(r"/api/training/role-creation/sessions/([0-9A-Za-z._:-]+)/stage", path)
    if mrcst:
        try:
            data = ws.update_role_creation_session_stage(
                cfg,
                ws.safe_token(mrcst.group(1), "", 160),
                body,
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mrcsn = re.fullmatch(r"/api/training/role-creation/sessions/([0-9A-Za-z._:-]+)/tasks", path)
    if mrcsn:
        try:
            data = ws.create_role_creation_task(
                cfg,
                ws.safe_token(mrcsn.group(1), "", 160),
                body,
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mrcsa = re.fullmatch(
        r"/api/training/role-creation/sessions/([0-9A-Za-z._:-]+)/tasks/([0-9A-Za-z._:-]+)/archive",
        path,
    )
    if mrcsa:
        try:
            data = ws.archive_role_creation_task(
                cfg,
                ws.safe_token(mrcsa.group(1), "", 160),
                ws.safe_token(mrcsa.group(2), "", 160),
                body,
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mrcsc = re.fullmatch(r"/api/training/role-creation/sessions/([0-9A-Za-z._:-]+)/complete", path)
    if mrcsc:
        try:
            data = ws.complete_role_creation_session(
                cfg,
                ws.safe_token(mrcsc.group(1), "", 160),
                body,
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    if path == "/api/training/plans/manual":
        try:
            data = ws.create_training_plan_and_enqueue(
                cfg,
                body,
                forced_source="manual",
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    if path == "/api/training/plans/auto":
        try:
            data = ws.create_training_plan_and_enqueue(
                cfg,
                body,
                forced_source="auto_analysis",
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mts = re.fullmatch(r"/api/training/agents/([0-9A-Za-z._:-]+)/switch", path)
    if mts:
        try:
            data = ws.switch_training_agent_release(
                cfg,
                agent_id=ws.safe_token(mts.group(1), "", 120),
                version_label=str(
                    body.get("version_label")
                    or body.get("target_version")
                    or ""
                ).strip(),
                operator=str(body.get("operator") or "web-user"),
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mtc = re.fullmatch(r"/api/training/agents/([0-9A-Za-z._:-]+)/clone", path)
    if mtc:
        try:
            data = ws.clone_training_agent_from_current(
                cfg,
                agent_id=ws.safe_token(mtc.group(1), "", 120),
                new_agent_name=str(
                    body.get("new_agent_name")
                    or body.get("agent_name")
                    or body.get("clone_agent_name")
                    or ""
                ).strip(),
                operator=str(body.get("operator") or "web-user"),
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mta = re.fullmatch(r"/api/training/agents/([0-9A-Za-z._:-]+)/avatar", path)
    if mta:
        try:
            data = ws.set_training_agent_avatar(
                cfg,
                agent_id=ws.safe_token(mta.group(1), "", 120),
                avatar_uri=str(body.get("avatar_uri") or body.get("avatar") or "").strip(),
                upload_name=str(body.get("upload_name") or body.get("file_name") or "").strip(),
                upload_content_type=str(
                    body.get("upload_content_type")
                    or body.get("content_type")
                    or body.get("mime_type")
                    or ""
                ).strip(),
                upload_base64=str(
                    body.get("upload_base64")
                    or body.get("file_base64")
                    or body.get("file_content_base64")
                    or ""
                ).strip(),
                operator=str(body.get("operator") or "web-user"),
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mtd = re.fullmatch(r"/api/training/agents/([0-9A-Za-z._:-]+)/pre-release/discard", path)
    if mtd:
        try:
            data = ws.discard_agent_pre_release(
                cfg,
                agent_id=ws.safe_token(mtd.group(1), "", 120),
                operator=str(body.get("operator") or "web-user"),
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mte = re.fullmatch(
        r"/api/training/agents/([0-9A-Za-z._:-]+)/release-evaluations/manual",
        path,
    )
    if mte:
        try:
            data = ws.submit_manual_release_evaluation(
                cfg,
                agent_id=ws.safe_token(mte.group(1), "", 120),
                decision=str(body.get("decision") or "").strip(),
                reviewer=str(body.get("reviewer") or "").strip(),
                summary=str(body.get("summary") or "").strip(),
                operator=str(body.get("operator") or "web-user"),
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mrre = re.fullmatch(r"/api/training/agents/([0-9A-Za-z._:-]+)/release-review/enter", path)
    if mrre:
        try:
            data = ws.enter_training_agent_release_review(
                cfg,
                agent_id=ws.safe_token(mrre.group(1), "", 120),
                operator=str(body.get("operator") or "web-user"),
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mrrd = re.fullmatch(r"/api/training/agents/([0-9A-Za-z._:-]+)/release-review/discard", path)
    if mrrd:
        try:
            data = ws.discard_training_agent_release_review(
                cfg,
                agent_id=ws.safe_token(mrrd.group(1), "", 120),
                operator=str(body.get("operator") or "web-user"),
                reason=str(body.get("reason") or body.get("review_comment") or body.get("summary") or "").strip(),
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mrrm = re.fullmatch(r"/api/training/agents/([0-9A-Za-z._:-]+)/release-review/manual", path)
    if mrrm:
        try:
            data = ws.submit_training_agent_release_review_manual(
                cfg,
                agent_id=ws.safe_token(mrrm.group(1), "", 120),
                decision=str(body.get("decision") or "").strip(),
                reviewer=str(body.get("reviewer") or "").strip(),
                review_comment=str(body.get("review_comment") or body.get("summary") or "").strip(),
                operator=str(body.get("operator") or "web-user"),
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mrrc = re.fullmatch(r"/api/training/agents/([0-9A-Za-z._:-]+)/release-review/confirm", path)
    if mrrc:
        try:
            data = ws.confirm_training_agent_release_review(
                cfg,
                agent_id=ws.safe_token(mrrc.group(1), "", 120),
                operator=str(body.get("operator") or "web-user"),
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mtrm = re.fullmatch(r"/api/training/queue/([0-9A-Za-z._:-]+)/remove", path)
    if mtrm:
        try:
            data = ws.remove_training_queue_item(
                cfg.root,
                queue_task_id_text=ws.safe_token(mtrm.group(1), "", 160),
                operator=str(body.get("operator") or "web-user"),
                reason=str(body.get("reason") or ""),
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mtrn = re.fullmatch(r"/api/training/queue/([0-9A-Za-z._:-]+)/rename", path)
    if mtrn:
        try:
            data = ws.rename_training_queue_item(
                cfg.root,
                queue_task_id_text=ws.safe_token(mtrn.group(1), "", 160),
                capability_goal=str(
                    body.get("capability_goal")
                    or body.get("title")
                    or body.get("name")
                    or ""
                ).strip(),
                operator=str(body.get("operator") or "web-user"),
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mtnr = re.fullmatch(r"/api/training/queue/([0-9A-Za-z._:-]+)/loop/enter-next-round", path)
    if mtnr:
        try:
            data = ws.enter_training_queue_next_round(
                cfg.root,
                queue_task_id_text=ws.safe_token(mtnr.group(1), "", 160),
                operator=str(body.get("operator") or "web-user"),
                reason=str(body.get("reason") or body.get("comment") or "").strip(),
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mtrb = re.fullmatch(r"/api/training/queue/([0-9A-Za-z._:-]+)/loop/rollback-round-increment", path)
    if mtrb:
        try:
            data = ws.rollback_training_queue_round_increment(
                cfg.root,
                queue_task_id_text=ws.safe_token(mtrb.group(1), "", 160),
                operator=str(body.get("operator") or "web-user"),
                reason=str(body.get("reason") or body.get("comment") or "").strip(),
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    mtre = re.fullmatch(r"/api/training/queue/([0-9A-Za-z._:-]+)/execute", path)
    if mtre:
        try:
            data = ws.execute_training_queue_item(
                cfg.root,
                queue_task_id_text=ws.safe_token(mtre.group(1), "", 160),
                operator=str(body.get("operator") or "web-user"),
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    if path == "/api/training/queue/dispatch-next":
        try:
            data = ws.dispatch_next_training_queue_item(
                cfg.root,
                operator=str(body.get("operator") or "web-user"),
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    return False


def try_handle_delete(handler, cfg, state, ctx: dict) -> bool:
    path = str(ctx.get("path") or "")
    body = ctx.get("body") or {}

    if path.startswith("/api/training") and not handler.ensure_root_ready():
        return True

    mrcsd = re.fullmatch(r"/api/training/role-creation/sessions/([0-9A-Za-z._:-]+)", path)
    if mrcsd:
        try:
            data = ws.delete_role_creation_session(
                cfg,
                ws.safe_token(mrcsd.group(1), "", 160),
                body,
            )
            handler.send_json(200, {"ok": True, **data})
        except ws.TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            handler.send_json(exc.status_code, payload)
        return True

    return False

