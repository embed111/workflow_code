from __future__ import annotations

# NOTE: legacy full-route implementation extracted from workflow_web_server.py
# Keep behavior-compatible while routing is being modularized.
from ..bootstrap.web_server_runtime import *  # noqa: F401,F403


def handle_get_legacy(self, cfg, state) -> None:
    parsed = urlparse(self.path)
    path = parsed.path
    query = parse_qs(parsed.query)
    if path == "/":
        self.send_html(load_index_page_html())
        return
    if path in ("/static/workflow-web-client.js", "/static/day3-web.js"):
        try:
            asset_text = load_web_client_asset_text()
        except FileNotFoundError:
            self.send_json(404, {"ok": False, "error": "asset missing"})
            return
        self.send_text(200, asset_text, "application/javascript; charset=utf-8")
        return
    if path == "/static/workflow-web.css":
        self.send_text(200, load_index_page_css(), "text/css; charset=utf-8")
        return
    if path == "/api/runtime-file":
        raw_ref = str((query.get("path") or [""])[0] or "").strip()
        if not raw_ref:
            self.send_json(400, {"ok": False, "error": "path required", "code": "runtime_file_path_required"})
            return
        try:
            target = normalize_abs_path(raw_ref, base=cfg.root)
            target.relative_to(cfg.root.resolve(strict=False))
        except Exception:
            self.send_json(
                400,
                {
                    "ok": False,
                    "error": f"runtime file path out of root: {raw_ref}",
                    "code": "runtime_file_out_of_root",
                },
            )
            return
        if not target.exists() or not target.is_file():
            self.send_json(
                404,
                {
                    "ok": False,
                    "error": f"runtime file not found: {raw_ref}",
                    "code": "runtime_file_not_found",
                },
            )
            return
        try:
            text = target.read_text(encoding="utf-8")
        except Exception as exc:
            self.send_json(
                500,
                {
                    "ok": False,
                    "error": f"runtime file read failed: {exc}",
                    "code": "runtime_file_read_failed",
                },
            )
            return
        content_type = "application/json; charset=utf-8" if target.suffix.lower() == ".json" else "text/plain; charset=utf-8"
        self.send_text(200, text, content_type)
        return
    if path == "/healthz":
        self.send_json(200, {"ok": True, "ts": iso_ts(now_local())})
        return
    _root, root_ready, root_error, root_text = self.root_status()
    root_ready_get_allowlist = {
        "/api/agents",
        "/api/status",
        "/api/config/show-test-data",
        "/api/dashboard",
        "/api/reconcile/latest",
        "/api/chat/sessions",
        "/api/workflows/training/queue",
        "/api/training/agents",
        "/api/training/queue",
        "/api/training/trainers",
    }
    if not root_ready and path not in root_ready_get_allowlist:
        self.send_json(409, self.root_not_ready_payload())
        return
    if path == "/api/agents":
        if parse_query_bool(query, "force_show_test_data_read_fail", default=False):
            self.send_json(
                500,
                {
                    "ok": False,
                    "error": "show_test_data read failed: forced by query",
                    "code": "show_test_data_read_failed",
                },
            )
            return
        force_refresh = parse_query_bool(query, "force_refresh", default=False)
        agents = list_available_agents(cfg, force_refresh=force_refresh) if root_ready else []
        self.send_json(
            200,
            {
                "ok": True,
                "agents_root": root_text,
                "agent_search_root": root_text,
                "workspace_root_valid": bool(root_ready),
                "workspace_root_error": root_error,
                "agent_search_root_ready": bool(root_ready),
                "features_locked": not bool(root_ready),
                "show_test_data": bool(current_show_test_data(cfg, state)),
                "allow_manual_policy_input": bool(current_allow_manual_policy_input(cfg, state)),
                "policy_closure": policy_closure_stats(cfg.root),
                "agents": agents,
                "count": len(agents),
            },
        )
        return
    if path == "/api/status":
        include_test_data = current_show_test_data(cfg, state)
        pa, pt = pending_counts(cfg.root, include_test_data=include_test_data)
        if AB_FEATURE_ENABLED:
            ab = ab_status(cfg)
        else:
            ab = {"active_version": "disabled", "active_slot": "disabled"}
        self.send_json(
            200,
            {
                "ok": True,
                "pending_analysis": pa,
                "pending_training": pt,
                "active_version": ab["active_version"],
                "active_slot": ab["active_slot"],
                "available_agents": len(list_available_agents(cfg)) if root_ready else 0,
                "show_test_data": bool(include_test_data),
                "agent_search_root": root_text,
                "agent_search_root_ready": bool(root_ready),
                "agent_search_root_error": root_error,
                "features_locked": not bool(root_ready),
            },
        )
        return
    if path == "/api/config/show-test-data":
        if parse_query_bool(query, "force_fail", default=False):
            self.send_json(
                500,
                {
                    "ok": False,
                    "error": "show_test_data read failed: forced by query",
                    "code": "show_test_data_read_failed",
                },
            )
            return
        self.send_json(
            200,
            {
                "ok": True,
                "show_test_data": bool(current_show_test_data(cfg, state)),
            },
        )
        return
    if path == "/api/dashboard":
        include_test_data = resolve_include_test_data(query, cfg, state)
        self.send_json(
            200,
            {
                **dashboard(cfg, include_test_data=include_test_data),
                "show_test_data": bool(current_show_test_data(cfg, state)),
                "include_test_data": bool(include_test_data),
            },
        )
        return
    if path == "/api/policy/closure/stats":
        self.send_json(
            200,
            {
                "ok": True,
                "stats": policy_closure_stats(cfg.root),
            },
        )
        return
    if path == "/api/policy/patch-tasks":
        try:
            limit = int((query.get("limit") or ["200"])[0])
        except Exception:
            limit = 200
        self.send_json(
            200,
            {
                "ok": True,
                "items": list_agent_policy_patch_tasks(cfg.root, limit=limit),
            },
        )
        return
    if path == "/api/reconcile/latest":
        self.send_json(200, {"ok": True, "latest": latest_reconcile(cfg.root)})
        return
    if path == "/api/chat/sessions":
        include_test_data = resolve_include_test_data(query, cfg, state)
        self.send_json(
            200,
            {
                "ok": True,
                "include_test_data": include_test_data,
                "show_test_data": bool(current_show_test_data(cfg, state)),
                "sessions": (
                    list_chat_sessions(
                        cfg.root,
                        include_test_data=include_test_data,
                    )
                    if root_ready
                    else []
                ),
                "agent_search_root": root_text,
                "agent_search_root_ready": bool(root_ready),
                "features_locked": not bool(root_ready),
            },
        )
        return
    mm = re.fullmatch(r"/api/chat/sessions/([0-9A-Za-z._:-]+)/messages", path)
    if mm:
        session_id = safe_token(mm.group(1), "", 140)
        session = get_session(cfg.root, session_id)
        if not session:
            self.send_json(404, {"ok": False, "error": "session not found"})
            return
        self.send_json(
            200,
            {
                "ok": True,
                "session_id": session_id,
                "agent_name": session.get("agent_name", ""),
                "agents_hash": session.get("agents_hash", ""),
                "agents_path": session.get("agents_path", ""),
                "agents_version": session.get("agents_version", ""),
                "role_profile": session.get("role_profile", ""),
                "session_goal": session.get("session_goal", ""),
                "duty_constraints": session.get("duty_constraints", ""),
                "policy_snapshot_json": session.get("policy_snapshot_json", "{}"),
                "messages": list_session_messages(cfg.root, session_id),
            },
        )
        return
    mr = re.fullmatch(r"/api/chat/sessions/([0-9A-Za-z._:-]+)/task-runs", path)
    if mr:
        session_id = safe_token(mr.group(1), "", 140)
        session = get_session(cfg.root, session_id)
        if not session:
            self.send_json(404, {"ok": False, "error": "session not found"})
            return
        try:
            limit = int((query.get("limit") or ["200"])[0])
        except Exception:
            limit = 200
        self.send_json(
            200,
            {
                "ok": True,
                "session_id": session_id,
                "items": list_session_task_runs(cfg.root, session_id, limit=limit),
            },
        )
        return
    if path == "/api/training/agents":
        if not root_ready:
            self.send_json(
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
                    "show_test_data": bool(current_show_test_data(cfg, state)),
                    "include_test_data": bool(current_show_test_data(cfg, state)),
                },
            )
            return
        include_test_data = resolve_include_test_data(query, cfg, state)
        data = list_training_agents_overview(cfg, include_test_data=include_test_data)
        self.send_json(
            200,
            {
                "ok": True,
                **data,
                "include_test_data": include_test_data,
                "show_test_data": bool(current_show_test_data(cfg, state)),
                "agent_search_root": root_text,
                "agent_search_root_ready": True,
                "features_locked": False,
            },
        )
        return
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
            data = list_training_agent_releases(
                cfg.root,
                safe_token(mtr.group(1), "", 120),
                page=page,
                page_size=page_size,
            )
            self.send_json(200, {"ok": True, **data})
        except TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            self.send_json(exc.status_code, payload)
        return
    mrr = re.fullmatch(r"/api/training/agents/([0-9A-Za-z._:-]+)/release-review", path)
    if mrr:
        try:
            data = get_training_agent_release_review(
                cfg.root,
                safe_token(mrr.group(1), "", 120),
            )
            self.send_json(200, {"ok": True, **data})
        except TrainingCenterError as exc:
            payload = {"ok": False, "error": str(exc), "code": exc.code}
            payload.update(exc.extra)
            self.send_json(exc.status_code, payload)
        return
    if path == "/api/training/queue":
        if not root_ready:
            self.send_json(
                200,
                {
                    "ok": True,
                    "items": [],
                    "show_test_data": bool(current_show_test_data(cfg, state)),
                    "include_test_data": bool(current_show_test_data(cfg, state)),
                    "agent_search_root": root_text,
                    "agent_search_root_ready": False,
                    "features_locked": True,
                },
            )
            return
        include_removed = parse_query_bool(query, "include_removed", default=True)
        include_test_data = resolve_include_test_data(query, cfg, state)
        self.send_json(
            200,
            {
                "ok": True,
                "items": list_training_queue_items(
                    cfg.root,
                    include_removed=include_removed,
                    include_test_data=include_test_data,
                ),
                "include_removed": include_removed,
                "include_test_data": include_test_data,
                "show_test_data": bool(current_show_test_data(cfg, state)),
            },
        )
        return
    mrun = re.fullmatch(r"/api/training/runs/([0-9A-Za-z._:-]+)", path)
    if mrun:
        data = get_training_run_detail(cfg.root, safe_token(mrun.group(1), "", 160))
        if data is None:
            self.send_json(404, {"ok": False, "error": "run not found", "code": "run_not_found"})
            return
        self.send_json(200, {"ok": True, **data})
        return
    if path == "/api/training/trainers":
        query_text = str((query.get("query") or [""])[0] or "").strip()
        self.send_json(
            200,
            {
                "ok": True,
                "query": query_text,
                "source_root": TRAINER_SOURCE_ROOT.as_posix(),
                "items": discover_training_trainers(query=query_text, limit=100),
            },
        )
        return
    if path == "/api/workflows/training/queue":
        include_test_data = resolve_include_test_data(query, cfg, state)
        items = (
            list_training_workflows(
                cfg.root,
                include_test_data=include_test_data,
            )
            if root_ready
            else []
        )
        self.send_json(
            200,
            {
                "ok": True,
                "include_test_data": include_test_data,
                "show_test_data": bool(current_show_test_data(cfg, state)),
                "items": items,
                "agent_search_root": root_text,
                "agent_search_root_ready": bool(root_ready),
                "features_locked": not bool(root_ready),
            },
        )
        return
    mp = re.fullmatch(r"/api/workflows/training/([0-9A-Za-z._:-]+)/plan", path)
    if mp:
        workflow_id = safe_token(mp.group(1), "", 120)
        workflow = get_training_workflow(cfg.root, workflow_id)
        if not workflow:
            self.send_json(404, {"ok": False, "error": "workflow not found"})
            return
        self.send_json(
            200,
            {
                "ok": True,
                "workflow_id": workflow_id,
                "plan": workflow.get("plan") or [],
                "selected_plan": workflow.get("selected_plan") or [],
                "analysis_summary": workflow.get("analysis_summary") or "",
                "analysis_recommendation": workflow.get("analysis_recommendation") or "",
                "analysis_run_id": workflow.get("latest_analysis_run_id") or "",
                "no_value_reason": workflow.get("latest_no_value_reason") or "",
            },
        )
        return
    mw = re.fullmatch(r"/api/workflows/training/([0-9A-Za-z._:-]+)/events", path)
    if mw:
        workflow_id = safe_token(mw.group(1), "", 120)
        workflow = get_training_workflow(cfg.root, workflow_id)
        if not workflow:
            self.send_json(404, {"ok": False, "error": "workflow not found"})
            return
        try:
            since_id = int((query.get("since_id") or ["0"])[0])
        except Exception:
            since_id = 0
        events = list_training_workflow_events(
            cfg.root,
            workflow_id,
            since_id=since_id,
        )
        next_since = int(events[-1]["event_id"]) if events else since_id
        self.send_json(
            200,
            {
                "ok": True,
                "workflow_id": workflow_id,
                "events": events,
                "next_since_id": next_since,
            },
        )
        return
    if path == "/api/ab/status":
        if not AB_FEATURE_ENABLED:
            self.send_json(404, {"ok": False, "error": "ab disabled", "code": "ab_disabled"})
            return
        self.send_json(200, {"ok": True, **ab_status(cfg)})
        return
    mt = re.fullmatch(r"/api/tasks/([0-9A-Za-z._:-]+)", path)
    if mt:
        task_id_text = safe_token(mt.group(1), "", 140)
        row = get_task_run(cfg.root, task_id_text)
        if not row:
            self.send_json(404, {"ok": False, "error": "task not found"})
            return
        self.send_json(200, {"ok": True, **row})
        return
    mtrace = re.fullmatch(r"/api/tasks/([0-9A-Za-z._:-]+)/trace", path)
    if mtrace:
        task_id_text = safe_token(mtrace.group(1), "", 140)
        row = get_task_run(cfg.root, task_id_text)
        if not row:
            self.send_json(404, {"ok": False, "error": "task not found"})
            return
        self.send_json(
            200,
            {
                "ok": True,
                "task_id": task_id_text,
                "task": row,
                "trace": load_task_trace(cfg.root, task_id_text),
                "events": list_task_events(cfg.root, task_id_text, since_id=0, limit=5000),
            },
        )
        return
    me = re.fullmatch(r"/api/tasks/([0-9A-Za-z._:-]+)/events", path)
    if me:
        task_id_text = safe_token(me.group(1), "", 140)
        row = get_task_run(cfg.root, task_id_text)
        if not row:
            self.send_json(404, {"ok": False, "error": "task not found"})
            return
        try:
            since_id = int((query.get("since_id") or ["0"])[0])
        except Exception:
            since_id = 0
        events = list_task_events(cfg.root, task_id_text, since_id=since_id)
        next_since = since_id
        if events:
            next_since = int(events[-1]["event_id"])
        self.send_json(
            200,
            {
                "ok": True,
                "task_id": task_id_text,
                "events": events,
                "next_since_id": next_since,
            },
        )
        return
    self.send_json(404, {"ok": False, "error": "not found"})


