#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from workflow_app.server.infra.db.connection import connect_db
from workflow_app.server.bootstrap import web_server_runtime as ws


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Acceptance for defect priority truth-source and duplicate graph repair.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8152)
    parser.add_argument("--artifacts-dir", default=os.getenv("TEST_ARTIFACTS_DIR") or ".test/evidence")
    parser.add_argument("--logs-dir", default=os.getenv("TEST_LOG_DIR") or ".test/evidence")
    return parser.parse_args()


def now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def tasks_root(runtime_root: Path) -> Path:
    return (runtime_root / "artifacts" / "tasks").resolve()


def ticket_dir(runtime_root: Path, ticket_id: str) -> Path:
    return (tasks_root(runtime_root) / str(ticket_id or "").strip()).resolve()


def graph_record_path(runtime_root: Path, ticket_id: str) -> Path:
    return ticket_dir(runtime_root, ticket_id) / "task.json"


def node_record_path(runtime_root: Path, ticket_id: str, node_id: str) -> Path:
    return ticket_dir(runtime_root, ticket_id) / "nodes" / f"{str(node_id or '').strip()}.json"


def write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def api_request(
    base_url: str,
    method: str,
    route: str,
    body: dict[str, Any] | None = None,
    *,
    timeout_s: int = 30,
) -> tuple[int, Any]:
    payload = None
    headers = {"Accept": "application/json"}
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(base_url + route, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=max(5, int(timeout_s))) as response:
            raw = response.read()
            content_type = str(response.headers.get("Content-Type") or "")
            if "application/json" in content_type:
                payload = json.loads(raw.decode("utf-8")) if raw else {}
                return int(response.status), payload if isinstance(payload, dict) else {}
            return int(response.status), raw.decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        content_type = str(exc.headers.get("Content-Type") or "")
        if "application/json" in content_type:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
            return int(exc.code), payload if isinstance(payload, dict) else {}
        return int(exc.code), raw.decode("utf-8")


def write_api_trace(
    api_root: Path,
    name: str,
    *,
    method: str,
    route: str,
    request_body: dict[str, Any] | None,
    status: int,
    response_body: Any,
) -> None:
    write_json(
        api_root / f"{name}.json",
        {
            "method": method,
            "route": route,
            "request_body": request_body,
            "status": status,
            "response": response_body,
        },
    )


def call_json_api(
    base_url: str,
    api_root: Path,
    name: str,
    method: str,
    route: str,
    body: dict[str, Any] | None = None,
    *,
    timeout_s: int = 30,
) -> tuple[int, dict[str, Any]]:
    status, payload = api_request(base_url, method, route, body, timeout_s=timeout_s)
    response_body = payload if isinstance(payload, dict) else {"raw": payload}
    write_api_trace(
        api_root,
        name,
        method=method,
        route=route,
        request_body=body,
        status=status,
        response_body=response_body,
    )
    return status, response_body


def assert_response_ok(status: int, payload: dict[str, Any], message: str) -> dict[str, Any]:
    assert_true(status == 200 and bool(payload.get("ok")), message)
    return payload


def wait_for_health(base_url: str, timeout_s: float = 45.0) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            status, data = api_request(base_url, "GET", "/healthz")
            if status == 200 and isinstance(data, dict) and data.get("ok"):
                return data
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError("healthz timeout")


def load_workspace_runtime_config(workspace_root: Path) -> dict[str, Any]:
    for candidate in (
        workspace_root / ".runtime" / "state" / "runtime-config.json",
        workspace_root / "state" / "runtime-config.json",
    ):
        if not candidate.exists():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}


def infer_agent_search_root(workspace_root: Path) -> str:
    configured = str(load_workspace_runtime_config(workspace_root).get("agent_search_root") or "").strip()
    if configured:
        return configured
    return workspace_root.parent.as_posix()


def prepare_isolated_runtime_root(workspace_root: Path, runtime_root: Path) -> tuple[Path, dict[str, Any]]:
    runtime_root = runtime_root.resolve()
    state_dir = runtime_root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    bootstrap_cfg = {
        "show_test_data": True,
        "agent_search_root": infer_agent_search_root(workspace_root),
        "artifact_root": (runtime_root / "artifacts").as_posix(),
        "task_artifact_root": (runtime_root / "artifacts").as_posix(),
    }
    (state_dir / "runtime-config.json").write_text(
        json.dumps(bootstrap_cfg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return runtime_root, bootstrap_cfg


def launch_server(
    workspace_root: Path,
    runtime_root: Path,
    *,
    host: str,
    port: int,
    stdout_path: Path,
    stderr_path: Path,
) -> tuple[subprocess.Popen[bytes], Any, Any]:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_handle = stdout_path.open("wb")
    stderr_handle = stderr_path.open("wb")
    env = os.environ.copy()
    env["WORKFLOW_RUNTIME_ENV"] = "test"
    server = subprocess.Popen(
        [sys.executable, "scripts/workflow_web_server.py", "--root", str(runtime_root), "--host", host, "--port", str(port)],
        cwd=str(workspace_root),
        stdout=stdout_handle,
        stderr=stderr_handle,
        env=env,
    )
    return server, stdout_handle, stderr_handle


def stop_server(server: subprocess.Popen[bytes], stdout_handle: Any, stderr_handle: Any) -> None:
    try:
        server.terminate()
        server.wait(timeout=10)
    except subprocess.TimeoutExpired:
        server.kill()
        server.wait(timeout=10)
    finally:
        stdout_handle.close()
        stderr_handle.close()


@contextmanager
def running_server(
    workspace_root: Path,
    runtime_root: Path,
    *,
    host: str,
    port: int,
    stdout_path: Path,
    stderr_path: Path,
) -> Iterator[None]:
    server, stdout_handle, stderr_handle = launch_server(
        workspace_root,
        runtime_root,
        host=host,
        port=port,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )
    try:
        yield
    finally:
        stop_server(server, stdout_handle, stderr_handle)


def build_process_specs(report_id: str, *, assignee: str, priority: int) -> list[dict[str, Any]]:
    analyze_node_id = f"{report_id}-analyze"
    fix_node_id = f"{report_id}-fix"
    return [
        {
            "node_id": analyze_node_id,
            "node_name": "分析缺陷",
            "assigned_agent_id": assignee,
            "node_goal": "旧流程分析缺陷。",
            "expected_artifact": "分析缺陷报告.html",
            "priority": priority,
            "upstream_node_ids": [],
        },
        {
            "node_id": fix_node_id,
            "node_name": "修复缺陷",
            "assigned_agent_id": assignee,
            "node_goal": "旧流程修复缺陷。",
            "expected_artifact": "缺陷修复说明.html",
            "priority": priority,
            "upstream_node_ids": [analyze_node_id],
        },
        {
            "node_id": f"{report_id}-release",
            "node_name": "推送到目标版本",
            "assigned_agent_id": assignee,
            "node_goal": "旧流程推送版本。",
            "expected_artifact": "目标版本发布记录.html",
            "priority": priority,
            "upstream_node_ids": [fix_node_id],
        },
    ]


def build_review_specs(report_id: str, *, assignee: str, priority: int) -> list[dict[str, Any]]:
    return [
        {
            "node_id": f"{report_id}-review",
            "node_name": "复核争议",
            "assigned_agent_id": assignee,
            "node_goal": "旧流程复核争议。",
            "expected_artifact": "复核争议结论.html",
            "priority": priority,
            "upstream_node_ids": [],
        }
    ]


def edge_rows_from_specs(node_specs: list[dict[str, Any]], *, created_at: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in list(node_specs or []):
        to_node_id = str(spec.get("node_id") or "").strip()
        for from_node_id in list(spec.get("upstream_node_ids") or []):
            if not str(from_node_id or "").strip() or not to_node_id:
                continue
            rows.append(
                {
                    "from_node_id": str(from_node_id).strip(),
                    "to_node_id": to_node_id,
                    "edge_kind": "depends_on",
                    "created_at": created_at,
                    "record_state": "active",
                }
            )
    return rows


def seed_legacy_graph(
    runtime_root: Path,
    *,
    ticket_id: str,
    graph_name: str,
    source_workflow: str,
    external_request_id: str,
    node_specs: list[dict[str, Any]],
) -> None:
    created_at = now_text()
    task_record = {
        "record_type": "assignment_task",
        "schema_version": 1,
        "record_state": "active",
        "ticket_id": ticket_id,
        "graph_name": graph_name,
        "source_workflow": str(source_workflow or "").strip() or "workflow-ui",
        "summary": "legacy defect graph",
        "review_mode": "none",
        "global_concurrency_limit": 4,
        "is_test_data": True,
        "external_request_id": external_request_id,
        "scheduler_state": "idle",
        "pause_note": "",
        "created_at": created_at,
        "updated_at": created_at,
        "deleted_at": "",
        "deleted_reason": "",
        "edges": edge_rows_from_specs(node_specs, created_at=created_at),
    }
    write_json_file(graph_record_path(runtime_root, ticket_id), task_record)
    for spec in list(node_specs or []):
        node_id = str(spec.get("node_id") or "").strip()
        node_payload = {
            "record_type": "assignment_node",
            "schema_version": 1,
            "record_state": "active",
            "ticket_id": ticket_id,
            "node_id": node_id,
            "node_name": str(spec.get("node_name") or "").strip(),
            "source_schedule_id": "",
            "planned_trigger_at": "",
            "trigger_instance_id": "",
            "trigger_rule_summary": "",
            "assigned_agent_id": str(spec.get("assigned_agent_id") or "").strip(),
            "assigned_agent_name": str(spec.get("assigned_agent_id") or "").strip(),
            "node_goal": str(spec.get("node_goal") or "").strip(),
            "expected_artifact": str(spec.get("expected_artifact") or "").strip(),
            "delivery_mode": "specified",
            "delivery_receiver_agent_id": str(spec.get("assigned_agent_id") or "").strip(),
            "delivery_receiver_agent_name": str(spec.get("assigned_agent_id") or "").strip(),
            "artifact_delivery_status": "pending",
            "artifact_delivered_at": "",
            "artifact_paths": [],
            "status": "pending",
            "priority": int(spec.get("priority") or 1),
            "completed_at": "",
            "success_reason": "",
            "result_ref": "",
            "failure_reason": "",
            "created_at": created_at,
            "updated_at": created_at,
            "upstream_node_ids": [
                str(item or "").strip()
                for item in list(spec.get("upstream_node_ids") or [])
                if str(item or "").strip()
            ],
            "downstream_node_ids": [],
        }
        write_json_file(node_record_path(runtime_root, ticket_id, node_id), node_payload)


def seed_task_refs(
    runtime_root: Path,
    *,
    report_id: str,
    ticket_id: str,
    action_kind: str,
    node_specs: list[dict[str, Any]],
) -> None:
    conn = connect_db(runtime_root)
    try:
        conn.execute("BEGIN")
        for spec in list(node_specs or []):
            created_at = now_text()
            focus_node_id = str(spec.get("node_id") or "").strip()
            title = str(spec.get("node_name") or "").strip()
            external_request_id = f"defect:{action_kind}:{report_id}"
            rows = conn.execute(
                """
                SELECT ref_id FROM defect_task_refs
                WHERE report_id=? AND focus_node_id=? AND external_request_id=?
                ORDER BY updated_at DESC, created_at DESC, ref_id DESC
                """,
                (report_id, focus_node_id, external_request_id),
            ).fetchall()
            if not rows:
                conn.execute(
                    """
                    INSERT INTO defect_task_refs(
                        ref_id,report_id,ticket_id,focus_node_id,action_kind,title,external_request_id,created_at,updated_at
                    )
                    VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        f"dtr-seed-{report_id[-6:]}-{focus_node_id[-12:]}",
                        report_id,
                        ticket_id,
                        focus_node_id,
                        action_kind,
                        title,
                        external_request_id,
                        created_at,
                        created_at,
                    ),
                )
                continue
            conn.execute(
                """
                UPDATE defect_task_refs
                SET ticket_id=?, action_kind=?, title=?, updated_at=?
                WHERE ref_id=?
                """,
                (
                    ticket_id,
                    action_kind,
                    title,
                    created_at,
                    str(rows[0]["ref_id"] or "").strip(),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def collect_active_tickets_by_request(runtime_root: Path, external_request_id: str) -> list[str]:
    items: list[str] = []
    artifact_tasks_root = tasks_root(runtime_root)
    if not artifact_tasks_root.exists() or not artifact_tasks_root.is_dir():
        return items
    for path in sorted(artifact_tasks_root.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_dir():
            continue
        graph_path = graph_record_path(runtime_root, str(path.name or "").strip())
        if not graph_path.exists():
            continue
        try:
            payload = json.loads(graph_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        if str(payload.get("record_state") or "active").strip().lower() == "deleted":
            continue
        if str(payload.get("external_request_id") or "").strip() != external_request_id:
            continue
        items.append(str(payload.get("ticket_id") or "").strip())
    return items


def read_graph_state(runtime_root: Path, ticket_id: str) -> dict[str, Any]:
    graph_path = graph_record_path(runtime_root, ticket_id)
    if not graph_path.exists():
        return {}
    try:
        payload = json.loads(graph_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def assert_assignment_priority(
    overview: dict[str, Any],
    *,
    expected_priority: str,
    node_ids: list[str],
    message: str,
) -> None:
    wanted = {str(item or "").strip() for item in node_ids if str(item or "").strip()}
    nodes = [
        node
        for node in list(overview.get("nodes") or overview.get("node_catalog") or [])
        if str((node or {}).get("node_id") or "").strip() in wanted
    ]
    assert_true(bool(nodes), f"{message}: focus nodes missing")
    labels = [
        str((node or {}).get("priority_label") or "").strip()
        or str((node or {}).get("priority") or "").strip()
        for node in nodes
    ]
    assert_true(all(label == expected_priority for label in labels), f"{message}: priorities={labels}")


def create_defect(
    base_url: str,
    api_root: Path,
    *,
    name: str,
    defect_summary: str,
    report_text: str,
) -> dict[str, Any]:
    body = {
        "defect_summary": defect_summary,
        "report_text": report_text,
        "evidence_images": [],
        "is_test_data": True,
        "operator": "acceptance",
        "automation_context": {
            "suite_id": "defect-priority-truth",
            "case_id": name,
            "run_id": "repair-ac",
            "env": "test",
        },
    }
    status, payload = call_json_api(base_url, api_root, f"create-{name}", "POST", "/api/defects", body)
    data = assert_response_ok(status, payload, f"create defect failed: {name}")
    report = dict(data.get("report") or {})
    assert_true(bool(report.get("is_formal")), f"defect not formal: {name}")
    assert_true(str(report.get("task_priority") or "").strip() == "P0", f"priority parse failed: {name}")
    return report


def exercise_acceptance(base_url: str, runtime_root: Path, artifacts_root: Path) -> dict[str, Any]:
    api_root = artifacts_root / "api"
    process_report = create_defect(
        base_url,
        api_root,
        name="process-summary-p0",
        defect_summary="[P0] 任务中心入口无法打开",
        report_text="升级后任务中心入口直接报错，属于 workflow 缺陷，需要立即修复。",
    )
    review_report = create_defect(
        base_url,
        api_root,
        name="review-text-p0",
        defect_summary="复核入口报错",
        report_text="升级后复核入口无法稳定打开，建议优先级：P0，需要复核处理。",
    )
    process_report_id = str(process_report.get("report_id") or "").strip()
    review_report_id = str(review_report.get("report_id") or "").strip()
    assert_true(process_report_id != "" and review_report_id != "", "report ids missing")

    status, dispute_payload = call_json_api(
        base_url,
        api_root,
        "mark-review-dispute",
        "POST",
        f"/api/defects/{review_report_id}/dispute",
        {"reason": "进入复核链路。", "operator": "acceptance"},
    )
    dispute_payload = assert_response_ok(status, dispute_payload, "mark dispute failed")
    assert_true(str(((dispute_payload.get("report") or {}).get("status") or "")).strip() == "dispute", "review not dispute")

    assignee = "workflow"
    process_specs = build_process_specs(process_report_id, assignee=assignee, priority=1)
    review_specs = build_review_specs(review_report_id, assignee=assignee, priority=1)
    legacy_process_tickets = [
        f"asg-legacy-{process_report_id[-6:]}-p1",
        f"asg-legacy-{process_report_id[-6:]}-p2",
    ]
    legacy_review_ticket = f"asg-legacy-{review_report_id[-6:]}-r1"
    for index, ticket_id in enumerate(legacy_process_tickets, start=1):
        seed_legacy_graph(
            runtime_root,
            ticket_id=ticket_id,
            graph_name=f"旧缺陷处理图-{index}",
            source_workflow="defect-center",
            external_request_id=f"defect:process:{process_report_id}",
            node_specs=process_specs,
        )
    seed_legacy_graph(
        runtime_root,
        ticket_id=legacy_review_ticket,
        graph_name="旧缺陷复核图",
        source_workflow="defect-center-review",
        external_request_id=f"defect:review:{review_report_id}",
        node_specs=review_specs,
    )
    seed_task_refs(
        runtime_root,
        report_id=process_report_id,
        ticket_id=legacy_process_tickets[-1],
        action_kind="process",
        node_specs=process_specs,
    )
    seed_task_refs(
        runtime_root,
        report_id=review_report_id,
        ticket_id=legacy_review_ticket,
        action_kind="review",
        node_specs=review_specs,
    )
    assert_true(
        len(collect_active_tickets_by_request(runtime_root, f"defect:process:{process_report_id}")) == 2,
        "legacy process duplicates not seeded",
    )
    assert_true(
        len(collect_active_tickets_by_request(runtime_root, f"defect:review:{review_report_id}")) == 1,
        "legacy review duplicate not seeded",
    )

    repair_result = ws.repair_defect_assignment_state(runtime_root)
    assert_true(bool(repair_result.get("ok")), "explicit repair should succeed")

    status, process_detail = call_json_api(
        base_url,
        api_root,
        "process-detail-after-repair",
        "GET",
        f"/api/defects/{process_report_id}",
    )
    process_detail = assert_response_ok(status, process_detail, "process detail failed")
    status, review_detail = call_json_api(
        base_url,
        api_root,
        "review-detail-after-repair",
        "GET",
        f"/api/defects/{review_report_id}",
    )
    review_detail = assert_response_ok(status, review_detail, "review detail failed")

    process_report_after = dict(process_detail.get("report") or {})
    review_report_after = dict(review_detail.get("report") or {})
    assert_true(str(process_report_after.get("task_priority") or "").strip() == "P0", "process task_priority mismatch")
    assert_true(str(review_report_after.get("task_priority") or "").strip() == "P0", "review task_priority mismatch")

    process_task_refs = list(process_detail.get("task_refs") or [])
    review_task_refs = list(review_detail.get("task_refs") or [])
    assert_true(len(process_task_refs) == 3, "process task refs should be unified to 3 nodes")
    assert_true(len(review_task_refs) == 1, "review task refs should be unified to 1 node")
    process_ticket_id = str((process_task_refs[0] or {}).get("ticket_id") or "").strip()
    review_ticket_id = str((review_task_refs[0] or {}).get("ticket_id") or "").strip()
    assert_true(process_ticket_id != "" and review_ticket_id != "", "global ticket ids missing")
    assert_true(process_ticket_id == review_ticket_id, "process/review should share the global graph")

    status, process_task_once = call_json_api(
        base_url,
        api_root,
        "process-task-once",
        "POST",
        f"/api/defects/{process_report_id}/process-task",
        {"operator": "acceptance"},
        timeout_s=120,
    )
    process_task_once = assert_response_ok(status, process_task_once, "process task once failed")
    status, process_task_twice = call_json_api(
        base_url,
        api_root,
        "process-task-twice",
        "POST",
        f"/api/defects/{process_report_id}/process-task",
        {"operator": "acceptance"},
        timeout_s=120,
    )
    process_task_twice = assert_response_ok(status, process_task_twice, "process task twice failed")
    assert_true(str(process_task_once.get("created_task_ticket_id") or "").strip() == process_ticket_id, "process ticket changed")
    assert_true(str(process_task_twice.get("created_task_ticket_id") or "").strip() == process_ticket_id, "process ticket duplicated")

    status, review_task_once = call_json_api(
        base_url,
        api_root,
        "review-task-once",
        "POST",
        f"/api/defects/{review_report_id}/review-task",
        {"operator": "acceptance"},
        timeout_s=120,
    )
    review_task_once = assert_response_ok(status, review_task_once, "review task once failed")
    status, review_task_twice = call_json_api(
        base_url,
        api_root,
        "review-task-twice",
        "POST",
        f"/api/defects/{review_report_id}/review-task",
        {"operator": "acceptance"},
        timeout_s=120,
    )
    review_task_twice = assert_response_ok(status, review_task_twice, "review task twice failed")
    assert_true(str(review_task_once.get("created_task_ticket_id") or "").strip() == process_ticket_id, "review ticket changed")
    assert_true(str(review_task_twice.get("created_task_ticket_id") or "").strip() == process_ticket_id, "review ticket duplicated")

    status, assignment_graph = call_json_api(
        base_url,
        api_root,
        "global-assignment-graph",
        "GET",
        f"/api/assignments/{process_ticket_id}/graph",
    )
    assignment_graph = assert_response_ok(status, assignment_graph, "global assignment graph failed")
    assert_assignment_priority(
        assignment_graph,
        expected_priority="P0",
        node_ids=[str(item.get("node_id") or "").strip() for item in process_specs],
        message="process graph priority mismatch",
    )
    assert_assignment_priority(
        assignment_graph,
        expected_priority="P0",
        node_ids=[str(item.get("node_id") or "").strip() for item in review_specs],
        message="review graph priority mismatch",
    )

    status, assignments_payload = call_json_api(base_url, api_root, "assignments-list", "GET", "/api/assignments")
    assignments_payload = assert_response_ok(status, assignments_payload, "assignments list failed")
    assignment_items = list(assignments_payload.get("items") or [])
    visible_ticket_ids = [str((item or {}).get("ticket_id") or "").strip() for item in assignment_items]
    assert_true(process_ticket_id in visible_ticket_ids, "global ticket missing from assignments list")
    assert_true(all(ticket_id not in visible_ticket_ids for ticket_id in legacy_process_tickets + [legacy_review_ticket]), "deleted legacy graph still visible")
    assert_true(
        collect_active_tickets_by_request(runtime_root, f"defect:process:{process_report_id}") == [],
        "active legacy process graph still exists",
    )
    assert_true(
        collect_active_tickets_by_request(runtime_root, f"defect:review:{review_report_id}") == [],
        "active legacy review graph still exists",
    )

    deleted_graph_states = {
        ticket_id: read_graph_state(runtime_root, ticket_id)
        for ticket_id in legacy_process_tickets + [legacy_review_ticket]
    }
    assert_true(
        all(str((state or {}).get("record_state") or "").strip().lower() == "deleted" for state in deleted_graph_states.values()),
        "legacy graph record_state not deleted",
    )
    status, legacy_process_graph = call_json_api(
        base_url,
        api_root,
        "legacy-process-graph-after-repair",
        "GET",
        f"/api/assignments/{legacy_process_tickets[0]}/graph",
    )
    assert_true(status == 404, "legacy process graph should be hidden after repair")
    status, legacy_review_graph = call_json_api(
        base_url,
        api_root,
        "legacy-review-graph-after-repair",
        "GET",
        f"/api/assignments/{legacy_review_ticket}/graph",
    )
    assert_true(status == 404, "legacy review graph should be hidden after repair")

    status, final_process_detail = call_json_api(
        base_url,
        api_root,
        "process-detail-final",
        "GET",
        f"/api/defects/{process_report_id}",
    )
    final_process_detail = assert_response_ok(status, final_process_detail, "process final detail failed")
    final_process_refs = list(final_process_detail.get("task_refs") or [])
    assert_true(
        len({str((item or {}).get("focus_node_id") or "").strip() for item in final_process_refs}) == 3,
        "process task refs duplicated after repeated calls",
    )

    return {
        "process": {
            "report_id": process_report_id,
            "display_id": str(process_report_after.get("display_id") or "").strip(),
            "task_priority": str(process_report_after.get("task_priority") or "").strip(),
            "ticket_id": process_ticket_id,
            "legacy_ticket_ids": legacy_process_tickets,
        },
        "review": {
            "report_id": review_report_id,
            "display_id": str(review_report_after.get("display_id") or "").strip(),
            "task_priority": str(review_report_after.get("task_priority") or "").strip(),
            "ticket_id": review_ticket_id,
            "legacy_ticket_ids": [legacy_review_ticket],
        },
        "global_ticket_id": process_ticket_id,
        "visible_ticket_ids": visible_ticket_ids,
        "deleted_graph_states": deleted_graph_states,
    }


def main() -> int:
    args = parse_args()
    workspace_root = Path(args.root).resolve()
    artifacts_root = Path(args.artifacts_dir).resolve() / "defect-priority-truth-and-idempotency"
    logs_root = Path(args.logs_dir).resolve() / "defect-priority-truth-and-idempotency"
    if artifacts_root.exists():
        shutil.rmtree(artifacts_root, ignore_errors=True)
    if logs_root.exists():
        shutil.rmtree(logs_root, ignore_errors=True)
    artifacts_root.mkdir(parents=True, exist_ok=True)
    logs_root.mkdir(parents=True, exist_ok=True)
    runtime_root = Path(os.getenv("TEST_TMP_DIR") or (artifacts_root / "runtime")).resolve()
    if runtime_root.exists():
        shutil.rmtree(runtime_root, ignore_errors=True)
    runtime_root, bootstrap_cfg = prepare_isolated_runtime_root(workspace_root, runtime_root)
    base_url = f"http://{args.host}:{int(args.port)}"
    with running_server(
        workspace_root,
        runtime_root,
        host=args.host,
        port=int(args.port),
        stdout_path=logs_root / "server.stdout.log",
        stderr_path=logs_root / "server.stderr.log",
    ):
        health = wait_for_health(base_url)
        summary = {
            "ok": True,
            "base_url": base_url,
            "health": health,
            "bootstrap_cfg": bootstrap_cfg,
            "evidence": exercise_acceptance(base_url, runtime_root, artifacts_root),
            "evidence_paths": {
                "api_root": (artifacts_root / "api").as_posix(),
                "server_stdout": (logs_root / "server.stdout.log").as_posix(),
                "server_stderr": (logs_root / "server.stderr.log").as_posix(),
                "runtime_root": runtime_root.as_posix(),
            },
        }
        write_json(artifacts_root / "summary.json", summary)
        print((artifacts_root / "summary.json").as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
