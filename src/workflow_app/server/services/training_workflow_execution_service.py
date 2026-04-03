from __future__ import annotations

from .work_record_store import (
    get_analysis_record,
    get_training_task_record,
    training_record_path,
    upsert_training_task_record,
)


def bind_runtime_symbols(symbols: dict[str, object]) -> None:
    module_name = str(globals().get("__name__") or "")
    for key, value in symbols.items():
        if key.startswith("__") or key == "bind_runtime_symbols":
            continue
        current = globals().get(key)
        if callable(current) and getattr(current, "__module__", "") == module_name:
            continue
        globals()[key] = value


def run_training_once_for_analysis(
    root: Path,
    analysis_id: str,
    *,
    max_retries: int,
) -> dict[str, Any]:
    analysis = get_analysis_record(root, analysis_id)
    if not analysis:
        raise RuntimeError(f"analysis not found: {analysis_id}")
    training = get_training_task_record(root, analysis_id) or {}

    session_id = str(analysis.get("session_id") or "")
    training_id = str(training.get("training_id") or create_training_id(analysis_id))
    current_attempts = int(training.get("attempts") or 0)
    if current_attempts >= max(1, max_retries):
        return {
            "training_id": training_id,
            "status": "failed",
            "attempt": current_attempts,
            "trainer_run_ref": "",
            "summary": "max retries reached",
            "session_id": session_id,
        }

    ts = now_local()
    attempt = current_attempts + 1
    upsert_training_task_record(
        root,
        analysis_id,
        {
            **training,
            "training_id": training_id,
            "status": "running",
            "attempts": attempt,
            "created_at": str(training.get("created_at") or iso_ts(ts)),
            "updated_at": iso_ts(ts),
        },
    )

    status = "failed"
    summary = ""
    trainer_ref = ""
    try:
        trainer_status, trainer_ref, summary = run_trainer_once(
            root=root,
            ts=ts,
            training_id=training_id,
            analysis_id=analysis_id,
            session_id=session_id,
            attempt=attempt,
        )
        if trainer_status == "done":
            status = "done"
            upsert_training_task_record(
                root,
                analysis_id,
                {
                    **(get_training_task_record(root, analysis_id) or {}),
                    "training_id": training_id,
                    "status": "done",
                    "result_summary": summary,
                    "trainer_run_ref": trainer_ref,
                    "last_error": "",
                    "updated_at": iso_ts(now_local()),
                },
            )
        else:
            status = "pending" if attempt < max(1, max_retries) else "failed"
            upsert_training_task_record(
                root,
                analysis_id,
                {
                    **(get_training_task_record(root, analysis_id) or {}),
                    "training_id": training_id,
                    "status": status,
                    "result_summary": summary,
                    "trainer_run_ref": trainer_ref,
                    "last_error": "TrainerPending: waiting for trainer report",
                    "updated_at": iso_ts(now_local()),
                },
            )
    except Exception as exc:
        status = "pending" if attempt < max(1, max_retries) else "failed"
        summary = f"{exc.__class__.__name__}: {exc}"
        trainer_ref = training_record_path(root, analysis_id).as_posix()
        upsert_training_task_record(
            root,
            analysis_id,
            {
                **(get_training_task_record(root, analysis_id) or {}),
                "training_id": training_id,
                "status": status,
                "last_error": summary,
                "updated_at": iso_ts(now_local()),
            },
        )
    persist_event(
        root,
        {
            "event_id": event_id(),
            "timestamp": iso_ts(now_local()),
            "session_id": session_id,
            "actor": "trainer",
            "stage": "train",
            "action": "run_training",
            "status": "success" if status == "done" else "failed",
            "latency_ms": 0,
            "task_id": training_id,
            "reason_tags": [] if status == "done" else [status],
            "ref": trainer_ref,
        },
    )
    return {
        "training_id": training_id,
        "status": status,
        "attempt": attempt,
        "trainer_run_ref": trainer_ref,
        "summary": summary,
        "session_id": session_id,
    }

def run_analysis_worker(cfg: AppConfig, state: RuntimeState, workflow_id: str) -> None:
    workflow: dict[str, Any] | None = None
    policy_snapshot: dict[str, Any] | None = None
    run_id = ""
    target_message_ids: list[int] = []
    session_id = ""
    analysis_id = ""
    try:
        workflow = get_training_workflow(cfg.root, workflow_id)
        if not workflow:
            return
        try:
            policy_snapshot = load_workflow_session_policy_snapshot(cfg.root, workflow)
        except WorkflowGateError as exc:
            update_training_workflow_fields(
                cfg.root,
                workflow_id,
                {
                    "status": "failed",
                    "latest_no_value_reason": AGENT_POLICY_ERROR_CODE,
                },
            )
            append_training_workflow_event(
                cfg.root,
                workflow,
                "analysis",
                "failed",
                {
                    "analysis_run_id": "",
                    "error": str(exc),
                    "policy_error": exc.code,
                },
                policy_snapshot=None,
            )
            append_failure_case(
                cfg.root,
                "analysis_worker_failed",
                f"workflow_id={workflow_id}, err={exc}, code={exc.code}",
            )
            return
        session_id = str(workflow.get("session_id") or "")
        analysis_id = str(workflow.get("analysis_id") or "")
        context_rows = list_session_dialogue_messages(cfg.root, session_id, limit=0)
        context_message_ids = [int(item.get("message_id") or 0) for item in context_rows if int(item.get("message_id") or 0) > 0]
        target_message_ids = [
            int(item.get("message_id") or 0)
            for item in context_rows
            if str(item.get("analysis_state") or ANALYSIS_STATE_PENDING) != ANALYSIS_STATE_DONE
            and int(item.get("message_id") or 0) > 0
        ]
        if not target_message_ids:
            update_training_workflow_fields(
                cfg.root,
                workflow_id,
                {
                    "status": "analyzed",
                    "latest_no_value_reason": "all_messages_analyzed",
                },
            )
            append_training_workflow_event(
                cfg.root,
                workflow,
                "analysis",
                "skipped",
                {
                    "reason": "all_messages_analyzed",
                    "context_mode": "full_session",
                    "context_message_count": len(context_message_ids),
                },
                policy_snapshot=policy_snapshot,
            )
            return

        run_id = create_analysis_run(
            cfg.root,
            workflow_id,
            analysis_id,
            session_id,
            context_message_ids=context_message_ids,
            target_message_ids=target_message_ids,
        )
        update_training_workflow_fields(
            cfg.root,
            workflow_id,
            {
                "status": "analyzing",
                "latest_analysis_run_id": run_id,
                "latest_no_value_reason": "",
            },
        )
        append_training_workflow_event(
            cfg.root,
            workflow,
            "analysis",
            "running",
            {
                "step": "collect_context",
                "analysis_run_id": run_id,
                "context_mode": "full_session",
                "context_message_count": len(context_message_ids),
                "target_message_count": len(target_message_ids),
            },
            policy_snapshot=policy_snapshot,
        )
        time.sleep(0.2)
        summary, recommendation, latest_user, snapshot_target_ids, no_value_reason = (
            build_analysis_snapshot_with_context(cfg.root, session_id)
        )
        summary = append_policy_to_analysis_summary(summary, policy_snapshot)
        if snapshot_target_ids:
            cleaned_ids: list[int] = []
            for raw in snapshot_target_ids:
                try:
                    num = int(raw)
                except Exception:
                    continue
                if num > 0:
                    cleaned_ids.append(num)
            if cleaned_ids:
                target_message_ids = cleaned_ids
        append_training_workflow_event(
            cfg.root,
            workflow,
            "analysis",
            "running",
            {
                "step": "summarize",
                "analysis_run_id": run_id,
                "user_sample": latest_user,
            },
            policy_snapshot=policy_snapshot,
        )
        time.sleep(0.2)
        if no_value_reason == "missing_next_context":
            set_message_analysis_state(
                cfg.root,
                session_id,
                target_message_ids,
                state_text=ANALYSIS_STATE_PENDING,
                reason="",
                run_id="",
            )
            update_analysis_run(
                cfg.root,
                run_id,
                status="rollback_wait_next_context",
                no_value_reason=no_value_reason,
                error_text="missing_next_context",
            )
            update_training_workflow_fields(
                cfg.root,
                workflow_id,
                {
                    "status": "assigned",
                    "analysis_summary": summary,
                    "analysis_recommendation": "need_info",
                    "latest_no_value_reason": no_value_reason,
                },
            )
            workflow_after = get_training_workflow(cfg.root, workflow_id) or workflow
            append_training_workflow_event(
                cfg.root,
                workflow_after,
                "analysis",
                "failed",
                {
                    "analysis_run_id": run_id,
                    "reason": no_value_reason,
                    "rollback": True,
                    "message_state_after": ANALYSIS_STATE_PENDING,
                },
                policy_snapshot=policy_snapshot,
            )
            return

        reason_text = no_value_reason if no_value_reason else ""
        set_message_analysis_state(
            cfg.root,
            session_id,
            target_message_ids,
            state_text=ANALYSIS_STATE_DONE,
            reason=reason_text,
            run_id=run_id,
        )
        update_analysis_run(
            cfg.root,
            run_id,
            status="success_no_value" if no_value_reason else "success",
            no_value_reason=no_value_reason,
            error_text="",
        )
        update_training_workflow_fields(
            cfg.root,
            workflow_id,
            {
                "status": "analyzed",
                "analysis_summary": summary,
                "analysis_recommendation": "skip" if no_value_reason else recommendation,
                "latest_no_value_reason": no_value_reason,
                "latest_analysis_run_id": run_id,
            },
        )
        workflow_after = get_training_workflow(cfg.root, workflow_id) or workflow
        append_training_workflow_event(
            cfg.root,
            workflow_after,
            "analysis",
            "success",
            {
                "summary": summary,
                "analysis_run_id": run_id,
                "recommendation": "skip" if no_value_reason else recommendation,
                "no_value_reason": no_value_reason,
                "target_message_count": len(target_message_ids),
            },
            policy_snapshot=policy_snapshot,
        )
    except Exception as exc:
        if session_id and target_message_ids:
            set_message_analysis_state(
                cfg.root,
                session_id,
                target_message_ids,
                state_text=ANALYSIS_STATE_PENDING,
                reason="",
                run_id="",
            )
        if run_id:
            update_analysis_run(
                cfg.root,
                run_id,
                status="failed",
                no_value_reason="",
                error_text=str(exc),
            )
        workflow = get_training_workflow(cfg.root, workflow_id)
        if workflow:
            update_training_workflow_fields(
                cfg.root,
                workflow_id,
                {
                    "status": "failed",
                    "latest_no_value_reason": "analysis_failed",
                },
            )
            append_training_workflow_event(
                cfg.root,
                workflow,
                "analysis",
                "failed",
                {
                    "analysis_run_id": run_id,
                    "error": str(exc),
                    "rollback": True,
                },
                policy_snapshot=policy_snapshot,
            )
        append_failure_case(cfg.root, "analysis_worker_failed", f"workflow_id={workflow_id}, err={exc}")
    finally:
        with state.workflow_lock:
            state.analyzing_workflows.discard(workflow_id)

def start_analysis_worker(cfg: AppConfig, state: RuntimeState, workflow_id: str) -> bool:
    with state.workflow_lock:
        if workflow_id in state.analyzing_workflows:
            return False
        state.analyzing_workflows.add(workflow_id)
    thread = threading.Thread(
        target=run_analysis_worker,
        args=(cfg, state, workflow_id),
        daemon=True,
        name=f"workflow-analysis-{workflow_id}",
    )
    thread.start()
    return True

def assign_training_workflow(
    cfg: AppConfig,
    state: RuntimeState,
    workflow_id: str,
    analyst: str,
    note: str = "",
) -> dict[str, Any]:
    sync_training_workflows(cfg.root)
    workflow = get_training_workflow(cfg.root, workflow_id)
    if not workflow:
        raise RuntimeError(f"workflow not found: {workflow_id}")
    policy_snapshot = load_workflow_session_policy_snapshot(cfg.root, workflow)
    gate = session_analysis_gate(cfg.root, str(workflow.get("session_id") or ""))
    if not bool(gate.get("analysis_selectable")):
        code = str(gate.get("analysis_block_reason_code") or "workflow_not_selectable")
        message = str(gate.get("analysis_block_reason") or "当前会话不可进入分析")
        raise WorkflowGateError(
            409,
            message,
            code,
            extra={
                "workflow_id": workflow_id,
                "session_id": str(workflow.get("session_id") or ""),
                "unanalyzed_message_count": int(gate.get("unanalyzed_message_count") or 0),
            },
        )
    analyst_text = safe_token(analyst, "", 80)
    if not analyst_text:
        raise RuntimeError("analyst required")
    update_training_workflow_fields(
        cfg.root,
        workflow_id,
        {
            "status": "assigned",
            "assigned_analyst": analyst_text,
            "assignment_note": note[:200],
        },
    )
    workflow_after = get_training_workflow(cfg.root, workflow_id) or workflow
    append_training_workflow_event(
        cfg.root,
        workflow_after,
        "assignment",
        "success",
        {
            "analyst": analyst_text,
            "note": note[:200],
        },
        policy_snapshot=policy_snapshot,
    )
    started = start_analysis_worker(cfg, state, workflow_id)
    append_change_log(
        cfg.root,
        "workflow assignment",
        f"workflow_id={workflow_id}, analyst={analyst_text}, analysis_started={started}",
    )
    return workflow_after

def generate_training_workflow_plan(cfg: AppConfig, workflow_id: str) -> dict[str, Any]:
    sync_training_workflows(cfg.root)
    workflow = get_training_workflow(cfg.root, workflow_id)
    if not workflow:
        raise RuntimeError(f"workflow not found: {workflow_id}")
    policy_snapshot = load_workflow_session_policy_snapshot(cfg.root, workflow)
    policy_summary_text_value = session_policy_summary(policy_snapshot)
    run = latest_analysis_run(cfg.root, workflow_id)
    run_id = str((run or {}).get("analysis_run_id") or "")
    summary = str(workflow.get("analysis_summary") or "").strip()
    recommendation = str(workflow.get("analysis_recommendation") or "").strip()
    latest_user: list[str] = []
    evidence_message_ids: list[int] = []
    no_value_reason = str((run or {}).get("no_value_reason") or "")
    if run:
        for raw in (run.get("target_message_ids") or []):
            try:
                num = int(raw)
            except Exception:
                continue
            if num > 0:
                evidence_message_ids.append(num)
    if not summary or not recommendation:
        summary, recommendation, latest_user, target_ids, reason_code = (
            build_analysis_snapshot_with_context(cfg.root, str(workflow.get("session_id") or ""))
        )
        if target_ids:
            evidence_message_ids = []
            for raw in target_ids:
                try:
                    num = int(raw)
                except Exception:
                    continue
                if num > 0:
                    evidence_message_ids.append(num)
        if not no_value_reason:
            no_value_reason = reason_code
    summary = append_policy_to_analysis_summary(summary, policy_snapshot)
    if no_value_reason:
        recommendation = "skip"
    plan = build_training_plan(
        summary,
        recommendation or "train",
        latest_user,
        message_ids=evidence_message_ids,
        no_value_reason=no_value_reason,
        policy_summary_text_value=policy_summary_text_value,
    )
    for item in plan:
        item["analysis_run_id"] = run_id
    update_training_workflow_fields(
        cfg.root,
        workflow_id,
        {
            "status": "planned",
            "analysis_summary": summary,
            "analysis_recommendation": recommendation or "train",
            "plan_json": json.dumps(plan, ensure_ascii=False),
            "latest_analysis_run_id": run_id,
            "latest_no_value_reason": no_value_reason,
        },
    )
    if run_id:
        replace_analysis_run_plan_items(cfg.root, workflow_id, run_id, plan)
    workflow_after = get_training_workflow(cfg.root, workflow_id) or workflow
    append_training_workflow_event(
        cfg.root,
        workflow_after,
        "plan",
        "success",
        {
            "analysis_run_id": run_id,
            "recommendation": recommendation or "train",
            "plan_count": len(plan),
            "no_value_reason": no_value_reason,
            "message_count": len(evidence_message_ids),
            "policy_summary": policy_summary_text_value,
        },
        policy_snapshot=policy_snapshot,
    )
    append_change_log(
        cfg.root,
        "workflow plan generated",
        (
            f"workflow_id={workflow_id}, recommendation={recommendation or 'train'}, "
            f"plan_count={len(plan)}, analysis_run_id={run_id or 'none'}, no_value_reason={no_value_reason or 'none'}"
        ),
    )
    return {
        "workflow_id": workflow_id,
        "analysis_id": workflow_after.get("analysis_id"),
        "plan": plan,
        "analysis_run_id": run_id,
        "analysis_summary": summary,
        "analysis_recommendation": recommendation or "train",
        "no_value_reason": no_value_reason,
        "policy_summary": policy_summary_text_value,
    }

def execute_training_workflow_plan(
    cfg: AppConfig,
    workflow_id: str,
    selected_items: list[str],
    *,
    max_retries: int,
) -> dict[str, Any]:
    sync_training_workflows(cfg.root)
    workflow = get_training_workflow(cfg.root, workflow_id)
    if not workflow:
        raise RuntimeError(f"workflow not found: {workflow_id}")
    policy_snapshot = load_workflow_session_policy_snapshot(cfg.root, workflow)
    policy_summary_text_value = session_policy_summary(policy_snapshot)
    selected: list[str] = []
    seen: set[str] = set()
    for raw in selected_items:
        item = safe_token(str(raw or ""), "", 80)
        if not item or item in seen:
            continue
        selected.append(item)
        seen.add(item)
    if not selected:
        raise RuntimeError("selected_items required")

    has_train = "decision_train" in selected
    has_skip = "decision_skip" in selected
    if has_train == has_skip:
        raise RuntimeError("select exactly one of decision_train / decision_skip")
    decision = "train" if has_train else "skip"
    run_training = "execute_training" in selected

    update_training_workflow_fields(
        cfg.root,
        workflow_id,
        {
            "status": "selected",
            "selected_plan_json": json.dumps(selected, ensure_ascii=False),
        },
    )
    workflow_after_select = get_training_workflow(cfg.root, workflow_id) or workflow
    append_training_workflow_event(
        cfg.root,
        workflow_after_select,
        "select",
        "success",
        {
            "selected_items": selected,
            "decision": decision,
            "run_training": run_training,
            "policy_summary": policy_summary_text_value,
        },
        policy_snapshot=policy_snapshot,
    )

    decision_result = apply_analysis_decision(
        cfg.root,
        workflow_after_select,
        decision=decision,
        reason=f"workflow_plan_selected; {policy_summary_text_value}",
    )
    append_training_workflow_event(
        cfg.root,
        workflow_after_select,
        "train",
        "running" if decision == "train" and run_training else ("skipped" if decision == "skip" else "pending"),
        {
            "decision": decision,
            "decision_ref": decision_result.get("decision_ref"),
            "training_id": decision_result.get("training_id"),
            "policy_summary": policy_summary_text_value,
        },
        policy_snapshot=policy_snapshot,
    )

    if decision != "train":
        skip_summary = "decision=skip, training not executed"
        update_training_workflow_fields(
            cfg.root,
            workflow_id,
            {
                "status": "done",
                "train_result_ref": str(decision_result.get("decision_ref") or ""),
                "train_result_summary": skip_summary,
            },
        )
        append_change_log(
            cfg.root,
            "workflow executed",
            f"workflow_id={workflow_id}, decision=skip",
        )
        return {
            "workflow_id": workflow_id,
            "decision": decision,
            "status": "done",
            "summary": skip_summary,
            "decision_ref": decision_result.get("decision_ref"),
            "policy_summary": policy_summary_text_value,
        }

    if not run_training:
        pending_summary = "decision=train written; execute_training not selected"
        update_training_workflow_fields(
            cfg.root,
            workflow_id,
            {
                "status": "planned",
                "train_result_ref": str(decision_result.get("decision_ref") or ""),
                "train_result_summary": pending_summary,
            },
        )
        append_change_log(
            cfg.root,
            "workflow executed",
            f"workflow_id={workflow_id}, decision=train, training_skipped",
        )
        return {
            "workflow_id": workflow_id,
            "decision": decision,
            "status": "planned",
            "summary": pending_summary,
            "decision_ref": decision_result.get("decision_ref"),
            "training_id": decision_result.get("training_id"),
            "policy_summary": policy_summary_text_value,
        }

    training_result = run_training_once_for_analysis(
        cfg.root,
        str(workflow_after_select.get("analysis_id") or ""),
        max_retries=max(1, int(max_retries)),
    )
    result_status = str(training_result.get("status") or "failed")
    wf_status = "done" if result_status == "done" else ("failed" if result_status == "failed" else "training")
    update_training_workflow_fields(
        cfg.root,
        workflow_id,
        {
            "status": wf_status,
            "train_result_ref": str(training_result.get("trainer_run_ref") or ""),
            "train_result_summary": str(training_result.get("summary") or ""),
        },
    )
    workflow_after_train = get_training_workflow(cfg.root, workflow_id) or workflow_after_select
    append_training_workflow_event(
        cfg.root,
        workflow_after_train,
        "train",
        "success" if result_status == "done" else "failed",
        training_result,
        policy_snapshot=policy_snapshot,
    )
    append_change_log(
        cfg.root,
        "workflow executed",
        (
            f"workflow_id={workflow_id}, decision=train, training_status={result_status}, "
            f"training_id={training_result.get('training_id','')}"
        ),
    )
    return {
        "workflow_id": workflow_id,
        "decision": decision,
        "status": wf_status,
        "training": training_result,
        "decision_ref": decision_result.get("decision_ref"),
        "policy_summary": policy_summary_text_value,
    }
