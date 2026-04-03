from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def bind_runtime_symbols(symbols: dict[str, object]) -> None:
    if not isinstance(symbols, dict):
        return
    target = globals()
    module_name = str(target.get("__name__") or "")
    for key, value in symbols.items():
        if str(key).startswith("__"):
            continue
        current = target.get(key)
        if callable(current) and getattr(current, "__module__", "") == module_name:
            continue
        target[key] = value


def _parse_loop_graph(raw: object) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if not raw:
        return {}
    try:
        payload = json.loads(str(raw))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _json_object(raw: object) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if not raw:
        return {}
    try:
        payload = json.loads(str(raw))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_training_tasks(raw: object) -> list[str]:
    try:
        payload = json.loads(str(raw or "[]"))
    except Exception:
        payload = []
    if not isinstance(payload, list):
        return []
    return [str(item or "").strip() for item in payload if str(item or "").strip()]


def _safe_float(raw: object) -> float | None:
    if raw in (None, ""):
        return None
    try:
        return round(float(raw), 2)
    except Exception:
        return None


def _loop_node_base(now_text: str) -> dict[str, Any]:
    return {
        "node_id": "baseline",
        "title": "基线",
        "round_index": 0,
        "round_label": "Baseline",
        "node_type": "baseline",
        "decision": "暂无历史",
        "decision_code": "baseline",
        "next_action": "执行首轮评测",
        "next_action_code": "",
        "impact": "闭环起点",
        "metrics": {
            "avg_score": None,
            "threshold": None,
            "previous_avg_score": None,
            "run_results": [],
        },
        "metrics_available": False,
        "metrics_unavailable_reason": "baseline_without_metrics",
        "queue_task_id": "",
        "plan_id": "",
        "status": "active",
        "available_actions": [],
        "run_ids": [],
        "execution_engine": EXECUTION_ENGINE,
        "created_at": now_text,
        "updated_at": now_text,
    }


def _resolve_training_queue_row(conn: sqlite3.Connection, queue_task_id: str) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT
            q.queue_task_id,q.plan_id,q.priority,q.status,q.trainer_match,q.enqueued_at,q.started_at,q.finished_at,
            COALESCE(q.execution_engine,'workflow_native') AS execution_engine,
            COALESCE(q.is_test_data,0) AS queue_is_test_data,
            p.source,p.target_agent_id,p.capability_goal,p.training_tasks_json,p.acceptance_criteria,p.priority AS plan_priority,
            COALESCE(p.is_test_data,0) AS plan_is_test_data,
            COALESCE(p.loop_id,'') AS loop_id,
            a.agent_name
        FROM training_queue q
        INNER JOIN training_plan p ON p.plan_id=q.plan_id
        LEFT JOIN agent_registry a ON a.agent_id=p.target_agent_id
        WHERE q.queue_task_id=?
        LIMIT 1
        """,
        (queue_task_id,),
    ).fetchone()
    if row is None:
        raise TrainingCenterError(
            404,
            "queue task not found",
            "queue_task_not_found",
            {"queue_task_id": queue_task_id},
        )
    return row


def _ensure_plan_loop_id(conn: sqlite3.Connection, row: sqlite3.Row) -> str:
    loop_id = str(row["loop_id"] or "").strip()
    plan_id = str(row["plan_id"] or "").strip()
    if loop_id:
        return loop_id
    if not plan_id:
        return ""
    conn.execute(
        """
        UPDATE training_plan
        SET loop_id=?
        WHERE plan_id=? AND COALESCE(loop_id,'')=''
        """,
        (plan_id, plan_id),
    )
    return plan_id


def _ensure_loop_state_row(
    conn: sqlite3.Connection,
    *,
    loop_id: str,
    seed_row: sqlite3.Row,
    now_text: str,
) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT
            loop_id,graph_json,current_node_id,metrics_available,metrics_unavailable_reason,is_test_data,created_at,updated_at
        FROM training_loop_state
        WHERE loop_id=?
        LIMIT 1
        """,
        (loop_id,),
    ).fetchone()
    if row is not None:
        return row

    is_test_data = bool(int(seed_row["plan_is_test_data"] or seed_row["queue_is_test_data"] or 0))
    base = _loop_node_base(now_text)
    current = {
        "node_id": str(seed_row["queue_task_id"] or "").strip(),
        "title": "R1 当前",
        "round_index": 1,
        "round_label": "R1",
        "node_type": "round",
        "decision": "等待执行三轮评测",
        "decision_code": "awaiting_evaluation",
        "next_action": "执行三轮评测",
        "next_action_code": "execute",
        "impact": "首轮任务已创建，等待后端回写三轮评测结果",
        "metrics": {
            "avg_score": None,
            "threshold": training_threshold_for_priority(seed_row["priority"]),
            "previous_avg_score": None,
            "run_results": [],
        },
        "metrics_available": False,
        "metrics_unavailable_reason": "evaluation_not_started",
        "queue_task_id": str(seed_row["queue_task_id"] or "").strip(),
        "plan_id": str(seed_row["plan_id"] or "").strip(),
        "status": str(seed_row["status"] or "").strip().lower() or "queued",
        "available_actions": [],
        "run_ids": [],
        "execution_engine": str(seed_row["execution_engine"] or EXECUTION_ENGINE).strip() or EXECUTION_ENGINE,
        "created_at": str(seed_row["enqueued_at"] or "").strip() or now_text,
        "updated_at": now_text,
    }
    graph = {
        "version": 2,
        "loop_id": loop_id,
        "nodes": [base, current],
        "edges": [{"from": base["node_id"], "to": current["node_id"], "kind": "main"}],
        "current_node_id": current["node_id"],
    }
    conn.execute(
        """
        INSERT INTO training_loop_state (
            loop_id,graph_json,current_node_id,metrics_available,metrics_unavailable_reason,is_test_data,created_at,updated_at
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            loop_id,
            json.dumps(graph, ensure_ascii=False),
            str(current["node_id"] or "").strip(),
            0,
            "evaluation_not_started",
            1 if is_test_data else 0,
            now_text,
            now_text,
        ),
    )
    return conn.execute(
        """
        SELECT
            loop_id,graph_json,current_node_id,metrics_available,metrics_unavailable_reason,is_test_data,created_at,updated_at
        FROM training_loop_state
        WHERE loop_id=?
        LIMIT 1
        """,
        (loop_id,),
    ).fetchone()


def _load_loop_queue_rows(conn: sqlite3.Connection, loop_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            q.queue_task_id,q.plan_id,q.priority,q.status,q.trainer_match,q.enqueued_at,q.started_at,q.finished_at,
            COALESCE(q.execution_engine,'workflow_native') AS execution_engine,
            COALESCE(q.is_test_data,0) AS queue_is_test_data,
            p.source,p.target_agent_id,p.capability_goal,p.training_tasks_json,p.acceptance_criteria,p.created_by,p.created_at AS plan_created_at,
            p.priority AS plan_priority,
            COALESCE(p.is_test_data,0) AS plan_is_test_data,
            COALESCE(p.loop_id,'') AS loop_id,
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
        WHERE COALESCE(p.loop_id,'')=? OR p.plan_id=?
        ORDER BY q.enqueued_at ASC, q.queue_task_id ASC
        """,
        (loop_id, loop_id),
    ).fetchall()


def _load_loop_eval_runs(
    conn: sqlite3.Connection,
    queue_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    if not queue_ids:
        return {}
    placeholders = ",".join(["?"] * len(queue_ids))
    rows = conn.execute(
        f"""
        SELECT
            eval_run_id,queue_task_id,round_index,run_index,status,score,evaluation_summary,started_at,finished_at,context_reset,evidence_ref,execution_engine,created_at,updated_at
        FROM training_eval_run
        WHERE queue_task_id IN ({placeholders})
        ORDER BY round_index ASC, queue_task_id ASC, run_index ASC, created_at ASC
        """,
        tuple(queue_ids),
    ).fetchall()
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        qid = str(row["queue_task_id"] or "").strip()
        if not qid:
            continue
        out.setdefault(qid, []).append({name: row[name] for name in row.keys()})
    return out


def _load_queue_audits(
    conn: sqlite3.Connection,
    queue_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    if not queue_ids:
        return {}
    placeholders = ",".join(["?"] * len(queue_ids))
    rows = conn.execute(
        f"""
        SELECT audit_id,action,operator,target_id,detail_json,created_at
        FROM training_audit_log
        WHERE target_id IN ({placeholders})
        ORDER BY created_at ASC, audit_id ASC
        """,
        tuple(queue_ids),
    ).fetchall()
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = str(row["target_id"] or "").strip()
        if not key:
            continue
        item = {name: row[name] for name in row.keys()}
        item["detail"] = _json_object(row["detail_json"])
        out.setdefault(key, []).append(item)
    return out


def _load_loop_action_audits(conn: sqlite3.Connection, loop_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT audit_id,action,operator,target_id,detail_json,created_at
        FROM training_audit_log
        WHERE target_id=?
          AND action IN ('enter-next-round','rollback-round-increment')
        ORDER BY created_at ASC, audit_id ASC
        """,
        (loop_id,),
    ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        item = {name: row[name] for name in row.keys()}
        item["detail"] = _json_object(row["detail_json"])
        items.append(item)
    return items


def _round_index_for_queue(
    *,
    order_index: int,
    graph_node: dict[str, Any],
    eval_rows: list[dict[str, Any]],
) -> int:
    for item in eval_rows:
        try:
            ridx = int(item.get("round_index") or 0)
        except Exception:
            ridx = 0
        if ridx > 0:
            return ridx
    try:
        ridx = int(graph_node.get("round_index") or 0)
    except Exception:
        ridx = 0
    if ridx > 0:
        return ridx
    return max(1, int(order_index) + 1)


def _related_action_audits(
    queue_task_id: str,
    *,
    queue_audit_map: dict[str, list[dict[str, Any]]],
    loop_audits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    items = list(queue_audit_map.get(queue_task_id, []))
    for audit in loop_audits:
        detail = audit.get("detail") if isinstance(audit, dict) else {}
        if not isinstance(detail, dict):
            detail = {}
        if (
            str(detail.get("queue_task_id") or "").strip() == queue_task_id
            or str(detail.get("created_queue_task_id") or "").strip() == queue_task_id
        ):
            items.append(audit)
    items.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("audit_id") or "")))
    return items


def _build_workset_changes(
    row: sqlite3.Row,
    *,
    round_index: int,
    previous_tasks: list[str],
    action_audits: list[dict[str, Any]],
    rolled_back: bool,
) -> dict[str, Any]:
    current_tasks = _parse_training_tasks(row["training_tasks_json"])
    added = [task for task in current_tasks if task not in previous_tasks]
    carried = [task for task in current_tasks if task in previous_tasks]
    removed = [task for task in previous_tasks if task not in current_tasks]

    action_reason = ""
    for audit in reversed(action_audits):
        detail = audit.get("detail") if isinstance(audit, dict) else {}
        if not isinstance(detail, dict):
            continue
        action_reason = str(detail.get("reason") or "").strip()
        if action_reason:
            break

    if round_index <= 1:
        delta_summary = f"首轮建立 {len(current_tasks)} 项训练任务工作集"
    elif added or removed:
        parts: list[str] = []
        if added:
            parts.append(f"新增 {len(added)} 项")
        if removed:
            parts.append(f"移除 {len(removed)} 项")
        if carried:
            parts.append(f"保留 {len(carried)} 项")
        delta_summary = "，".join(parts) if parts else "当前轮工作集无结构化变化"
    elif current_tasks:
        delta_summary = f"本轮沿用上轮 {len(carried)} 项训练任务，暂无结构化增删记录"
    else:
        delta_summary = "当前未配置训练任务工作集"

    if rolled_back:
        delta_summary += "；当前轮已执行回退。"
    if action_reason:
        delta_summary += f"；动作说明：{action_reason}"

    items: list[dict[str, Any]] = []
    for task in current_tasks:
        state_key = "added" if task in added or round_index <= 1 else "carried"
        items.append({"kind": "training_task", "label": task, "state": state_key})
    for task in removed:
        items.append({"kind": "training_task", "label": task, "state": "removed"})

    return {
        "queue_task_id": str(row["queue_task_id"] or "").strip(),
        "round_index": round_index,
        "delta_summary": delta_summary,
        "current_items": current_tasks,
        "items": items,
        "added_items": added if round_index > 1 else current_tasks,
        "carried_items": carried,
        "removed_items": removed,
        "rollback_applied": rolled_back,
        "execution_engine": str(row["execution_engine"] or EXECUTION_ENGINE).strip() or EXECUTION_ENGINE,
        "updated_at": str(
            row["latest_run_updated_at"] or row["finished_at"] or row["started_at"] or row["enqueued_at"] or ""
        ).strip(),
    }


def _append_edge(
    edges: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
    *,
    from_id: str,
    to_id: str,
    kind: str,
    valid_ids: set[str],
) -> None:
    fid = str(from_id or "").strip()
    tid = str(to_id or "").strip()
    edge_kind = str(kind or "main").strip().lower() or "main"
    if not fid or not tid or fid not in valid_ids or tid not in valid_ids:
        return
    key = (fid, tid, edge_kind)
    if key in seen:
        return
    seen.add(key)
    edges.append({"from": fid, "to": tid, "kind": edge_kind})
