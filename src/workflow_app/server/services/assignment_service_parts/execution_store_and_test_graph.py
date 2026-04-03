

def _insert_assignment_execution_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    ticket_id: str,
    node_id: str,
    provider: str,
    workspace_path: Path,
    command_summary: str,
    prompt_ref: str,
    stdout_ref: str,
    stderr_ref: str,
    result_ref: str,
    latest_event: str,
    started_at: str,
    created_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO assignment_execution_runs (
            run_id,ticket_id,node_id,provider,workspace_path,status,command_summary,
            prompt_ref,stdout_ref,stderr_ref,result_ref,latest_event,latest_event_at,
            exit_code,started_at,finished_at,created_at,updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            run_id,
            ticket_id,
            node_id,
            provider,
            workspace_path.as_posix(),
            "starting",
            command_summary,
            prompt_ref,
            stdout_ref,
            stderr_ref,
            result_ref,
            latest_event,
            started_at,
            0,
            started_at,
            "",
            created_at,
            created_at,
        ),
    )


def _update_assignment_execution_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    status: str,
    latest_event: str,
    latest_event_at: str,
    exit_code: int | None = None,
    stdout_ref: str | None = None,
    stderr_ref: str | None = None,
    result_ref: str | None = None,
    finished_at: str | None = None,
) -> None:
    assignments = [
        "status=?",
        "latest_event=?",
        "latest_event_at=?",
        "updated_at=?",
    ]
    values: list[Any] = [status, latest_event, latest_event_at, latest_event_at]
    if exit_code is not None:
        assignments.append("exit_code=?")
        values.append(int(exit_code))
    if stdout_ref is not None:
        assignments.append("stdout_ref=?")
        values.append(stdout_ref)
    if stderr_ref is not None:
        assignments.append("stderr_ref=?")
        values.append(stderr_ref)
    if result_ref is not None:
        assignments.append("result_ref=?")
        values.append(result_ref)
    if finished_at is not None:
        assignments.append("finished_at=?")
        values.append(finished_at)
    values.append(run_id)
    conn.execute(
        f"UPDATE assignment_execution_runs SET {', '.join(assignments)} WHERE run_id=?",
        tuple(values),
    )


def _touch_assignment_execution_run_latest_event(
    root: Path,
    *,
    run_id: str,
    latest_event: str,
    latest_event_at: str,
) -> None:
    latest_event_text = _short_assignment_text(latest_event, 1000) or "执行中"
    conn = connect_db(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT status
            FROM assignment_execution_runs
            WHERE run_id=?
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()
        if row is None:
            conn.commit()
            return
        current_status = _normalize_run_status(row["status"] or "starting")
        if current_status not in {"starting", "running"}:
            conn.commit()
            return
        conn.execute(
            """
            UPDATE assignment_execution_runs
            SET latest_event=?,latest_event_at=?,updated_at=?
            WHERE run_id=?
            """,
            (latest_event_text, latest_event_at, latest_event_at, run_id),
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()


def _cancel_active_assignment_runs(
    conn: sqlite3.Connection,
    *,
    ticket_id: str,
    node_id: str,
    reason: str,
    now_text: str,
) -> list[str]:
    rows = conn.execute(
        """
        SELECT run_id
        FROM assignment_execution_runs
        WHERE ticket_id=? AND node_id=? AND status IN ('starting','running')
        ORDER BY created_at DESC, run_id DESC
        """,
        (ticket_id, node_id),
    ).fetchall()
    run_ids = [str(row["run_id"] or "").strip() for row in rows if str(row["run_id"] or "").strip()]
    if run_ids:
        conn.execute(
            """
            UPDATE assignment_execution_runs
            SET status='cancelled',latest_event=?,latest_event_at=?,finished_at=?,updated_at=?
            WHERE ticket_id=? AND node_id=? AND status IN ('starting','running')
            """,
            (reason, now_text, now_text, now_text, ticket_id, node_id),
        )
    for run_id in run_ids:
        _kill_assignment_run_process(run_id)
    return run_ids


def _normalize_history_loaded(raw: Any) -> int:
    if raw in (None, ""):
        return 0
    try:
        value = int(raw)
    except Exception:
        value = 0
    return max(0, value)


def list_assignments(root: Path, *, include_test_data: bool = True) -> dict[str, Any]:
    conn = connect_db(root)
    try:
        conn.execute("BEGIN")
        _refresh_all_pause_states(conn)
        rows = conn.execute(
            """
            SELECT
                g.ticket_id,g.graph_name,g.source_workflow,g.summary,g.review_mode,
                g.global_concurrency_limit,g.is_test_data,g.external_request_id,g.scheduler_state,g.pause_note,
                g.created_at,g.updated_at,
                COUNT(n.node_id) AS total_nodes,
                SUM(CASE WHEN n.status='running' THEN 1 ELSE 0 END) AS running_nodes,
                SUM(CASE WHEN n.status='failed' THEN 1 ELSE 0 END) AS failed_nodes,
                SUM(CASE WHEN n.status='blocked' THEN 1 ELSE 0 END) AS blocked_nodes
            FROM assignment_graphs g
            LEFT JOIN assignment_nodes n ON n.ticket_id=g.ticket_id
            WHERE (?=1 OR COALESCE(g.is_test_data,0)=0)
            GROUP BY
                g.ticket_id,g.graph_name,g.source_workflow,g.summary,g.review_mode,
                g.global_concurrency_limit,g.is_test_data,g.external_request_id,g.scheduler_state,g.pause_note,
                g.created_at,g.updated_at
            ORDER BY g.updated_at DESC, g.created_at DESC
            """
            ,
            (1 if include_test_data else 0,),
        ).fetchall()
        system_limit, system_limit_updated_at = _get_global_concurrency_limit(conn)
        conn.commit()
    finally:
        conn.close()
    items: list[dict[str, Any]] = []
    for row in rows:
        total_nodes = int(row["total_nodes"] or 0)
        items.append(
            {
                "ticket_id": str(row["ticket_id"] or "").strip(),
                "graph_name": str(row["graph_name"] or "").strip(),
                "source_workflow": str(row["source_workflow"] or "").strip(),
                "summary": str(row["summary"] or "").strip(),
                "review_mode": str(row["review_mode"] or "").strip(),
                "global_concurrency_limit": int(row["global_concurrency_limit"] or 0),
                "is_test_data": _row_is_test_data(row),
                "external_request_id": str(row["external_request_id"] or "").strip(),
                "scheduler_state": str(row["scheduler_state"] or "").strip().lower(),
                "scheduler_state_text": _scheduler_state_text(row["scheduler_state"]),
                "pause_note": str(row["pause_note"] or "").strip(),
                "created_at": str(row["created_at"] or "").strip(),
                "updated_at": str(row["updated_at"] or "").strip(),
                "metrics_summary": {
                    "total_nodes": total_nodes,
                    "running_nodes": int(row["running_nodes"] or 0),
                    "failed_nodes": int(row["failed_nodes"] or 0),
                    "blocked_nodes": int(row["blocked_nodes"] or 0),
                },
            }
        )
    return {
        "items": items,
        "settings": {
            "global_concurrency_limit": int(system_limit),
            "updated_at": system_limit_updated_at,
        },
    }


def _assignment_test_iso(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    if "T" in text:
        return text if "+" in text or text.endswith("Z") else text + "+08:00"
    return text.replace(" ", "T") + "+08:00"


def _assignment_test_graph_seed() -> tuple[list[dict[str, Any]], list[tuple[str, str]], set[str]]:
    def node(
        node_id: str,
        node_name: str,
        agent_name: str,
        *,
        goal: str,
        artifact: str,
        priority: int,
        created_at: str,
        status: str = "pending",
        completed_at: str = "",
        success_reason: str = "",
        result_ref: str = "",
        failure_reason: str = "",
        delivery_mode: str = "none",
        receiver_name: str = "",
        artifact_delivery_status: str = "pending",
        artifact_delivered_at: str = "",
    ) -> dict[str, Any]:
        completed_text = _assignment_test_iso(completed_at) if completed_at else ""
        delivered_text = _assignment_test_iso(artifact_delivered_at) if artifact_delivered_at else ""
        created_text = _assignment_test_iso(created_at)
        updated_text = delivered_text or completed_text or created_text
        return {
            "node_id": node_id,
            "node_name": node_name,
            "assigned_agent_id": agent_name,
            "assigned_agent_name": agent_name,
            "node_goal": goal,
            "expected_artifact": artifact,
            "delivery_mode": delivery_mode,
            "delivery_receiver_agent_id": receiver_name,
            "delivery_receiver_agent_name": receiver_name,
            "artifact_delivery_status": artifact_delivery_status,
            "artifact_delivered_at": delivered_text,
            "artifact_paths": [],
            "status": status,
            "priority": int(priority),
            "completed_at": completed_text,
            "success_reason": success_reason,
            "result_ref": result_ref,
            "failure_reason": failure_reason,
            "created_at": created_text,
            "updated_at": updated_text,
        }

    nodes = [
        node(
            "T1",
            "需求澄清",
            "需求分析师",
            goal="澄清输入需求、边界与依赖，形成统一开工口径。",
            artifact="澄清记录",
            priority=1,
            created_at="2026-03-14 10:00:00",
            status="succeeded",
            completed_at="2026-03-14 10:12:08",
            success_reason="运行成功",
        ),
        node(
            "T2",
            "范围收口",
            "需求分析师",
            goal="把任务中心一期边界压缩成可执行范围。",
            artifact="范围边界表",
            priority=1,
            created_at="2026-03-14 10:16:00",
            status="succeeded",
            completed_at="2026-03-14 10:24:17",
            success_reason="运行成功",
        ),
        node(
            "T3",
            "角色映射",
            "协调代理",
            goal="将任务拆分映射到执行角色与职责槽位。",
            artifact="角色映射表",
            priority=1,
            created_at="2026-03-14 10:22:00",
            status="succeeded",
            completed_at="2026-03-14 10:31:06",
            success_reason="运行成功",
        ),
        node(
            "T4",
            "基线确认",
            "需求分析师",
            goal="冻结一期基线，避免后续任务图口径漂移。",
            artifact="基线快照",
            priority=1,
            created_at="2026-03-14 10:34:00",
            status="succeeded",
            completed_at="2026-03-14 10:46:11",
            success_reason="运行成功",
        ),
        node(
            "T5",
            "数据备份",
            "协调代理",
            goal="在变更前完成运行态与产物目录备份。",
            artifact="备份结果",
            priority=1,
            created_at="2026-03-14 11:02:00",
            status="succeeded",
            completed_at="2026-03-14 11:18:09",
            success_reason="运行成功",
        ),
        node(
            "T6",
            "任务拆分",
            "需求分析师",
            goal="输出任务树并明确上下游依赖。",
            artifact="任务树",
            priority=1,
            created_at="2026-03-14 11:22:00",
            status="succeeded",
            completed_at="2026-03-14 11:31:25",
            success_reason="运行成功",
        ),
        node(
            "T7",
            "原型骨架",
            "设计代理",
            goal="搭建任务中心界面结构和交互骨架。",
            artifact="低保真原型",
            priority=1,
            created_at="2026-03-14 11:28:00",
            status="succeeded",
            completed_at="2026-03-14 11:44:40",
            success_reason="运行成功",
        ),
        node(
            "T8",
            "节点映射",
            "协调代理",
            goal="把任务树映射为可视化依赖图节点与连线。",
            artifact="依赖关系图",
            priority=1,
            created_at="2026-03-14 11:48:00",
            status="succeeded",
            completed_at="2026-03-14 12:01:18",
            success_reason="运行成功",
            artifact_delivery_status="delivered",
            artifact_delivered_at="2026-03-14 12:02:07",
        ),
        node(
            "T16",
            "知识快照",
            "知识代理",
            goal="固化当前知识面和原型决策快照。",
            artifact="快照归档",
            priority=2,
            created_at="2026-03-14 12:04:00",
            status="succeeded",
            completed_at="2026-03-14 12:08:56",
            success_reason="运行成功",
        ),
        node(
            "T9",
            "接口预留",
            "后端代理",
            goal="补齐任务中心所需接口字段与返回结构。",
            artifact="接口草案",
            priority=0,
            created_at="2026-03-14 12:09:20",
            status="running",
            delivery_mode="specified",
            receiver_name="测试代理",
        ),
        node(
            "T20",
            "沙箱试跑",
            "执行代理",
            goal="在沙箱环境验证调度与交付链路。",
            artifact="失败日志",
            priority=0,
            created_at="2026-03-14 12:14:00",
            status="failed",
            completed_at="2026-03-14 12:19:33",
            failure_reason="运行失败：沙箱冒烟未通过。",
        ),
        node(
            "T10",
            "联调验收",
            "测试代理",
            goal="等待接口和试跑结果后完成联调验收。",
            artifact="待补充联调记录",
            priority=0,
            created_at="2026-03-14 12:20:00",
            status="blocked",
            delivery_mode="specified",
            receiver_name="测试代理",
        ),
        node(
            "T11",
            "回写关闭",
            "协调代理",
            goal="回写执行结果并推动关闭流程。",
            artifact="关闭回写单",
            priority=1,
            created_at="2026-03-14 12:22:00",
        ),
        node(
            "T12",
            "回执汇总",
            "分析代理",
            goal="汇总各节点回执结果与差异。",
            artifact="回执汇总",
            priority=1,
            created_at="2026-03-14 12:26:00",
        ),
        node(
            "T13",
            "结果广播",
            "协调代理",
            goal="向上下游广播本轮执行结果。",
            artifact="广播记录",
            priority=1,
            created_at="2026-03-14 12:28:00",
        ),
        node(
            "T17",
            "风险巡检",
            "风险代理",
            goal="抽检独立风险项，验证任务图边界稳定性。",
            artifact="风险巡检单",
            priority=2,
            created_at="2026-03-14 12:30:00",
        ),
        node(
            "T14",
            "人工确认",
            "人工审核",
            goal="在结果广播后执行人工确认。",
            artifact="人工确认结论",
            priority=1,
            created_at="2026-03-14 12:32:00",
        ),
        node(
            "T15",
            "自动关闭",
            "协调代理",
            goal="满足关闭条件后自动完成收口。",
            artifact="关闭结果",
            priority=1,
            created_at="2026-03-14 12:36:00",
        ),
        node(
            "T18",
            "模板同步",
            "知识代理",
            goal="同步原型模板与任务中心最新约束。",
            artifact="模板同步记录",
            priority=2,
            created_at="2026-03-14 12:40:00",
        ),
        node(
            "T19",
            "资源回收",
            "运维代理",
            goal="在主链完成后执行资源回收。",
            artifact="资源回收单",
            priority=2,
            created_at="2026-03-14 12:42:00",
        ),
    ]
    edges = [
        ("T1", "T2"),
        ("T1", "T3"),
        ("T2", "T4"),
        ("T3", "T4"),
        ("T4", "T5"),
        ("T5", "T6"),
        ("T5", "T7"),
        ("T6", "T8"),
        ("T7", "T8"),
        ("T8", "T9"),
        ("T9", "T10"),
        ("T20", "T10"),
        ("T10", "T11"),
        ("T11", "T12"),
        ("T11", "T13"),
        ("T12", "T15"),
        ("T13", "T14"),
        ("T14", "T15"),
    ]
    return nodes, edges, {"T17", "T18", "T19"}


def bootstrap_assignment_test_graph(cfg: Any, *, operator: str) -> dict[str, Any]:
    operator_text = _default_assignment_operator(operator)
    seed_nodes, seed_edges, sticky_node_ids = _assignment_test_graph_seed()
    conn = connect_db(cfg.root)
    created = False
    seeded = False
    ticket_id = ""
    bootstrap_updated_at = iso_ts(now_local())
    try:
        conn.execute("BEGIN IMMEDIATE")
        graph_row = conn.execute(
            """
            SELECT
                ticket_id,graph_name,source_workflow,summary,review_mode,
                global_concurrency_limit,is_test_data,external_request_id,scheduler_state,pause_note,
                created_at,updated_at
            FROM assignment_graphs
            WHERE source_workflow=? AND external_request_id=?
            LIMIT 1
            """,
            (ASSIGNMENT_TEST_GRAPH_SOURCE, ASSIGNMENT_TEST_GRAPH_EXTERNAL_REQUEST_ID),
        ).fetchone()
        if graph_row is None:
            ticket_id = assignment_ticket_id()
            conn.execute(
                """
                INSERT INTO assignment_graphs (
                    ticket_id,graph_name,source_workflow,summary,review_mode,
                    global_concurrency_limit,is_test_data,external_request_id,scheduler_state,pause_note,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    ticket_id,
                    ASSIGNMENT_TEST_GRAPH_NAME,
                    ASSIGNMENT_TEST_GRAPH_SOURCE,
                    ASSIGNMENT_TEST_GRAPH_SUMMARY,
                    "none",
                    DEFAULT_ASSIGNMENT_CONCURRENCY_LIMIT,
                    1,
                    ASSIGNMENT_TEST_GRAPH_EXTERNAL_REQUEST_ID,
                    "running",
                    "",
                    ASSIGNMENT_TEST_GRAPH_CREATED_AT,
                    bootstrap_updated_at,
                ),
            )
            created = True
        else:
            ticket_id = str(graph_row["ticket_id"] or "").strip()
            conn.execute(
                """
                UPDATE assignment_graphs
                SET graph_name=?,summary=?,review_mode='none',
                    global_concurrency_limit=?,is_test_data=1,
                    external_request_id=?,updated_at=?
                WHERE ticket_id=?
                """,
                (
                    ASSIGNMENT_TEST_GRAPH_NAME,
                    ASSIGNMENT_TEST_GRAPH_SUMMARY,
                    DEFAULT_ASSIGNMENT_CONCURRENCY_LIMIT,
                    ASSIGNMENT_TEST_GRAPH_EXTERNAL_REQUEST_ID,
                    bootstrap_updated_at,
                    ticket_id,
                ),
            )
        existing_node_count = int(
            (
                conn.execute(
                    "SELECT COUNT(1) AS cnt FROM assignment_nodes WHERE ticket_id=?",
                    (ticket_id,),
                ).fetchone()
                or {"cnt": 0}
            )["cnt"]
        )
        if existing_node_count <= 0:
            seeded = True
            conn.execute("DELETE FROM assignment_edges WHERE ticket_id=?", (ticket_id,))
            conn.execute("DELETE FROM assignment_nodes WHERE ticket_id=?", (ticket_id,))
            _insert_graph_nodes(
                conn,
                ticket_id=ticket_id,
                node_payloads=seed_nodes,
                created_at=ASSIGNMENT_TEST_GRAPH_CREATED_AT,
            )
            _insert_edges(
                conn,
                ticket_id=ticket_id,
                edges=seed_edges,
                created_at=ASSIGNMENT_TEST_GRAPH_CREATED_AT,
            )
            _recompute_graph_statuses(conn, ticket_id, sticky_node_ids=sticky_node_ids)
            snapshot_seed = _current_assignment_snapshot(conn, ticket_id)
            node_map_seed = snapshot_seed["node_map_by_id"]
            delivered_node = node_map_seed.get("T8") or {}
            if delivered_node:
                delivered_paths = [path.as_posix() for path in _node_artifact_file_paths(cfg.root, delivered_node)]
                delivered_payload = _artifact_delivery_markdown(
                    delivered_node,
                    delivered_at=_assignment_test_iso("2026-03-14 12:02:07"),
                    operator=operator_text,
                    artifact_label=str(
                        delivered_node.get("expected_artifact") or delivered_node.get("node_name") or "依赖关系图"
                    ),
                    delivery_note="任务中心原型测试数据预置交付产物。",
                )
                for raw_path in delivered_paths:
                    path = Path(raw_path).resolve(strict=False)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(delivered_payload, encoding="utf-8")
                result_ref = delivered_paths[0] if delivered_paths else ""
                conn.execute(
                    """
                    UPDATE assignment_nodes
                    SET artifact_delivery_status='delivered',
                        artifact_delivered_at=?,
                        artifact_paths_json=?,
                        result_ref=?,
                        updated_at=?
                    WHERE ticket_id=? AND node_id='T8'
                    """,
                    (
                        _assignment_test_iso("2026-03-14 12:02:07"),
                        json.dumps(delivered_paths, ensure_ascii=False),
                        result_ref,
                        _assignment_test_iso("2026-03-14 12:02:07"),
                        ticket_id,
                    ),
                )
            failed_node = node_map_seed.get("T20") or {}
            if failed_node:
                failed_paths = [path.as_posix() for path in _node_artifact_file_paths(cfg.root, failed_node)]
                failed_payload = "\n".join(
                    [
                        "# 沙箱试跑失败日志",
                        "",
                        "- node_id: T20",
                        "- node_name: 沙箱试跑",
                        "- completed_at: 2026-03-14T12:19:33+08:00",
                        "- failure_reason: 运行失败：沙箱冒烟未通过。",
                        "",
                        "## 摘要",
                        "",
                        "接口联调前置检查未通过，调度链路保持阻塞。",
                        "",
                    ]
                )
                for raw_path in failed_paths:
                    path = Path(raw_path).resolve(strict=False)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(failed_payload, encoding="utf-8")
                conn.execute(
                    """
                    UPDATE assignment_nodes
                    SET artifact_paths_json=?,updated_at=?
                    WHERE ticket_id=? AND node_id='T20'
                    """,
                    (
                        json.dumps(failed_paths, ensure_ascii=False),
                        _assignment_test_iso("2026-03-14 12:19:33"),
                        ticket_id,
                    ),
                )
            conn.execute(
                """
                UPDATE assignment_graphs
                SET scheduler_state='running',pause_note='',updated_at=?
                WHERE ticket_id=?
                """,
                (bootstrap_updated_at, ticket_id),
            )
        snapshot = _current_assignment_snapshot(conn, ticket_id)
        conn.commit()
    finally:
        conn.close()
    _sync_assignment_workspace_snapshot(cfg.root, snapshot)
    return {
        "ticket_id": ticket_id,
        "created": bool(created or seeded),
        "graph_overview": _graph_overview_payload(
            snapshot["graph_row"],
            metrics_summary=snapshot["metrics_summary"],
            scheduler_state_payload=snapshot["scheduler"],
        ),
    }
