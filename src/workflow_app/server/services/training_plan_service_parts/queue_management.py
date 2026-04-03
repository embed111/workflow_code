from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

def bind_runtime_symbols(symbols: dict[str, object]) -> None:
    if not isinstance(symbols, dict):
        return
    target = globals()
    module_name = str(target.get('__name__') or '')
    for key, value in symbols.items():
        if str(key).startswith('__'):
            continue
        current = target.get(key)
        if callable(current) and getattr(current, '__module__', '') == module_name:
            continue
        target[key] = value


EXECUTION_ENGINE = "workflow_native"

_TRAINING_THRESHOLD_BY_PRIORITY = {
    "P0": 86.0,
    "P1": 84.0,
    "P2": 80.0,
    "P3": 76.0,
}

_TRAINING_PRIORITY_BASE_SCORE = {
    "P0": 78.0,
    "P1": 76.0,
    "P2": 74.0,
    "P3": 72.0,
}


def training_eval_run_id_text() -> str:
    ts = now_local()
    return f"ter-{date_key(ts)}-{ts.strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}"


def training_threshold_for_priority(priority: object) -> float:
    key = str(priority or "").strip().upper()
    return float(_TRAINING_THRESHOLD_BY_PRIORITY.get(key, _TRAINING_THRESHOLD_BY_PRIORITY["P1"]))


def summarize_training_eval_runs(
    *,
    priority: object,
    run_results: list[dict[str, Any]],
    previous_avg_score: float | None,
) -> dict[str, Any]:
    threshold = training_threshold_for_priority(priority)
    normalized_runs: list[dict[str, Any]] = []
    for run_index in range(1, 4):
        raw = next(
            (
                item
                for item in run_results
                if int(item.get("run_index") or 0) == run_index
            ),
            None,
        )
        node = dict(raw or {})
        status = str(node.get("status") or ("pending" if raw is None else "")).strip().lower() or "pending"
        score_value = node.get("score")
        score: float | None
        try:
            score = round(float(score_value), 2) if score_value not in (None, "") else None
        except Exception:
            score = None
        normalized_runs.append(
            {
                "eval_run_id": str(node.get("eval_run_id") or "").strip(),
                "queue_task_id": str(node.get("queue_task_id") or "").strip(),
                "round_index": int(node.get("round_index") or 0),
                "run_index": run_index,
                "run_label": f"Run{run_index}",
                "status": status,
                "score": score,
                "summary": str(
                    node.get("summary")
                    or node.get("evaluation_summary")
                    or ""
                ).strip(),
                "started_at": str(node.get("started_at") or "").strip(),
                "finished_at": str(node.get("finished_at") or "").strip(),
                "context_reset": bool(int(node.get("context_reset") or 1)),
                "evidence_ref": str(node.get("evidence_ref") or "").strip(),
                "execution_engine": str(node.get("execution_engine") or EXECUTION_ENGINE).strip() or EXECUTION_ENGINE,
            }
        )

    completed_scores = [
        float(item["score"])
        for item in normalized_runs
        if str(item.get("status") or "").strip().lower() == "done" and item.get("score") is not None
    ]
    all_done = len(completed_scores) == 3 and all(
        str(item.get("status") or "").strip().lower() == "done" and item.get("score") is not None
        for item in normalized_runs
    )

    metrics_available = all_done
    metrics_unavailable_reason = ""
    if not normalized_runs or not any(str(item.get("eval_run_id") or "").strip() for item in normalized_runs):
        metrics_unavailable_reason = "evaluation_not_started"
    elif not all_done:
        metrics_unavailable_reason = "evaluation_partial"

    avg_score = round(sum(completed_scores) / 3.0, 2) if all_done else None
    previous_value = None
    if previous_avg_score not in (None, ""):
        try:
            previous_value = round(float(previous_avg_score), 2)
        except Exception:
            previous_value = None

    decision_code = ""
    decision = ""
    next_action_code = ""
    next_action = ""
    available_actions: list[str] = []

    if metrics_available and avg_score is not None:
        if avg_score >= threshold:
            decision_code = "meet_threshold"
            decision = "达到阈值，当前闭环可结束"
            next_action_code = ""
            next_action = "无需进入下一轮"
        elif previous_value is not None and avg_score < previous_value:
            decision_code = "degraded_vs_previous"
            decision = "较上一轮劣化，建议回退本轮新增"
            next_action_code = "rollback-round-increment"
            next_action = "回退本轮新增"
            available_actions = ["rollback-round-increment"]
        elif previous_value is not None and avg_score > previous_value:
            decision_code = "improved_but_below_threshold"
            decision = "较上一轮提升但未达阈值，建议进入下一轮"
            next_action_code = "enter-next-round"
            next_action = "进入下一轮"
            available_actions = ["enter-next-round"]
        else:
            decision_code = "below_threshold_continue"
            decision = "未达阈值，建议进入下一轮"
            next_action_code = "enter-next-round"
            next_action = "进入下一轮"
            available_actions = ["enter-next-round"]

    return {
        "run_results": normalized_runs,
        "threshold": threshold,
        "avg_score": avg_score,
        "previous_avg_score": previous_value,
        "decision_code": decision_code,
        "decision": decision,
        "next_action_code": next_action_code,
        "next_action": next_action,
        "available_actions": available_actions,
        "metrics_available": metrics_available,
        "metrics_unavailable_reason": metrics_unavailable_reason,
    }


def _training_round_index_for_queue(conn: sqlite3.Connection, queue_task_id: str, plan_id: str) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(p.loop_id,'') AS loop_id
        FROM training_plan p
        WHERE p.plan_id=?
        LIMIT 1
        """,
        (plan_id,),
    ).fetchone()
    loop_id = str(row["loop_id"] or "").strip() if row is not None else ""
    if loop_id:
        loop_row = conn.execute(
            """
            SELECT graph_json
            FROM training_loop_state
            WHERE loop_id=?
            LIMIT 1
            """,
            (loop_id,),
        ).fetchone()
        if loop_row is not None:
            try:
                graph = json.loads(str(loop_row["graph_json"] or "{}"))
            except Exception:
                graph = {}
            nodes = graph.get("nodes") if isinstance(graph, dict) else []
            if isinstance(nodes, list):
                for node in nodes:
                    if not isinstance(node, dict):
                        continue
                    node_qid = str(node.get("queue_task_id") or node.get("node_id") or "").strip()
                    if node_qid != queue_task_id:
                        continue
                    try:
                        ridx = int(node.get("round_index") or 0)
                    except Exception:
                        ridx = 0
                    if ridx > 0:
                        return ridx

    eval_row = conn.execute(
        """
        SELECT MAX(round_index) AS round_index
        FROM training_eval_run
        WHERE queue_task_id=?
        """,
        (queue_task_id,),
    ).fetchone()
    if eval_row is not None:
        try:
            ridx = int(eval_row["round_index"] or 0)
        except Exception:
            ridx = 0
        if ridx > 0:
            return ridx
    return 1


def _deterministic_eval_score(
    *,
    queue_task_id: str,
    priority: str,
    round_index: int,
    run_index: int,
) -> float:
    priority_key = str(priority or "").strip().upper()
    base_score = float(_TRAINING_PRIORITY_BASE_SCORE.get(priority_key, _TRAINING_PRIORITY_BASE_SCORE["P1"]))
    if round_index <= 1:
        round_delta = 0.0
    elif round_index == 2:
        round_delta = -4.0
    else:
        round_delta = min(12.0, float(round_index * 2 + 2))
    run_delta = {-1: -1.5, 0: 0.0, 1: 1.5}.get(run_index - 2, 0.0)
    digest = hashlib.sha1(f"{queue_task_id}:{run_index}".encode("utf-8")).hexdigest()
    variance = float((int(digest[:2], 16) % 3) - 1)
    score = base_score + round_delta + run_delta + variance
    return round(max(0.0, min(100.0, score)), 2)

def _detect_similar_training_plans(
    conn: sqlite3.Connection,
    *,
    target_agent_id: str,
    capability_goal: str,
    training_tasks: list[str],
    acceptance_criteria: str,
    is_test_data: bool = False,
) -> tuple[int, list[str]]:
    test_flag = 1 if is_test_data else 0
    rows = conn.execute(
        """
        SELECT
            p.plan_id,
            p.capability_goal,
            p.training_tasks_json,
            p.acceptance_criteria
        FROM training_plan p
        INNER JOIN training_queue q ON q.plan_id=p.plan_id
        WHERE p.target_agent_id=?
          AND q.status <> 'removed'
          AND COALESCE(p.is_test_data,0)=?
        ORDER BY p.created_at DESC
        LIMIT 120
        """,
        (target_agent_id, test_flag),
    ).fetchall()
    similar_ids: list[str] = []
    for row in rows:
        try:
            existed_tasks = json.loads(str(row["training_tasks_json"] or "[]"))
            if not isinstance(existed_tasks, list):
                existed_tasks = []
        except Exception:
            existed_tasks = []
        if training_plan_similarity_hit(
            candidate_goal=capability_goal,
            candidate_tasks=training_tasks,
            candidate_criteria=acceptance_criteria,
            existing_goal=str(row["capability_goal"] or ""),
            existing_tasks=[str(item or "") for item in existed_tasks],
            existing_criteria=str(row["acceptance_criteria"] or ""),
        ):
            similar_ids.append(str(row["plan_id"] or ""))
    similar_ids = [pid for pid in similar_ids if pid][:8]
    return (1 if similar_ids else 0), similar_ids


def create_training_plan_and_enqueue(
    cfg: AppConfig,
    body: dict[str, Any],
    *,
    forced_source: str | None = None,
) -> dict[str, Any]:
    source = normalize_training_source(
        forced_source if forced_source is not None else body.get("source"),
        default="manual",
    )
    target_agent = str(
        body.get("target_agent_id")
        or body.get("target_agent")
        or body.get("agent_id")
        or body.get("agent_name")
        or ""
    ).strip()
    if not target_agent:
        raise TrainingCenterError(400, "target_agent 必填", "target_agent_required")

    capability_goal = str(body.get("capability_goal") or "").strip()
    if not capability_goal:
        raise TrainingCenterError(400, "capability_goal 必填", "capability_goal_required")
    training_tasks = normalize_training_tasks(body.get("training_tasks"))
    if not training_tasks:
        raise TrainingCenterError(400, "training_tasks 必填", "training_tasks_required")
    acceptance_criteria = str(body.get("acceptance_criteria") or "").strip()
    if not acceptance_criteria:
        raise TrainingCenterError(400, "acceptance_criteria 必填", "acceptance_criteria_required")
    priority = normalize_training_priority(body.get("priority"), required=True)
    operator = safe_token(str(body.get("operator") or "web-user"), "web-user", 80)
    created_by = safe_token(str(body.get("created_by") or operator), operator, 80)
    is_test_data = normalize_training_test_flag(
        body.get("is_test_data", body.get("isTestData")),
        default=False,
    )

    sync_training_agent_registry(cfg)
    conn = connect_db(cfg.root)
    try:
        agent = _resolve_training_agent(conn, target_agent)
        if agent is None:
            raise TrainingCenterError(
                404,
                "target agent not found",
                "target_agent_not_found",
                {"target_agent": target_agent},
            )
        target_agent_id = str(agent.get("agent_id") or "")
        target_agent_name = str(agent.get("agent_name") or "")
        training_gate_state = normalize_training_gate_state(agent.get("training_gate_state"))
        if training_gate_state == "frozen_switched":
            raise TrainingCenterError(
                409,
                "当前 agent 已冻结训练，请切回最新发布版本后再训练",
                "training_frozen_after_switch",
                {"target_agent_id": target_agent_id, "training_gate_state": training_gate_state},
            )

        similar_flag, similar_ids = _detect_similar_training_plans(
            conn,
            target_agent_id=target_agent_id,
            capability_goal=capability_goal,
            training_tasks=training_tasks,
            acceptance_criteria=acceptance_criteria,
            is_test_data=is_test_data,
        )
        plan_id_text = training_plan_id()
        queue_task_id_text = training_queue_task_id()
        ts = iso_ts(now_local())
        execution_engine = EXECUTION_ENGINE
        trainer_match = safe_token(str(body.get("trainer_match") or ""), "", 80)

        conn.execute(
            """
            INSERT INTO training_plan (
                plan_id,loop_id,source,target_agent_id,capability_goal,training_tasks_json,acceptance_criteria,priority,similar_flag,created_by,is_test_data,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                plan_id_text,
                plan_id_text,
                source,
                target_agent_id,
                capability_goal,
                json.dumps(training_tasks, ensure_ascii=False),
                acceptance_criteria,
                priority,
                int(similar_flag),
                created_by,
                1 if is_test_data else 0,
                ts,
            ),
        )
        conn.execute(
            """
            INSERT INTO training_queue (
                queue_task_id,plan_id,priority,status,execution_engine,trainer_match,is_test_data,enqueued_at,started_at,finished_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                queue_task_id_text,
                plan_id_text,
                priority,
                "queued",
                execution_engine,
                trainer_match,
                1 if is_test_data else 0,
                ts,
                "",
                "",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    enqueue_audit_id = append_training_center_audit(
        cfg.root,
        action="enqueue",
        operator=operator,
        target_id=queue_task_id_text,
        detail={
            "plan_id": plan_id_text,
            "source": source,
            "target_agent_id": target_agent_id,
            "target_agent_name": target_agent_name,
            "priority": priority,
            "is_test_data": bool(is_test_data),
            "similar_flag": bool(similar_flag),
            "execution_engine": execution_engine,
        },
    )
    similar_audit_id = ""
    if similar_flag:
        similar_audit_id = append_training_center_audit(
            cfg.root,
            action="mark_similar",
            operator=operator,
            target_id=plan_id_text,
            detail={"similar_plan_ids": similar_ids},
        )

    return {
        "plan_id": plan_id_text,
        "queue_task_id": queue_task_id_text,
        "source": source,
        "target_agent_id": target_agent_id,
        "target_agent_name": target_agent_name,
        "target_agent_lifecycle_state": normalize_lifecycle_state(agent.get("lifecycle_state")),
        "target_agent_training_gate_state": normalize_training_gate_state(agent.get("training_gate_state")),
        "capability_goal": capability_goal,
        "training_tasks": training_tasks,
        "acceptance_criteria": acceptance_criteria,
        "priority": priority,
        "is_test_data": bool(is_test_data),
        "similar_flag": bool(similar_flag),
        "similar_plan_ids": similar_ids,
        "execution_engine": execution_engine,
        "can_execute": normalize_training_gate_state(agent.get("training_gate_state")) != "frozen_switched",
        "audit_ids": {
            "enqueue": enqueue_audit_id,
            "mark_similar": similar_audit_id,
        },
    }


def list_training_queue_items(
    root: Path,
    *,
    include_removed: bool = True,
    include_test_data: bool = True,
) -> list[dict[str, Any]]:
    conn = connect_db(root)
    try:
        sql = """
            SELECT
                q.queue_task_id,q.plan_id,q.priority,q.status,
                COALESCE(q.execution_engine,'workflow_native') AS execution_engine,
                q.enqueued_at,q.started_at,q.finished_at,
                p.source,p.target_agent_id,p.capability_goal,p.training_tasks_json,p.acceptance_criteria,p.similar_flag,p.created_by,p.created_at,p.is_test_data,
                a.agent_name,a.lifecycle_state,a.training_gate_state,
                (
                    SELECT r.run_id
                    FROM training_run r
                    WHERE r.queue_task_id=q.queue_task_id
                    ORDER BY r.updated_at DESC
                    LIMIT 1
                ) AS latest_run_id,
                (
                    SELECT r.status
                    FROM training_run r
                    WHERE r.queue_task_id=q.queue_task_id
                    ORDER BY r.updated_at DESC
                    LIMIT 1
                ) AS latest_run_status,
                (
                    SELECT r.run_ref
                    FROM training_run r
                    WHERE r.queue_task_id=q.queue_task_id
                    ORDER BY r.updated_at DESC
                    LIMIT 1
                ) AS latest_run_ref,
                (
                    SELECT r.result_summary
                    FROM training_run r
                    WHERE r.queue_task_id=q.queue_task_id
                    ORDER BY r.updated_at DESC
                    LIMIT 1
                ) AS latest_result_summary,
                (
                    SELECT r.updated_at
                    FROM training_run r
                    WHERE r.queue_task_id=q.queue_task_id
                    ORDER BY r.updated_at DESC
                    LIMIT 1
                ) AS latest_run_updated_at
            FROM training_queue q
            INNER JOIN training_plan p ON p.plan_id=q.plan_id
            LEFT JOIN agent_registry a ON a.agent_id=p.target_agent_id
            {where_clause}
            ORDER BY
                CASE q.priority
                    WHEN 'P0' THEN 0
                    WHEN 'P1' THEN 1
                    WHEN 'P2' THEN 2
                    WHEN 'P3' THEN 3
                    ELSE 99
                END ASC,
                q.enqueued_at ASC
        """
        where_parts: list[str] = []
        params: list[Any] = []
        if not include_removed:
            where_parts.append("q.status <> 'removed'")
        if not include_test_data:
            where_parts.append("COALESCE(p.is_test_data,0)=0")
        where_clause = ""
        if where_parts:
            where_clause = "WHERE " + " AND ".join(where_parts)
        rows = conn.execute(sql.format(where_clause=where_clause), tuple(params)).fetchall()
    finally:
        conn.close()
    items: list[dict[str, Any]] = []
    for row in rows:
        tasks = []
        try:
            payload = json.loads(str(row["training_tasks_json"] or "[]"))
            if isinstance(payload, list):
                tasks = [str(item or "").strip() for item in payload if str(item or "").strip()]
        except Exception:
            tasks = []
        item = {name: row[name] for name in row.keys()}
        item["training_tasks"] = tasks
        item["is_test_data"] = bool(int(row["is_test_data"] or 0))
        item["similar_flag"] = bool(int(row["similar_flag"] or 0))
        item["priority_rank"] = TRAINING_PRIORITY_RANK.get(str(row["priority"] or "").upper(), 999)
        item["lifecycle_state"] = normalize_lifecycle_state(row["lifecycle_state"])
        item["training_gate_state"] = normalize_training_gate_state(row["training_gate_state"])
        item["can_execute"] = bool(item["training_gate_state"] != "frozen_switched")
        items.append(item)
    return items


def rename_training_queue_item(
    root: Path,
    *,
    queue_task_id_text: str,
    capability_goal: str,
    operator: str,
) -> dict[str, Any]:
    qid = safe_token(str(queue_task_id_text or ""), "", 160)
    if not qid:
        raise TrainingCenterError(400, "queue_task_id required", "queue_task_id_required")
    operator_text = safe_token(str(operator or "web-user"), "web-user", 80)
    next_goal = str(capability_goal or "").strip()
    if not next_goal:
        raise TrainingCenterError(400, "capability_goal required", "capability_goal_required")
    if len(next_goal) > 200:
        raise TrainingCenterError(
            400,
            "capability_goal too long",
            "capability_goal_too_long",
            {"max_length": 200},
        )

    conn = connect_db(root)
    try:
        row = conn.execute(
            """
            SELECT q.queue_task_id,q.plan_id,q.status,
                   p.capability_goal,p.target_agent_id
            FROM training_queue q
            INNER JOIN training_plan p ON p.plan_id=q.plan_id
            WHERE q.queue_task_id=?
            LIMIT 1
            """,
            (qid,),
        ).fetchone()
        if row is None:
            raise TrainingCenterError(404, "queue task not found", "queue_task_not_found", {"queue_task_id": qid})
        status = str(row["status"] or "").strip().lower()
        if status == "removed":
            raise TrainingCenterError(409, "queue task removed", "queue_task_removed", {"queue_task_id": qid})

        old_goal = str(row["capability_goal"] or "").strip()
        if old_goal != next_goal:
            conn.execute(
                """
                UPDATE training_plan
                SET capability_goal=?
                WHERE plan_id=?
                """,
                (next_goal, str(row["plan_id"] or "")),
            )
            conn.commit()
    finally:
        conn.close()

    audit_id = ""
    if old_goal != next_goal:
        audit_id = append_training_center_audit(
            root,
            action="rename",
            operator=operator_text,
            target_id=qid,
            detail={
                "queue_task_id": qid,
                "target_agent_id": str(row["target_agent_id"] or "").strip(),
                "old_capability_goal": old_goal,
                "new_capability_goal": next_goal,
            },
        )
    return {
        "queue_task_id": qid,
        "capability_goal": next_goal,
        "old_capability_goal": old_goal,
        "changed": bool(old_goal != next_goal),
        "audit_id": audit_id,
    }


def remove_training_queue_item(
    root: Path,
    *,
    queue_task_id_text: str,
    operator: str,
    reason: str = "",
) -> dict[str, Any]:
    qid = safe_token(str(queue_task_id_text or ""), "", 160)
    if not qid:
        raise TrainingCenterError(400, "queue_task_id required", "queue_task_id_required")
    operator_text = safe_token(str(operator or "web-user"), "web-user", 80)
    reason_text = str(reason or "").strip()
    now_text = iso_ts(now_local())

    conn = connect_db(root)
    try:
        row = conn.execute(
            """
            SELECT q.queue_task_id,q.plan_id,q.status,q.priority,q.trainer_match,q.enqueued_at,
                   p.source,p.target_agent_id,p.capability_goal
            FROM training_queue q
            INNER JOIN training_plan p ON p.plan_id=q.plan_id
            WHERE q.queue_task_id=?
            LIMIT 1
            """,
            (qid,),
        ).fetchone()
        if row is None:
            raise TrainingCenterError(404, "queue task not found", "queue_task_not_found", {"queue_task_id": qid})

        old_status = str(row["status"] or "")
        if old_status != "removed":
            conn.execute(
                """
                UPDATE training_queue
                SET status='removed',finished_at=?
                WHERE queue_task_id=?
                """,
                (now_text, qid),
            )
            conn.execute(
                """
                UPDATE training_run
                SET status='removed',updated_at=?
                WHERE queue_task_id=? AND status='running'
                """,
                (now_text, qid),
            )
            conn.commit()
    finally:
        conn.close()

    audit_id = append_training_center_audit(
        root,
        action="remove",
        operator=operator_text,
        target_id=qid,
        detail={
            "reason": reason_text,
        },
    )
    return {
        "queue_task_id": qid,
        "status": "removed",
        "audit_id": audit_id,
    }
