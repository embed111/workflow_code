#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import time
import urllib.parse
from pathlib import Path
from typing import Any

from run_acceptance_schedule_center_browser import (
    api_request,
    assert_true,
    infer_agent_search_root,
    prepare_isolated_runtime_root,
    running_server,
    wait_for_health,
    write_json,
)


FAST_SUCCESS_COMMAND_TEMPLATE = 'cmd.exe /c rem "{codex_path}" "{workspace_path}"'
WATCHDOG_TIMES_TEXT = ",".join(f"{hour:02d}:{minute:02d}" for hour in range(24) for minute in range(0, 60, 20))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Acceptance for assignment self-iteration schedule chaining.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8168)
    parser.add_argument(
        "--artifacts-dir",
        default=os.getenv("TEST_ARTIFACTS_DIR") or ".test/evidence",
    )
    parser.add_argument(
        "--logs-dir",
        default=os.getenv("TEST_LOG_DIR") or ".test/evidence",
    )
    return parser.parse_args()


def _poll_graph(base_url: str, ticket_id: str, *, timeout_seconds: float = 20.0) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    route = "/api/assignments/" + urllib.parse.quote(ticket_id) + "/graph"
    last_body: dict[str, Any] = {}
    while time.time() < deadline:
        status, body = api_request(base_url, "GET", route)
        assert_true(status == 200 and isinstance(body, dict) and body.get("ok"), f"assignment graph failed: {body}")
        last_body = body
        rows = list(body.get("nodes") or [])
        if any(str((row or {}).get("status") or "").strip().lower() in {"succeeded", "failed"} for row in rows):
            return body
        time.sleep(0.5)
    return last_body


def _poll_self_iteration_schedule(base_url: str, *, timeout_seconds: float = 20.0) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_body: dict[str, Any] = {}
    while time.time() < deadline:
        status, body = api_request(base_url, "GET", "/api/schedules")
        assert_true(status == 200 and isinstance(body, dict) and body.get("ok"), f"schedule list failed: {body}")
        last_body = body
        for item in list(body.get("items") or []):
            if str((item or {}).get("schedule_name") or "").strip() == "[持续迭代] workflow":
                return item
        time.sleep(0.5)
    raise AssertionError(f"self iteration schedule missing: {json.dumps(last_body, ensure_ascii=False)}")


def _poll_backup_schedule(base_url: str, *, timeout_seconds: float = 20.0) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_body: dict[str, Any] = {}
    while time.time() < deadline:
        status, body = api_request(base_url, "GET", "/api/schedules")
        assert_true(status == 200 and isinstance(body, dict) and body.get("ok"), f"schedule list failed: {body}")
        last_body = body
        for item in list(body.get("items") or []):
            if str((item or {}).get("expected_artifact") or "").strip() == "workflow-pm-wake-summary":
                return item
        time.sleep(0.5)
    raise AssertionError(f"backup schedule missing: {json.dumps(last_body, ensure_ascii=False)}")


def main() -> int:
    args = parse_args()
    workspace_root = Path(args.root).resolve()
    artifacts_root = Path(args.artifacts_dir).resolve() / "assignment-self-iteration-schedule"
    logs_root = Path(args.logs_dir).resolve() / "assignment-self-iteration-schedule"
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
        runtime_base / "assignment-self-iteration-schedule",
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

        execution_payload = {
            "execution_provider": "codex",
            "codex_command_path": "cmd.exe",
            "command_template": FAST_SUCCESS_COMMAND_TEMPLATE,
            "global_concurrency_limit": 1,
            "operator": "assignment-self-iter-acceptance",
        }
        status, execution_body = api_request(base_url, "POST", "/api/assignments/settings/execution", execution_payload)
        assert_true(status == 200 and isinstance(execution_body, dict) and execution_body.get("ok"), f"set execution settings failed: {execution_body}")
        write_json(api_dir / "assignment_execution_settings.json", execution_body)

        graph_payload = {
            "graph_name": "自迭代验收图",
            "source_workflow": "workflow-acceptance",
            "summary": "验证 assignment 完成后会自动挂下一轮自迭代计划。",
            "review_mode": "none",
            "external_request_id": "assignment-self-iter-acceptance",
            "operator": "assignment-self-iter-acceptance",
        }
        status, graph_body = api_request(base_url, "POST", "/api/assignments", graph_payload)
        assert_true(status == 200 and isinstance(graph_body, dict) and graph_body.get("ok"), f"create graph failed: {graph_body}")
        write_json(api_dir / "assignment_graph_create.json", graph_body)
        ticket_id = str(graph_body.get("ticket_id") or "").strip()
        assert_true(ticket_id != "", "ticket_id missing")

        node_payload = {
            "node_name": "workflow 自迭代验收任务",
            "assigned_agent_id": "workflow",
            "priority": "P1",
            "node_goal": "完成后应自动给 workflow 挂下一轮自迭代计划。",
            "expected_artifact": "assignment-self-iter-report.md",
            "delivery_mode": "none",
            "operator": "assignment-self-iter-acceptance",
        }
        status, node_body = api_request(base_url, "POST", f"/api/assignments/{urllib.parse.quote(ticket_id)}/nodes", node_payload)
        assert_true(status == 200 and isinstance(node_body, dict) and node_body.get("ok"), f"create node failed: {node_body}")
        write_json(api_dir / "assignment_node_create.json", node_body)
        node_id = str((node_body.get("node") or {}).get("node_id") or "").strip()
        assert_true(node_id != "", "node_id missing")

        status, resume_body = api_request(
            base_url,
            "POST",
            f"/api/assignments/{urllib.parse.quote(ticket_id)}/resume",
            {"operator": "assignment-self-iter-acceptance"},
        )
        assert_true(status == 200 and isinstance(resume_body, dict) and resume_body.get("ok"), f"resume failed: {resume_body}")
        write_json(api_dir / "assignment_resume.json", resume_body)

        status, dispatch_body = api_request(
            base_url,
            "POST",
            f"/api/assignments/{urllib.parse.quote(ticket_id)}/dispatch-next",
            {"operator": "assignment-self-iter-acceptance"},
        )
        assert_true(status == 200 and isinstance(dispatch_body, dict) and dispatch_body.get("ok"), f"dispatch failed: {dispatch_body}")
        write_json(api_dir / "assignment_dispatch.json", dispatch_body)

        graph_after = _poll_graph(base_url, ticket_id)
        write_json(api_dir / "assignment_graph_after.json", graph_after)
        nodes = list(graph_after.get("nodes") or [])
        original = next((item for item in nodes if str((item or {}).get("node_id") or "").strip() == node_id), {})
        final_status = str(original.get("status") or "").strip().lower()
        assert_true(final_status in {"succeeded", "failed"}, f"original node not completed: {original}")

        schedule_item = _poll_self_iteration_schedule(base_url)
        write_json(api_dir / "self_iteration_schedule.json", schedule_item)
        assert_true(str(schedule_item.get("assigned_agent_id") or "").strip() == "workflow", f"unexpected self-iter agent: {schedule_item}")
        assert_true(bool(str(schedule_item.get("next_trigger_at") or "").strip()), f"next_trigger_at missing: {schedule_item}")
        assert_true(
            str(schedule_item.get("expected_artifact") or "").strip() == "continuous-improvement-report.md",
            f"unexpected expected_artifact: {schedule_item}",
        )
        launch_summary = str(schedule_item.get("launch_summary") or "").strip()
        execution_checklist = str(schedule_item.get("execution_checklist") or "").strip()
        done_definition = str(schedule_item.get("done_definition") or "").strip()
        assert_true("版本推进计划.md" in launch_summary, f"launch_summary missing version plan path: {schedule_item}")
        assert_true("需求详情-pm持续唤醒与清醒维持.md" in launch_summary, f"launch_summary missing wake requirement path: {schedule_item}")
        assert_true("workflow_devmate" in execution_checklist, f"execution_checklist missing teammate routing: {schedule_item}")
        assert_true("版本计划" in done_definition, f"done_definition missing version plan contract: {schedule_item}")

        backup_schedule = _poll_backup_schedule(base_url)
        write_json(api_dir / "backup_schedule.json", backup_schedule)
        backup_launch_summary = str(backup_schedule.get("launch_summary") or "").strip()
        backup_execution_checklist = str(backup_schedule.get("execution_checklist") or "").strip()
        backup_editor_inputs = backup_schedule.get("editor_rule_inputs") if isinstance(backup_schedule.get("editor_rule_inputs"), dict) else {}
        backup_daily = backup_editor_inputs.get("daily") if isinstance(backup_editor_inputs.get("daily"), dict) else {}
        assert_true(str(backup_schedule.get("assigned_agent_id") or "").strip() == "workflow", f"unexpected backup agent: {backup_schedule}")
        assert_true(bool(str(backup_schedule.get("next_trigger_at") or "").strip()), f"backup next_trigger_at missing: {backup_schedule}")
        assert_true("20 分钟真定时看门狗" in backup_launch_summary, f"backup launch_summary missing watchdog wording: {backup_schedule}")
        assert_true("主线健康" in backup_execution_checklist, f"backup execution_checklist missing healthy-mainline branch: {backup_schedule}")
        assert_true(bool(backup_daily.get("enabled")), f"backup daily rule not enabled: {backup_schedule}")
        assert_true(str(backup_daily.get("times_text") or "").strip() == WATCHDOG_TIMES_TEXT, f"backup daily times mismatch: {backup_schedule}")

        summary.update(
            {
                "ok": True,
                "ticket_id": ticket_id,
                "node_id": node_id,
                "original_final_status": final_status,
                "self_iteration_schedule_id": str(schedule_item.get("schedule_id") or "").strip(),
                "self_iteration_next_trigger_at": str(schedule_item.get("next_trigger_at") or "").strip(),
                "backup_schedule_id": str(backup_schedule.get("schedule_id") or "").strip(),
                "backup_next_trigger_at": str(backup_schedule.get("next_trigger_at") or "").strip(),
            }
        )

    write_json(artifacts_root / "summary.json", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
