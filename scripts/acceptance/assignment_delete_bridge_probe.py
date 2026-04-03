#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe assignment delete/clear bridge rules.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8128)
    parser.add_argument("--root", default=".")
    parser.add_argument("--artifacts-dir", default=os.getenv("TEST_ARTIFACTS_DIR") or ".test/evidence")
    parser.add_argument("--logs-dir", default=os.getenv("TEST_LOG_DIR") or ".test/evidence")
    return parser.parse_args()


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def read_json_response(response: urllib.request.addinfourl) -> dict[str, Any]:
    raw = response.read()
    if not raw:
        return {}
    payload = json.loads(raw.decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def api_request(base_url: str, method: str, route: str, body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    payload = None
    headers = {"Accept": "application/json"}
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        base_url + route,
        data=payload,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return int(response.status), read_json_response(response)
    except urllib.error.HTTPError as exc:
        try:
            data = read_json_response(exc)
        except Exception:
            data = {}
        return int(exc.code), data


def wait_for_health(base_url: str, timeout_s: float = 30.0) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            status, data = api_request(base_url, "GET", "/healthz")
            if status == 200 and data.get("ok"):
                return data
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError("healthz timeout")


def load_json_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_workspace_runtime_config(workspace_root: Path) -> dict[str, Any]:
    config_path = workspace_root / ".runtime" / "state" / "runtime-config.json"
    if not config_path.exists():
        return {}
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def prepare_isolated_runtime_root(workspace_root: Path, runtime_root: Path) -> tuple[Path, dict[str, Any]]:
    runtime_root = runtime_root.resolve()
    state_dir = runtime_root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    source_cfg = load_workspace_runtime_config(workspace_root)
    bootstrap_cfg: dict[str, Any] = {}
    agent_search_root = str(source_cfg.get("agent_search_root") or "").strip()
    if agent_search_root:
        bootstrap_cfg["agent_search_root"] = agent_search_root
    if "show_test_data" in source_cfg:
        bootstrap_cfg["show_test_data"] = bool(source_cfg.get("show_test_data"))
    if bootstrap_cfg:
        (state_dir / "runtime-config.json").write_text(
            json.dumps(bootstrap_cfg, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return runtime_root, bootstrap_cfg


def main() -> int:
    args = parse_args()
    workspace_root = Path(args.root).resolve()
    artifacts_dir = Path(args.artifacts_dir).resolve()
    logs_dir = Path(args.logs_dir).resolve()
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    evidence_root = artifacts_dir / "assignment-delete-bridge-probe"
    evidence_root.mkdir(parents=True, exist_ok=True)
    log_root = logs_dir / "assignment-delete-bridge-probe"
    log_root.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_root / "summary.json"
    server_stdout = log_root / "server.stdout.log"
    server_stderr = log_root / "server.stderr.log"
    runtime_base = Path(os.getenv("TEST_TMP_DIR") or (workspace_root / ".test" / "runtime")).resolve()
    runtime_root, bootstrap_cfg = prepare_isolated_runtime_root(
        workspace_root,
        runtime_base / "assignment-delete-bridge-probe",
    )
    runtime_db = runtime_root / "state" / "workflow.db"
    base_url = f"http://{args.host}:{args.port}"

    stdout_handle = server_stdout.open("ab")
    stderr_handle = server_stderr.open("ab")
    server = subprocess.Popen(
        [
            sys.executable,
            "scripts/workflow_web_server.py",
            "--root",
            str(runtime_root),
            "--host",
            args.host,
            "--port",
            str(args.port),
        ],
        cwd=str(workspace_root),
        stdout=stdout_handle,
        stderr=stderr_handle,
    )

    evidence: dict[str, Any] = {
        "base_url": base_url,
        "runtime_db": str(runtime_db),
        "runtime_root": str(runtime_root),
        "runtime_bootstrap_config": bootstrap_cfg,
        "workspace_root": str(workspace_root),
    }

    try:
        evidence["healthz"] = wait_for_health(base_url)

        status, agents_payload = api_request(base_url, "GET", "/api/training/agents")
        assert_true(status == 200 and agents_payload.get("ok"), "training agents unavailable")
        agent_ids = [
            str((item or {}).get("agent_id") or "").strip()
            for item in list(agents_payload.get("items") or [])
            if str((item or {}).get("agent_id") or "").strip()
        ]
        assert_true(bool(agent_ids), "no training agents available")
        artifact_workspace_root_text = str(agents_payload.get("artifact_workspace_root") or "").strip()
        assert_true(bool(artifact_workspace_root_text), "artifact workspace root missing")
        artifact_workspace_root = Path(artifact_workspace_root_text).resolve()
        evidence["training_agents"] = {
            "count": len(agent_ids),
            "artifact_workspace_root": str(artifact_workspace_root),
        }

        status, create_graph = api_request(
            base_url,
            "POST",
            "/api/assignments",
            {
                "graph_name": "删除桥接探针",
                "source_workflow": "assignment-delete-bridge-probe",
                "summary": "probe delete bridge and clear rules",
                "review_mode": "none",
                "external_request_id": f"delete-bridge-{int(time.time() * 1000)}",
                "operator": "assignment-delete-bridge-probe",
            },
        )
        assert_true(status == 200 and create_graph.get("ok"), "create graph failed")
        ticket_id = str(create_graph.get("ticket_id") or "").strip()
        assert_true(ticket_id, "ticket_id missing")
        evidence["bridge_ticket_id"] = ticket_id

        node_ids: dict[str, str] = {}
        node_specs = [
            ("A", "上游A", []),
            ("B", "上游B", []),
            ("X", "中间节点", ["A", "B"]),
            ("C", "下游C", ["X", "A"]),
            ("D", "下游D", ["X"]),
        ]
        for index, (key, label, upstream_keys) in enumerate(node_specs):
            upstream_ids = [node_ids[item] for item in upstream_keys]
            status, created = api_request(
                base_url,
                "POST",
                f"/api/assignments/{ticket_id}/nodes",
                {
                    "node_name": label,
                    "assigned_agent_id": agent_ids[index % len(agent_ids)],
                    "priority": "P1",
                    "node_goal": label + " probe",
                    "expected_artifact": label + " artifact",
                    "upstream_node_ids": upstream_ids,
                    "operator": "assignment-delete-bridge-probe",
                },
            )
            assert_true(status == 200 and created.get("ok"), f"create node failed: {key}")
            node_id = str(((created.get("node") or {}).get("node_id")) or "").strip()
            assert_true(node_id, f"node id missing: {key}")
            node_ids[key] = node_id
        evidence["bridge_node_ids"] = dict(node_ids)

        status, delete_payload = api_request(
            base_url,
            "DELETE",
            f"/api/assignments/{ticket_id}/nodes/{node_ids['X']}",
            {"operator": "assignment-delete-bridge-probe"},
        )
        assert_true(status == 200 and delete_payload.get("ok"), "delete middle node failed")
        bridge_summary = delete_payload.get("bridge_summary") or {}
        added_edges = {
            (str(item.get("from_node_id") or "").strip(), str(item.get("to_node_id") or "").strip())
            for item in list(bridge_summary.get("bridge_added") or [])
        }
        skipped = list(bridge_summary.get("bridge_skipped") or [])
        expected_added = {
            (node_ids["A"], node_ids["D"]),
            (node_ids["B"], node_ids["C"]),
            (node_ids["B"], node_ids["D"]),
        }
        assert_true(added_edges == expected_added, "bridge added edges mismatch")
        duplicate_skip = [
            item
            for item in skipped
            if str(item.get("reason") or "").strip() == "duplicate_edge_skipped"
            and str(item.get("from_node_id") or "").strip() == node_ids["A"]
            and str(item.get("to_node_id") or "").strip() == node_ids["C"]
        ]
        assert_true(bool(duplicate_skip), "duplicate bridge edge was not skipped")
        evidence["delete_response"] = delete_payload

        status, graph_payload = api_request(
            base_url,
            "GET",
            f"/api/assignments/{ticket_id}/graph?history_loaded=12&history_batch_size=12",
        )
        assert_true(status == 200 and graph_payload.get("ok"), "graph fetch after delete failed")
        edges_after_delete = {
            (
                str(item.get("from_node_id") or "").strip(),
                str(item.get("to_node_id") or "").strip(),
            )
            for item in list(graph_payload.get("edges") or [])
        }
        expected_edges_after_delete = {
            (node_ids["A"], node_ids["C"]),
            (node_ids["A"], node_ids["D"]),
            (node_ids["B"], node_ids["C"]),
            (node_ids["B"], node_ids["D"]),
        }
        assert_true(edges_after_delete == expected_edges_after_delete, "graph edges after delete mismatch")
        assert_true(
            all(str((item or {}).get("node_id") or "").strip() != node_ids["X"] for item in list(graph_payload.get("nodes") or [])),
            "deleted node still present in graph",
        )
        evidence["graph_after_delete"] = {
            "node_count": len(list(graph_payload.get("nodes") or [])),
            "edge_count": len(list(graph_payload.get("edges") or [])),
            "edges": sorted(list(edges_after_delete)),
        }

        ticket_workspace = artifact_workspace_root / "assignments" / ticket_id
        deleted_node_record = load_json_file(ticket_workspace / "nodes" / f"{node_ids['X']}.json")
        assert_true(deleted_node_record.get("record_state") == "deleted", "deleted node record state mismatch")
        assert_true(
            ((deleted_node_record.get("extra") or {}).get("delete_action") == "delete_node"),
            "deleted node record missing delete action",
        )

        status, clear_payload = api_request(
            base_url,
            "POST",
            f"/api/assignments/{ticket_id}/clear",
            {"operator": "assignment-delete-bridge-probe"},
        )
        assert_true(status == 200 and clear_payload.get("ok"), "clear graph failed")
        evidence["clear_response"] = clear_payload

        status, cleared_graph = api_request(
            base_url,
            "GET",
            f"/api/assignments/{ticket_id}/graph?history_loaded=12&history_batch_size=12",
        )
        assert_true(status == 200 and cleared_graph.get("ok"), "graph fetch after clear failed")
        assert_true(len(list(cleared_graph.get("nodes") or [])) == 0, "clear did not remove all nodes")
        assert_true(len(list(cleared_graph.get("edges") or [])) == 0, "clear did not remove all edges")
        cleared_a_record = load_json_file(ticket_workspace / "nodes" / f"{node_ids['A']}.json")
        assert_true(cleared_a_record.get("record_state") == "deleted", "cleared node record state mismatch")
        assert_true(
            ((cleared_a_record.get("extra") or {}).get("delete_action") == "clear_graph"),
            "cleared node record missing clear action",
        )
        evidence["workspace_records"] = {
            "ticket_dir": str(ticket_workspace),
            "deleted_node_record": str(ticket_workspace / "nodes" / f"{node_ids['X']}.json"),
            "cleared_node_record": str(ticket_workspace / "nodes" / f"{node_ids['A']}.json"),
            "graph_record": str(ticket_workspace / "graph.json"),
        }

        status, running_graph = api_request(
            base_url,
            "POST",
            "/api/assignments",
            {
                "graph_name": "运行中删除拦截探针",
                "source_workflow": "assignment-delete-running-probe",
                "summary": "probe running node delete and clear guard",
                "review_mode": "none",
                "external_request_id": f"delete-running-{int(time.time() * 1000)}",
                "operator": "assignment-delete-bridge-probe",
            },
        )
        assert_true(status == 200 and running_graph.get("ok"), "create running graph failed")
        running_ticket_id = str(running_graph.get("ticket_id") or "").strip()
        assert_true(running_ticket_id, "running ticket id missing")
        status, running_node = api_request(
            base_url,
            "POST",
            f"/api/assignments/{running_ticket_id}/nodes",
            {
                "node_name": "运行中节点",
                "assigned_agent_id": agent_ids[0],
                "priority": "P0",
                "node_goal": "running node probe",
                "expected_artifact": "",
                "operator": "assignment-delete-bridge-probe",
            },
        )
        assert_true(status == 200 and running_node.get("ok"), "create running probe node failed")
        running_node_id = str(((running_node.get("node") or {}).get("node_id")) or "").strip()
        assert_true(running_node_id, "running node id missing")
        if runtime_db.exists():
            conn = sqlite3.connect(str(runtime_db))
            try:
                now_text = iso_now()
                conn.execute(
                    """
                    UPDATE assignment_graphs
                    SET scheduler_state='running',updated_at=?
                    WHERE ticket_id=?
                    """,
                    (now_text, running_ticket_id),
                )
                conn.execute(
                    """
                    UPDATE assignment_nodes
                    SET status='running',updated_at=?
                    WHERE ticket_id=? AND node_id=?
                    """,
                    (now_text, running_ticket_id, running_node_id),
                )
                conn.commit()
            finally:
                conn.close()

        delete_running_status, delete_running_payload = api_request(
            base_url,
            "DELETE",
            f"/api/assignments/{running_ticket_id}/nodes/{running_node_id}",
            {"operator": "assignment-delete-bridge-probe"},
        )
        assert_true(delete_running_status == 409, "running node delete should be rejected")
        assert_true(
            str(delete_running_payload.get("code") or "").strip() == "assignment_delete_running_node_blocked",
            "running node delete rejection code mismatch",
        )

        clear_running_status, clear_running_payload = api_request(
            base_url,
            "POST",
            f"/api/assignments/{running_ticket_id}/clear",
            {"operator": "assignment-delete-bridge-probe"},
        )
        assert_true(clear_running_status == 409, "clear with running node should be rejected")
        assert_true(
            str(clear_running_payload.get("code") or "").strip() == "assignment_clear_has_running_nodes",
            "clear rejection code mismatch",
        )
        evidence["running_guards"] = {
            "ticket_id": running_ticket_id,
            "node_id": running_node_id,
            "delete_reject": delete_running_payload,
            "clear_reject": clear_running_payload,
        }

        if runtime_db.exists():
            conn = sqlite3.connect(str(runtime_db))
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    """
                    SELECT action,node_id,reason,target_status
                    FROM assignment_audit_log
                    WHERE ticket_id IN (?,?)
                    ORDER BY created_at ASC
                    """,
                    (ticket_id, running_ticket_id),
                ).fetchall()
                evidence["audit_rows"] = [
                    {
                        "action": str(row["action"] or "").strip(),
                        "node_id": str(row["node_id"] or "").strip(),
                        "reason": str(row["reason"] or "").strip(),
                        "target_status": str(row["target_status"] or "").strip(),
                    }
                    for row in rows
                ]
            finally:
                conn.close()

        evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "evidence_path": str(evidence_path),
                    "bridge_ticket_id": ticket_id,
                    "running_ticket_id": running_ticket_id,
                    "workspace_ticket_dir": str(ticket_workspace),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    finally:
        try:
            server.terminate()
            server.wait(timeout=5)
        except Exception:
            try:
                server.kill()
            except Exception:
                pass
        stdout_handle.close()
        stderr_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
