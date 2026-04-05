#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import time
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from run_acceptance_schedule_center_browser import (
    BEIJING_TZ,
    api_request,
    assert_true,
    choose_agent,
    infer_agent_search_root,
    prepare_isolated_runtime_root,
    running_server,
    wait_for_health,
    write_json,
)


FAST_SUCCESS_COMMAND_TEMPLATE = 'cmd.exe /c rem "{codex_path}" "{workspace_path}"'


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Acceptance for schedule trigger idempotency and detail writeback.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8166)
    parser.add_argument(
        "--artifacts-dir",
        default=os.getenv("TEST_ARTIFACTS_DIR") or ".test/evidence",
    )
    parser.add_argument(
        "--logs-dir",
        default=os.getenv("TEST_LOG_DIR") or ".test/evidence",
    )
    return parser.parse_args()


def _poll_schedule_detail(base_url: str, schedule_id: str, *, timeout_seconds: float = 20.0) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_body: dict[str, Any] = {}
    route = "/api/schedules/" + urllib.parse.quote(schedule_id)
    while time.time() < deadline:
        status, body = api_request(base_url, "GET", route)
        assert_true(status == 200 and isinstance(body, dict) and body.get("ok"), f"schedule detail failed: {body}")
        last_body = body
        recent = list(body.get("recent_triggers") or [])
        latest = dict(recent[0] or {}) if recent else {}
        schedule = dict(body.get("schedule") or {})
        if (
            str(latest.get("trigger_instance_id") or "").strip()
            and str(latest.get("assignment_ticket_id") or "").strip()
            and str(latest.get("assignment_node_id") or "").strip()
            and str(schedule.get("last_result_ticket_id") or "").strip()
            and str(schedule.get("last_result_node_id") or "").strip()
        ):
            return body
        time.sleep(0.5)
    return last_body


def main() -> int:
    args = parse_args()
    workspace_root = Path(args.root).resolve()
    artifacts_root = Path(args.artifacts_dir).resolve() / "schedule-trigger-idempotency"
    logs_root = Path(args.logs_dir).resolve() / "schedule-trigger-idempotency"
    if artifacts_root.exists():
        shutil.rmtree(artifacts_root, ignore_errors=True)
    if logs_root.exists():
        shutil.rmtree(logs_root, ignore_errors=True)
    artifacts_root.mkdir(parents=True, exist_ok=True)
    logs_root.mkdir(parents=True, exist_ok=True)
    api_dir = artifacts_root / "api"
    api_dir.mkdir(parents=True, exist_ok=True)

    agent_search_root = infer_agent_search_root(workspace_root)
    artifact_root = artifacts_root / "task-output"
    runtime_base = Path(os.getenv("TEST_TMP_DIR") or (artifacts_root / "runtime")).resolve()
    runtime_root, bootstrap_cfg = prepare_isolated_runtime_root(
        runtime_base / "schedule-trigger-idempotency",
        agent_search_root=agent_search_root,
        artifact_root=artifact_root,
    )
    base_url = f"http://{args.host}:{int(args.port)}"
    summary: dict[str, Any] = {
        "ok": False,
        "workspace_root": workspace_root.as_posix(),
        "runtime_root": runtime_root.as_posix(),
        "bootstrap_cfg": bootstrap_cfg,
    }

    with running_server(
        workspace_root,
        runtime_root,
        host=args.host,
        port=int(args.port),
        stdout_path=logs_root / "server.stdout.log",
        stderr_path=logs_root / "server.stderr.log",
    ):
        summary["healthz"] = wait_for_health(base_url)

        status, agents_payload = api_request(base_url, "GET", "/api/agents")
        assert_true(status == 200 and isinstance(agents_payload, dict) and agents_payload.get("ok"), "agents api unavailable")
        write_json(api_dir / "agents.json", agents_payload)
        chosen_agent, _receiver_agent = choose_agent(agents_payload)
        assigned_agent_id = str(chosen_agent.get("agent_name") or chosen_agent.get("agent_id") or "").strip()
        assert_true(assigned_agent_id != "", "assigned agent missing")
        summary["assigned_agent_id"] = assigned_agent_id

        execution_payload = {
            "execution_provider": "codex",
            "codex_command_path": "cmd.exe",
            "command_template": FAST_SUCCESS_COMMAND_TEMPLATE,
            "global_concurrency_limit": 1,
            "operator": "schedule-idempotency-acceptance",
        }
        status, execution_body = api_request(base_url, "POST", "/api/assignments/settings/execution", execution_payload)
        assert_true(status == 200 and isinstance(execution_body, dict) and execution_body.get("ok"), f"set execution settings failed: {execution_body}")
        write_json(api_dir / "assignment_execution_settings.json", execution_body)

        trigger_dt = datetime.now(BEIJING_TZ).replace(second=0, microsecond=0) + timedelta(minutes=1)
        trigger_at = trigger_dt.isoformat(timespec="seconds")
        schedule_payload = {
            "schedule_name": "定时幂等性验收",
            "enabled": True,
            "assigned_agent_id": assigned_agent_id,
            "launch_summary": "验证同一 trigger 不会重复建单。",
            "execution_checklist": "1) 同一分钟 scan 两次\n2) 只存在一个任务节点\n3) detail 状态对齐真实任务",
            "done_definition": "同一 trigger_instance_id 只对应一个 assignment node，且 detail 结果状态与最新 trigger 一致。",
            "priority": "P1",
            "expected_artifact": "schedule-trigger-idempotency-report",
            "delivery_mode": "none",
            "rule_sets": {
                "monthly": {"enabled": False},
                "weekly": {"enabled": False},
                "daily": {"enabled": False},
                "once": {"enabled": True, "date_times_text": trigger_at},
            },
            "operator": "schedule-idempotency-acceptance",
        }
        status, create_body = api_request(base_url, "POST", "/api/schedules", schedule_payload)
        assert_true(status == 200 and isinstance(create_body, dict) and create_body.get("ok"), f"create schedule failed: {create_body}")
        write_json(api_dir / "schedule_create.json", create_body)
        schedule_id = str(create_body.get("schedule_id") or "").strip()
        assert_true(schedule_id != "", "schedule_id missing")

        scan_payload = {
            "schedule_id": schedule_id,
            "now_at": trigger_at,
            "operator": "schedule-idempotency-acceptance",
        }
        status, scan_first = api_request(base_url, "POST", "/api/schedules/scan", scan_payload)
        assert_true(status == 200 and isinstance(scan_first, dict) and scan_first.get("ok"), f"first scan failed: {scan_first}")
        write_json(api_dir / "schedule_scan_first.json", scan_first)

        detail_after_first = _poll_schedule_detail(base_url, schedule_id)
        write_json(api_dir / "schedule_detail_after_first.json", detail_after_first)

        status, scan_second = api_request(base_url, "POST", "/api/schedules/scan", scan_payload)
        assert_true(status == 200 and isinstance(scan_second, dict) and scan_second.get("ok"), f"second scan failed: {scan_second}")
        write_json(api_dir / "schedule_scan_second.json", scan_second)

        detail_after_second = _poll_schedule_detail(base_url, schedule_id)
        write_json(api_dir / "schedule_detail_after_second.json", detail_after_second)

        recent = list(detail_after_second.get("recent_triggers") or [])
        latest = dict(recent[0] or {}) if recent else {}
        schedule = dict(detail_after_second.get("schedule") or {})
        trigger_instance_id = str(latest.get("trigger_instance_id") or "").strip()
        ticket_id = str(latest.get("assignment_ticket_id") or "").strip()
        node_id = str(latest.get("assignment_node_id") or "").strip()
        assert_true(trigger_instance_id != "", "trigger_instance_id missing after rescan")
        assert_true(ticket_id != "" and node_id != "", "assignment refs missing after rescan")

        graph_route = "/api/assignments/" + urllib.parse.quote(ticket_id) + "/graph"
        status, graph_body = api_request(base_url, "GET", graph_route)
        assert_true(status == 200 and isinstance(graph_body, dict) and graph_body.get("ok"), f"assignment graph failed: {graph_body}")
        write_json(api_dir / "assignment_graph.json", graph_body)
        matching_nodes = [
            node
            for node in list(graph_body.get("nodes") or [])
            if str(node.get("source_schedule_id") or "").strip() == schedule_id
            and str(node.get("trigger_instance_id") or "").strip() == trigger_instance_id
        ]
        assert_true(len(matching_nodes) == 1, f"expected exactly one matching node, got {len(matching_nodes)}")
        assert_true(str(matching_nodes[0].get("node_id") or "").strip() == node_id, "detail node_id should match graph node_id")
        assert_true(str(schedule.get("last_result_ticket_id") or "").strip() == ticket_id, "schedule last_result_ticket_id mismatch")
        assert_true(str(schedule.get("last_result_node_id") or "").strip() == node_id, "schedule last_result_node_id mismatch")
        assert_true(
            str(schedule.get("last_result_status") or "").strip().lower()
            == str(latest.get("result_status") or "").strip().lower(),
            "schedule last_result_status should match latest trigger result_status",
        )

        second_items = list(scan_second.get("items") or [])
        dedup_statuses = {str(item.get("status") or "").strip().lower() for item in second_items}
        assert_true(bool({"deduped", "deduped_resumed"} & dedup_statuses), f"second scan should dedupe existing trigger: {dedup_statuses}")

        summary.update(
            {
                "ok": True,
                "schedule_id": schedule_id,
                "trigger_instance_id": trigger_instance_id,
                "assignment_ticket_id": ticket_id,
                "assignment_node_id": node_id,
                "latest_result_status": str(latest.get("result_status") or "").strip(),
                "schedule_last_result_status": str(schedule.get("last_result_status") or "").strip(),
                "matching_node_count": len(matching_nodes),
                "second_scan_statuses": sorted(dedup_statuses),
            }
        )

    write_json(artifacts_root / "summary.json", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
