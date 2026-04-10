from __future__ import annotations


def _node_map(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(node.get("node_id") or "").strip(): dict(node)
        for node in nodes
        if str(node.get("node_id") or "").strip()
    }


def _derive_node_status(
    node_id: str,
    *,
    current_status: str,
    node_status_map: dict[str, str],
    upstream_map: dict[str, list[str]],
) -> str:
    if current_status in {"running", "succeeded", "failed"}:
        return current_status
    upstream_ids = list(upstream_map.get(node_id) or [])
    if not upstream_ids:
        return "ready"
    statuses = [str(node_status_map.get(upstream_id) or "").strip().lower() for upstream_id in upstream_ids]
    if any(status == "failed" for status in statuses):
        return "blocked"
    if all(status == "succeeded" for status in statuses):
        return "ready"
    return "pending"


def _refresh_pause_state(
    conn: sqlite3.Connection,
    ticket_id: str,
    now_text: str,
    *,
    reconcile_running: bool = True,
) -> None:
    if reconcile_running:
        _reconcile_stale_running_nodes(conn, ticket_id=ticket_id)
    row = _ensure_graph_row(conn, ticket_id)
    if str(row["scheduler_state"] or "").strip().lower() != "pause_pending":
        return
    running = int(
        (
            conn.execute(
                """
                SELECT COUNT(1) AS cnt
                FROM assignment_nodes
                WHERE ticket_id=? AND status='running'
                """,
                (ticket_id,),
            ).fetchone()
            or {"cnt": 0}
        )["cnt"]
    )
    if running > 0:
        return
    conn.execute(
        """
        UPDATE assignment_graphs
        SET scheduler_state='paused',updated_at=?
        WHERE ticket_id=?
        """,
        (now_text, ticket_id),
    )


def _refresh_all_pause_states(conn: sqlite3.Connection) -> None:
    now_text = iso_ts(now_local())
    _reconcile_stale_running_nodes(conn)
    conn.execute(
        """
        UPDATE assignment_graphs
        SET scheduler_state='paused',updated_at=?
        WHERE scheduler_state='pause_pending'
          AND ticket_id NOT IN (
              SELECT DISTINCT ticket_id
              FROM assignment_nodes
              WHERE status='running'
          )
        """,
        (now_text,),
    )


def _recompute_graph_statuses(
    conn: sqlite3.Connection,
    ticket_id: str,
    *,
    sticky_node_ids: set[str] | None = None,
    reconcile_running: bool = True,
) -> dict[str, str]:
    if reconcile_running:
        _reconcile_stale_running_nodes(conn, ticket_id=ticket_id)
    now_text = iso_ts(now_local())
    sticky = {
        str(item or "").strip()
        for item in (sticky_node_ids or set())
        if str(item or "").strip()
    }
    nodes = _load_nodes(conn, ticket_id)
    edges = _load_edges(conn, ticket_id)
    upstream_map, _downstream_map = _edge_maps(edges)
    status_map = {
        str(node["node_id"]): str(node["status"] or "").strip().lower()
        for node in nodes
    }
    for node in nodes:
        node_id = str(node["node_id"])
        if node_id in sticky:
            continue
        current_status = str(node["status"] or "").strip().lower()
        next_status = _derive_node_status(
            node_id,
            current_status=current_status,
            node_status_map=status_map,
            upstream_map=upstream_map,
        )
        if next_status == current_status:
            continue
        conn.execute(
            """
            UPDATE assignment_nodes
            SET status=?,updated_at=?
            WHERE node_id=? AND ticket_id=?
            """,
            (next_status, now_text, node_id, ticket_id),
        )
        status_map[node_id] = next_status
    _refresh_pause_state(conn, ticket_id, now_text, reconcile_running=False)
    return status_map


def _graph_effective_limit(*, graph_limit: int, system_limit: int) -> int:
    if graph_limit <= 0:
        return system_limit
    return min(graph_limit, system_limit)


def _running_counts(conn: sqlite3.Connection, *, ticket_id: str) -> dict[str, int]:
    _reconcile_stale_running_nodes(conn)
    total_running = int(
        (
            conn.execute(
                "SELECT COUNT(1) AS cnt FROM assignment_nodes WHERE status='running'"
            ).fetchone()
            or {"cnt": 0}
        )["cnt"]
    )
    graph_running = int(
        (
            conn.execute(
                """
                SELECT COUNT(1) AS cnt
                FROM assignment_nodes
                WHERE ticket_id=? AND status='running'
                """,
                (ticket_id,),
            ).fetchone()
            or {"cnt": 0}
        )["cnt"]
    )
    graph_running_agents = int(
        (
            conn.execute(
                """
                SELECT COUNT(DISTINCT assigned_agent_id) AS cnt
                FROM assignment_nodes
                WHERE ticket_id=? AND status='running'
                """,
                (ticket_id,),
            ).fetchone()
            or {"cnt": 0}
        )["cnt"]
    )
    total_running_agents = int(
        (
            conn.execute(
                """
                SELECT COUNT(DISTINCT assigned_agent_id) AS cnt
                FROM assignment_nodes
                WHERE status='running'
                """
            ).fetchone()
            or {"cnt": 0}
        )["cnt"]
    )
    return {
        "system_running_node_count": total_running,
        "graph_running_node_count": graph_running,
        "running_agent_count": graph_running_agents,
        "system_running_agent_count": total_running_agents,
    }
