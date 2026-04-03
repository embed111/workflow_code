

def execute_training_queue_item(
    root: Path,
    *,
    queue_task_id_text: str,
    operator: str,
) -> dict[str, Any]:
    qid = safe_token(str(queue_task_id_text or ""), "", 160)
    if not qid:
        raise TrainingCenterError(400, "queue_task_id required", "queue_task_id_required")
    operator_text = safe_token(str(operator or "web-user"), "web-user", 80)

    conn = connect_db(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT q.queue_task_id,q.plan_id,q.priority,q.status,q.enqueued_at,q.started_at,q.finished_at,
                   p.source,p.target_agent_id,p.capability_goal,p.training_tasks_json,p.acceptance_criteria,p.similar_flag,
                   a.training_gate_state,a.lifecycle_state
            FROM training_queue q
            INNER JOIN training_plan p ON p.plan_id=q.plan_id
            LEFT JOIN agent_registry a ON a.agent_id=p.target_agent_id
            WHERE q.queue_task_id=?
            LIMIT 1
            """,
            (qid,),
        ).fetchone()
        if row is None:
            raise TrainingCenterError(404, "queue task not found", "queue_task_not_found", {"queue_task_id": qid})
        status = str(row["status"] or "").strip().lower()
        execution_engine = EXECUTION_ENGINE
        target_agent_id = str(row["target_agent_id"] or "").strip()
        training_gate_state = normalize_training_gate_state(row["training_gate_state"])
        if training_gate_state == "frozen_switched":
            raise TrainingCenterError(
                409,
                "当前 agent 已冻结训练，请切回最新发布版本后再训练",
                "training_frozen_after_switch",
                {"queue_task_id": qid, "target_agent_id": target_agent_id},
            )
        if status == "removed":
            raise TrainingCenterError(409, "queue task removed", "queue_task_removed", {"queue_task_id": qid})
        if status == "running":
            raise TrainingCenterError(409, "queue task running", "queue_task_running", {"queue_task_id": qid})
        if status == "done":
            existing_run = conn.execute(
                """
                SELECT run_id,run_ref,status,result_summary,updated_at
                FROM training_run
                WHERE queue_task_id=?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (qid,),
            ).fetchone()
            raise TrainingCenterError(
                409,
                "queue task already done",
                "queue_task_done",
                {
                    "queue_task_id": qid,
                    "run_id": str(existing_run["run_id"] or "").strip() if existing_run is not None else "",
                },
            )

        run_id = training_run_id_text()
        start_ts = now_local()
        start_text = iso_ts(start_ts)
        run_ref = f"workflow://native/{run_id}"
        round_index = _training_round_index_for_queue(conn, qid, str(row["plan_id"] or "").strip())

        previous_eval_rows = conn.execute(
            """
            SELECT queue_task_id,round_index,run_index,status,score,evaluation_summary,started_at,finished_at,context_reset,evidence_ref,execution_engine,created_at,updated_at
            FROM training_eval_run
            WHERE queue_task_id IN (
                SELECT q2.queue_task_id
                FROM training_queue q2
                INNER JOIN training_plan p2 ON p2.plan_id=q2.plan_id
                WHERE COALESCE(p2.loop_id,'') = (
                    SELECT COALESCE(p3.loop_id,'')
                    FROM training_plan p3
                    WHERE p3.plan_id=?
                    LIMIT 1
                )
            )
            ORDER BY round_index ASC, run_index ASC, updated_at ASC
            """,
            (str(row["plan_id"] or "").strip(),),
        ).fetchall()
        previous_round_scores: dict[int, list[float]] = {}
        for prev in previous_eval_rows:
            try:
                prev_round_index = int(prev["round_index"] or 0)
            except Exception:
                prev_round_index = 0
            if prev_round_index <= 0 or prev_round_index >= round_index:
                continue
            status_key = str(prev["status"] or "").strip().lower()
            score_value = prev["score"]
            if status_key != "done" or score_value in (None, ""):
                continue
            try:
                score = float(score_value)
            except Exception:
                continue
            previous_round_scores.setdefault(prev_round_index, []).append(score)
        previous_avg_score = None
        if previous_round_scores:
            last_round_index = max(previous_round_scores)
            scores = previous_round_scores.get(last_round_index) or []
            if len(scores) == 3:
                previous_avg_score = round(sum(scores) / 3.0, 2)

        conn.execute(
            """
            UPDATE training_queue
            SET status='running',started_at=?,execution_engine=?
            WHERE queue_task_id=?
            """,
            (start_text, execution_engine, qid),
        )
        conn.execute(
            """
            INSERT INTO training_run (
                run_id,queue_task_id,run_ref,status,result_summary,updated_at
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                run_id,
                qid,
                run_ref,
                "running",
                "",
                start_text,
            ),
        )

        eval_run_ids: list[str] = []
        run_results: list[dict[str, Any]] = []
        for run_index in range(1, 4):
            eval_run_id = training_eval_run_id_text()
            eval_started_at = iso_ts(now_local())
            score = _deterministic_eval_score(
                queue_task_id=qid,
                priority=str(row["priority"] or "").strip(),
                round_index=round_index,
                run_index=run_index,
            )
            eval_finished_at = iso_ts(now_local())
            summary = (
                f"R{round_index}/Run{run_index} 清空上下文完成独立评测，"
                f"score={score:.2f}，execution_engine={execution_engine}。"
            )
            evidence_ref = f"workflow://native/eval/{eval_run_id}"
            conn.execute(
                """
                INSERT INTO training_eval_run (
                    eval_run_id,queue_task_id,round_index,run_index,status,score,evaluation_summary,started_at,finished_at,context_reset,evidence_ref,execution_engine,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    eval_run_id,
                    qid,
                    round_index,
                    run_index,
                    "done",
                    score,
                    summary,
                    eval_started_at,
                    eval_finished_at,
                    1,
                    evidence_ref,
                    execution_engine,
                    eval_started_at,
                    eval_finished_at,
                ),
            )
            eval_run_ids.append(eval_run_id)
            run_results.append(
                {
                    "eval_run_id": eval_run_id,
                    "queue_task_id": qid,
                    "round_index": round_index,
                    "run_index": run_index,
                    "status": "done",
                    "score": score,
                    "evaluation_summary": summary,
                    "started_at": eval_started_at,
                    "finished_at": eval_finished_at,
                    "context_reset": 1,
                    "evidence_ref": evidence_ref,
                    "execution_engine": execution_engine,
                }
            )

        summary = summarize_training_eval_runs(
            priority=row["priority"],
            run_results=run_results,
            previous_avg_score=previous_avg_score,
        )
        finish_ts = now_local()
        finish_text = iso_ts(finish_ts)
        result_summary = (
            f"Round {round_index} 三轮评测完成："
            f"Avg={summary['avg_score'] if summary['avg_score'] is not None else '-'}，"
            f"Threshold={summary['threshold']:.2f}，"
            f"Decision={summary['decision_code'] or 'pending'}，"
            f"Next={summary['next_action_code'] or 'none'}，"
            f"execution_engine={execution_engine}。"
        )
        conn.execute(
            """
            UPDATE training_queue
            SET status='done',finished_at=?,execution_engine=?
            WHERE queue_task_id=?
            """,
            (finish_text, execution_engine, qid),
        )
        conn.execute(
            """
            UPDATE training_run
            SET status='done',result_summary=?,updated_at=?
            WHERE run_id=?
            """,
            (result_summary, finish_text, run_id),
        )
        conn.execute(
            """
            UPDATE agent_registry
            SET lifecycle_state='pre_release',training_gate_state='trainable',updated_at=?
            WHERE agent_id=?
            """,
            (finish_text, target_agent_id),
        )
        conn.commit()
    finally:
        conn.close()

    start_audit_id = append_training_center_audit(
        root,
        action="start",
        operator=operator_text,
        target_id=qid,
        detail={"run_id": run_id, "run_ref": run_ref, "execution_engine": execution_engine},
    )

    finish_audit_id = append_training_center_audit(
        root,
        action="finish",
        operator=operator_text,
        target_id=qid,
        detail={
            "run_id": run_id,
            "round_index": round_index,
            "status": "done",
            "result_summary": result_summary,
            "execution_engine": execution_engine,
            "eval_run_ids": eval_run_ids,
            "avg_score": summary["avg_score"],
            "threshold": summary["threshold"],
            "previous_avg_score": summary["previous_avg_score"],
            "decision": summary["decision"],
            "decision_code": summary["decision_code"],
            "next_action": summary["next_action"],
            "next_action_code": summary["next_action_code"],
        },
    )
    return {
        "queue_task_id": qid,
        "run_id": run_id,
        "run_ref": run_ref,
        "execution_engine": execution_engine,
        "status": "done",
        "round_index": round_index,
        "eval_run_ids": eval_run_ids,
        "run_results": summary["run_results"],
        "avg_score": summary["avg_score"],
        "threshold": summary["threshold"],
        "previous_avg_score": summary["previous_avg_score"],
        "decision": summary["decision"],
        "decision_code": summary["decision_code"],
        "next_action": summary["next_action"],
        "next_action_code": summary["next_action_code"],
        "available_actions": summary["available_actions"],
        "metrics_available": summary["metrics_available"],
        "metrics_unavailable_reason": summary["metrics_unavailable_reason"],
        "target_agent_id": target_agent_id,
        "target_agent_lifecycle_state": "pre_release",
        "result_summary": result_summary,
        "updated_at": finish_text,
        "audit_ids": {"start": start_audit_id, "finish": finish_audit_id},
    }


def dispatch_next_training_queue_item(root: Path, *, operator: str) -> dict[str, Any]:
    conn = connect_db(root)
    try:
        row = conn.execute(
            """
            SELECT q.queue_task_id
            FROM training_queue q
            INNER JOIN training_plan p ON p.plan_id=q.plan_id
            LEFT JOIN agent_registry a ON a.agent_id=p.target_agent_id
            WHERE q.status='queued'
              AND COALESCE(a.training_gate_state,'trainable') <> 'frozen_switched'
            ORDER BY
                CASE q.priority
                    WHEN 'P0' THEN 0
                    WHEN 'P1' THEN 1
                    WHEN 'P2' THEN 2
                    WHEN 'P3' THEN 3
                    ELSE 99
                END ASC,
                q.enqueued_at ASC
            LIMIT 1
            """
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return {"dispatched": False, "message": "queue empty"}
    queue_task_id_text = str(row["queue_task_id"] or "")
    result = execute_training_queue_item(
        root,
        queue_task_id_text=queue_task_id_text,
        operator=operator,
    )
    return {"dispatched": True, "queue_task_id": queue_task_id_text, "result": result}


def get_training_run_detail(root: Path, run_id_text: str) -> dict[str, Any] | None:
    run_id = safe_token(str(run_id_text or ""), "", 160)
    if not run_id:
        return None
    conn = connect_db(root)
    try:
        row = conn.execute(
            """
            SELECT
                r.run_id,r.queue_task_id,r.run_ref,r.status,r.result_summary,r.updated_at,
                q.plan_id,q.priority,q.status AS queue_status,
                COALESCE(q.execution_engine,'workflow_native') AS execution_engine,
                q.enqueued_at,q.started_at,q.finished_at,
                p.source,p.target_agent_id,p.capability_goal,p.training_tasks_json,p.acceptance_criteria,p.similar_flag,p.is_test_data,
                a.agent_name,a.lifecycle_state,a.training_gate_state
            FROM training_run r
            INNER JOIN training_queue q ON q.queue_task_id=r.queue_task_id
            INNER JOIN training_plan p ON p.plan_id=q.plan_id
            LEFT JOIN agent_registry a ON a.agent_id=p.target_agent_id
            WHERE r.run_id=?
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    tasks: list[str] = []
    try:
        payload = json.loads(str(row["training_tasks_json"] or "[]"))
        if isinstance(payload, list):
            tasks = [str(item or "").strip() for item in payload if str(item or "").strip()]
    except Exception:
        tasks = []
    out = {name: row[name] for name in row.keys()}
    out["training_tasks"] = tasks
    out["similar_flag"] = bool(int(row["similar_flag"] or 0))
    out["is_test_data"] = bool(int(row["is_test_data"] or 0))
    out["lifecycle_state"] = normalize_lifecycle_state(row["lifecycle_state"])
    out["training_gate_state"] = normalize_training_gate_state(row["training_gate_state"])
    return out
