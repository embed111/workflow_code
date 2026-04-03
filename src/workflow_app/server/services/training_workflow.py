from __future__ import annotations

from . import training_workflow_execution_service as _execution_service
from .work_record_store import (
    append_workflow_event_record,
    ensure_workflow_record,
    get_training_task_record,
    list_analysis_records,
    list_session_message_records,
    list_workflow_event_records,
    list_workflow_records,
    session_work_record_count,
    update_workflow_record,
    upsert_analysis_record,
    upsert_training_task_record,
)


def bind_runtime_symbols(symbols: dict[str, object]) -> None:
    globals().update(symbols)
    _execution_service.bind_runtime_symbols(globals())

def detect_context_gap(records: list[dict[str, Any]]) -> str:
    if not records:
        return "no_training_value"
    first_role = str(records[0].get("role") or "")
    last_role = str(records[-1].get("role") or "")
    if first_role == "assistant":
        return "missing_previous_context"
    if last_role == "user":
        return "missing_next_context"
    return ""


def sync_training_workflows(root: Path) -> int:
    created = 0
    existing_by_analysis = {
        str(item.get("analysis_id") or ""): dict(item) for item in list_workflow_records(root)
    }
    for analysis in list_analysis_records(root):
        analysis_id = str(analysis.get("analysis_id") or "")
        session_id = str(analysis.get("session_id") or "")
        if not analysis_id or not session_id:
            continue
        if not session_has_work_records(root, session_id):
            continue
        created_at = str(analysis.get("created_at") or iso_ts(now_local()))
        updated_at = str(analysis.get("updated_at") or created_at)
        current = existing_by_analysis.get(analysis_id) or {}
        workflow_id = str(current.get("workflow_id") or workflow_id_for_analysis(analysis_id))
        _record, was_created = ensure_workflow_record(
            root,
            workflow_id,
            {
                "analysis_id": analysis_id,
                "session_id": session_id,
                "status": str(current.get("status") or "queued"),
                "created_at": str(current.get("created_at") or created_at),
                "updated_at": str(current.get("updated_at") or updated_at),
            },
        )
        created += int(was_created)
    return created


def list_training_workflows(
    root: Path,
    limit: int = 300,
    *,
    include_test_data: bool = True,
) -> list[dict[str, Any]]:
    sync_training_workflows(root)
    analysis_map = {
        str(item.get("analysis_id") or ""): dict(item) for item in list_analysis_records(root)
    }
    out: list[dict[str, Any]] = []
    for workflow in list_workflow_records(root):
        session_id = str(workflow.get("session_id") or "")
        analysis_id = str(workflow.get("analysis_id") or "")
        if not session_id or not analysis_id:
            continue
        session = get_session(root, session_id)
        is_test_data = bool((session or {}).get("is_test_data"))
        if (not include_test_data) and is_test_data:
            continue
        if not session_has_work_records(root, session_id):
            continue
        analysis = analysis_map.get(analysis_id) or {}
        training = get_training_task_record(root, analysis_id) or {}
        message_rows = list_session_message_records(root, session_id)
        latest_user_message = next(
            (
                str(item.get("content") or "")
                for item in reversed(message_rows)
                if str(item.get("role") or "") == "user" and str(item.get("content") or "").strip()
            ),
            "",
        )
        latest_assistant_message = next(
            (
                str(item.get("content") or "")
                for item in reversed(message_rows)
                if str(item.get("role") or "") == "assistant" and str(item.get("content") or "").strip()
            ),
            "",
        )
        item: dict[str, Any] = {
            "workflow_id": str(workflow.get("workflow_id") or ""),
            "analysis_id": analysis_id,
            "session_id": session_id,
            "is_test_data": is_test_data,
            "workflow_status": str(workflow.get("status") or workflow.get("workflow_status") or ""),
            "assigned_analyst": str(workflow.get("assigned_analyst") or ""),
            "assignment_note": str(workflow.get("assignment_note") or ""),
            "analysis_summary": str(workflow.get("analysis_summary") or ""),
            "analysis_recommendation": str(workflow.get("analysis_recommendation") or ""),
            "latest_analysis_run_id": str(workflow.get("latest_analysis_run_id") or ""),
            "latest_no_value_reason": str(workflow.get("latest_no_value_reason") or ""),
            "plan_json": str(workflow.get("plan_json") or "[]"),
            "selected_plan_json": str(workflow.get("selected_plan_json") or "[]"),
            "train_result_ref": str(workflow.get("train_result_ref") or ""),
            "train_result_summary": str(workflow.get("train_result_summary") or ""),
            "updated_at": str(workflow.get("updated_at") or ""),
            "created_at": str(workflow.get("created_at") or ""),
            "analysis_status": str(analysis.get("status") or ""),
            "decision": str(analysis.get("decision") or ""),
            "decision_reason": str(analysis.get("decision_reason") or ""),
            "training_id": str(training.get("training_id") or ""),
            "training_status": str(training.get("status") or ""),
            "trainer_run_ref": str(training.get("trainer_run_ref") or ""),
            "result_summary": str(training.get("result_summary") or ""),
            "last_error": str(training.get("last_error") or ""),
            "latest_user_message": latest_user_message,
            "latest_assistant_message": latest_assistant_message,
        }
        item["plan"] = parse_json_list(item.get("plan_json"))
        item["selected_plan"] = parse_json_list(item.get("selected_plan_json"))
        records = list_session_work_records(root, session_id, limit=60)
        item["work_records"] = records
        item["work_record_preview"] = work_record_preview(records)
        item["work_record_count"] = session_work_record_count(root, session_id)
        item["training_plan_item_count"] = max(
            workflow_plan_item_count(item.get("plan_json")),
            workflow_plan_item_count(item.get("selected_plan_json")),
        )
        item.update(session_analysis_gate(root, session_id))
        latest_run = latest_analysis_run(root, str(item.get("workflow_id") or ""))
        if latest_run:
            item["latest_analysis_run_id"] = str(latest_run.get("analysis_run_id") or "")
            item["latest_no_value_reason"] = str(latest_run.get("no_value_reason") or "")
        out.append(item)
    out.sort(key=lambda item: (str(item.get("updated_at") or ""), str(item.get("created_at") or "")), reverse=True)
    return out[: max(1, min(limit, 2000))]


def get_training_workflow(root: Path, workflow_id: str) -> dict[str, Any] | None:
    item = next(
        (
            row
            for row in list_training_workflows(root, limit=2000, include_test_data=True)
            if str(row.get("workflow_id") or "") == str(workflow_id or "")
        ),
        None,
    )
    return dict(item) if item else None


def update_training_workflow_fields(root: Path, workflow_id: str, fields: dict[str, Any]) -> None:
    if not fields:
        return
    allowed = {
        "status",
        "assigned_analyst",
        "assignment_note",
        "analysis_summary",
        "analysis_recommendation",
        "latest_analysis_run_id",
        "latest_no_value_reason",
        "plan_json",
        "selected_plan_json",
        "train_result_ref",
        "train_result_summary",
        "session_id",
    }
    for key, value in fields.items():
        if key not in allowed:
            continue
    patch = {key: value for key, value in fields.items() if key in allowed}
    if not patch:
        return
    patch["updated_at"] = iso_ts(now_local())
    update_workflow_record(root, workflow_id, patch)


def load_workflow_session_policy_snapshot(root: Path, workflow: dict[str, Any]) -> dict[str, Any]:
    session_id = str(workflow.get("session_id") or "")
    if not session_id:
        raise WorkflowGateError(
            409,
            "workflow missing session_id",
            AGENT_POLICY_ERROR_CODE,
            extra={"workflow_id": str(workflow.get("workflow_id") or ""), "session_id": ""},
        )
    session = get_session(root, session_id)
    if not session:
        raise WorkflowGateError(
            404,
            "session not found for workflow",
            "session_not_found",
            extra={"workflow_id": str(workflow.get("workflow_id") or ""), "session_id": session_id},
        )
    try:
        return ensure_session_policy_snapshot(root, session)
    except SessionGateError as exc:
        raise WorkflowGateError(
            exc.status_code,
            str(exc),
            AGENT_POLICY_ERROR_CODE,
            extra={
                "workflow_id": str(workflow.get("workflow_id") or ""),
                "session_id": session_id,
                **exc.extra,
            },
        ) from exc


def policy_alignment_payload(
    snapshot: dict[str, Any] | None,
    *,
    stage: str,
) -> dict[str, Any]:
    if not snapshot:
        return {
            "policy_alignment": POLICY_ALIGNMENT_DEVIATED,
            "policy_alignment_reason": "session_policy_missing",
            "policy_stage": stage,
            "policy_source_type": "auto",
            "policy_source": {
                "policy_source": "auto",
                "agents_hash": "",
                "agents_version": "",
                "agents_path": "",
            },
        }
    source = snapshot.get("source") if isinstance(snapshot.get("source"), dict) else {}
    source_type = session_policy_source_type(snapshot)
    return {
        "policy_alignment": POLICY_ALIGNMENT_ALIGNED,
        "policy_alignment_reason": "session_policy_injected",
        "policy_stage": stage,
        "policy_summary": session_policy_summary(snapshot),
        "policy_source_type": source_type,
        "policy_source": {
            "policy_source": source_type,
            "agents_hash": str((source or {}).get("agents_hash") or ""),
            "agents_version": str((source or {}).get("agents_version") or ""),
            "agents_path": str((source or {}).get("agents_path") or ""),
        },
    }


def append_training_workflow_event(
    root: Path,
    workflow: dict[str, Any],
    stage: str,
    status: str,
    payload: dict[str, Any],
    *,
    policy_snapshot: dict[str, Any] | None = None,
) -> int:
    workflow_id = str(workflow.get("workflow_id") or "")
    analysis_id = str(workflow.get("analysis_id") or "")
    session_id = str(workflow.get("session_id") or "")
    created_at = iso_ts(now_local())
    snapshot_obj = policy_snapshot
    if snapshot_obj is None and session_id:
        session = get_session(root, session_id)
        if session:
            try:
                snapshot_obj = ensure_session_policy_snapshot(root, session)
            except SessionGateError:
                snapshot_obj = None
    payload_obj = dict(payload or {})
    for key, value in policy_alignment_payload(snapshot_obj, stage=stage).items():
        payload_obj.setdefault(key, value)
    event_num = append_workflow_event_record(
        root,
        workflow_id,
        {
            "created_at": created_at,
            "workflow_id": workflow_id,
            "analysis_id": analysis_id,
            "session_id": session_id,
            "stage": stage,
            "status": status,
            "payload": payload_obj,
        },
    )
    persist_event(
        root,
        {
            "event_id": event_id(),
            "timestamp": created_at,
            "session_id": session_id or "sess-training",
            "actor": "workflow",
            "stage": "training_workflow",
            "action": stage,
            "status": status,
            "latency_ms": 0,
            "task_id": workflow_id,
            "reason_tags": [
                status,
                f"policy_alignment:{str(payload_obj.get('policy_alignment') or POLICY_ALIGNMENT_DEVIATED)}",
                f"policy_reason:{str(payload_obj.get('policy_alignment_reason') or 'unknown')}",
                f"policy_source:{str(payload_obj.get('policy_source_type') or 'auto')}",
            ],
            "ref": relative_to_root(root, event_file(root)),
        },
    )
    return event_num


def list_training_workflow_events(
    root: Path,
    workflow_id: str,
    *,
    since_id: int = 0,
    limit: int = 400,
) -> list[dict[str, Any]]:
    return list_workflow_event_records(
        root,
        workflow_id,
        since_id=max(0, since_id),
        limit=max(1, min(limit, 2000)),
    )


def build_analysis_snapshot_with_context(
    root: Path,
    session_id: str,
    *,
    policy_snapshot: dict[str, Any] | None = None,
) -> tuple[str, str, list[str], list[int], str]:
    records = list_session_dialogue_messages(root, session_id, limit=0)
    user_msgs = [str(item.get("content") or "").strip() for item in records if item.get("role") == "user"]
    assistant_msgs = [item for item in records if item.get("role") == "assistant"]
    latest_user = [text for text in user_msgs if text][-3:]
    target_message_ids = [
        int(item.get("message_id") or 0)
        for item in records
        if str(item.get("analysis_state") or ANALYSIS_STATE_PENDING) != ANALYSIS_STATE_DONE
    ]
    gap_reason = detect_context_gap(records)
    recommendation = "train" if len(user_msgs) >= 1 else "skip"
    no_value_reason = ""
    if gap_reason in {"missing_previous_context", "missing_next_context"}:
        recommendation = "skip"
        no_value_reason = gap_reason
    elif not user_msgs:
        recommendation = "skip"
        no_value_reason = "no_training_value"
    elif all(len(text) <= 2 for text in user_msgs if text):
        recommendation = "skip"
        no_value_reason = "no_training_value"
    summary_parts = [
        f"context_mode=full_session",
        f"message_count={len(records)}",
        f"user_turns={len(user_msgs)}",
        f"assistant_turns={len(assistant_msgs)}",
        f"target_unanalyzed={len(target_message_ids)}",
        f"latest_user={' | '.join(latest_user) if latest_user else 'none'}",
        f"context_gap={gap_reason or 'none'}",
    ]
    if policy_snapshot:
        source = policy_snapshot.get("source") if isinstance(policy_snapshot.get("source"), dict) else {}
        source_type = session_policy_source_type(policy_snapshot)
        summary_parts.extend(
            [
                f"policy_goal={first_non_empty_sentence(str(policy_snapshot.get('session_goal') or ''), max_chars=80)}",
                f"policy_alignment={POLICY_ALIGNMENT_ALIGNED}",
                f"policy_source={source_type}",
                f"policy_source_version={str((source or {}).get('agents_version') or '')}",
            ]
        )
    else:
        summary_parts.append(f"policy_alignment={POLICY_ALIGNMENT_DEVIATED}")
    return "; ".join(summary_parts), recommendation, latest_user, target_message_ids, no_value_reason


def build_analysis_snapshot(root: Path, session_id: str) -> tuple[str, str, list[str]]:
    summary, recommendation, latest_user, _target_message_ids, _no_value_reason = (
        build_analysis_snapshot_with_context(root, session_id)
    )
    return summary, recommendation, latest_user


def build_training_plan(
    summary: str,
    recommendation: str,
    latest_user: list[str],
    *,
    message_ids: list[int],
    no_value_reason: str = "",
    policy_summary_text_value: str = "",
) -> list[dict[str, Any]]:
    if no_value_reason:
        return []
    latest = " / ".join(latest_user) if latest_user else "no recent user turns"
    train_selected = recommendation == "train"
    skip_selected = recommendation != "train"
    evidence_ids: list[int] = []
    for raw in message_ids:
        try:
            num = int(raw)
        except Exception:
            continue
        if num > 0:
            evidence_ids.append(num)
    return [
        {
            "item_id": "decision_train",
            "title": "判定入训（train）",
            "description": f"依据分析摘要执行 train。summary={summary}; policy={policy_summary_text_value or 'none'}",
            "selected": train_selected,
            "kind": "decision",
            "decision": "train",
            "message_ids": evidence_ids,
            "policy_summary": policy_summary_text_value,
        },
        {
            "item_id": "decision_skip",
            "title": "判定跳过（skip）",
            "description": f"当前不进入训练，保留追踪记录。policy={policy_summary_text_value or 'none'}",
            "selected": skip_selected,
            "kind": "decision",
            "decision": "skip",
            "message_ids": evidence_ids,
            "policy_summary": policy_summary_text_value,
        },
        {
            "item_id": "execute_training",
            "title": "执行训练并回写",
            "description": f"触发训练执行并写入 trainer_run_ref。policy={policy_summary_text_value or 'none'}",
            "selected": train_selected,
            "kind": "train",
            "message_ids": evidence_ids,
            "policy_summary": policy_summary_text_value,
        },
        {
            "item_id": "collect_notes",
            "title": "沉淀分析记录",
            "description": f"最近上下文：{latest}；policy={policy_summary_text_value or 'none'}",
            "selected": True,
            "kind": "record",
            "message_ids": evidence_ids,
            "policy_summary": policy_summary_text_value,
        },
    ]


def apply_analysis_decision(root: Path, workflow: dict[str, Any], decision: str, reason: str) -> dict[str, Any]:
    analysis_id = str(workflow.get("analysis_id") or "")
    session_id = str(workflow.get("session_id") or "")
    if decision not in {"train", "skip", "need_info"}:
        raise RuntimeError(f"invalid decision: {decision}")
    ts = now_local()
    status = decision_to_status(decision)
    training_id = ""
    analysis_record = next(
        (
            item
            for item in list_analysis_records(root)
            if str(item.get("analysis_id") or "") == analysis_id
        ),
        {},
    )
    upsert_analysis_record(
        root,
        analysis_id,
        {
            **analysis_record,
            "session_id": session_id,
            "status": status,
            "decision": decision,
            "decision_reason": reason,
            "updated_at": iso_ts(ts),
        },
    )
    if decision == "train":
        current_training = get_training_task_record(root, analysis_id) or {}
        training_id = str(current_training.get("training_id") or create_training_id(analysis_id))
        upsert_training_task_record(
            root,
            analysis_id,
            {
                **current_training,
                "training_id": training_id,
                "status": str(current_training.get("status") or "pending"),
                "attempts": int(current_training.get("attempts") or 0),
                "created_at": str(current_training.get("created_at") or iso_ts(ts)),
                "updated_at": iso_ts(ts),
            },
        )

    decision_ref = append_decision_log(
        root,
        ts,
        analysis_id=analysis_id,
        session_id=session_id,
        decision=decision,
        reason=reason,
    )
    persist_event(
        root,
        {
            "event_id": event_id(),
            "timestamp": iso_ts(ts),
            "session_id": session_id,
            "actor": "workflow",
            "stage": "analyze",
            "action": "decision",
            "status": "success",
            "latency_ms": 0,
            "task_id": analysis_id,
            "reason_tags": [decision],
            "ref": decision_ref,
        },
    )
    return {"analysis_status": status, "decision_ref": decision_ref, "training_id": training_id}

def run_training_once_for_analysis(
    root: Path,
    analysis_id: str,
    *,
    max_retries: int,
) -> dict[str, Any]:
    return _execution_service.run_training_once_for_analysis(
        root,
        analysis_id,
        max_retries=max_retries,
    )


def run_analysis_worker(cfg: AppConfig, state: RuntimeState, workflow_id: str) -> None:
    _execution_service.run_analysis_worker(cfg, state, workflow_id)


def start_analysis_worker(cfg: AppConfig, state: RuntimeState, workflow_id: str) -> bool:
    return _execution_service.start_analysis_worker(cfg, state, workflow_id)


def assign_training_workflow(
    cfg: AppConfig,
    state: RuntimeState,
    workflow_id: str,
    analyst: str,
    note: str = "",
) -> dict[str, Any]:
    return _execution_service.assign_training_workflow(cfg, state, workflow_id, analyst, note)


def generate_training_workflow_plan(cfg: AppConfig, workflow_id: str) -> dict[str, Any]:
    return _execution_service.generate_training_workflow_plan(cfg, workflow_id)


def execute_training_workflow_plan(
    cfg: AppConfig,
    workflow_id: str,
    selected_items: list[str],
    *,
    max_retries: int,
) -> dict[str, Any]:
    return _execution_service.execute_training_workflow_plan(
        cfg,
        workflow_id,
        selected_items,
        max_retries=max_retries,
    )
