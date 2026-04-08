#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


STUB_SCRIPT = r"""
import json
import os
import sys
from pathlib import Path

mode = sys.argv[1]
flag_path = Path(sys.argv[2])
attempt = 1
if flag_path.exists():
    try:
        attempt = int(flag_path.read_text(encoding="utf-8").strip() or "1") + 1
    except Exception:
        attempt = 2
flag_path.write_text(str(attempt), encoding="utf-8")

if attempt == 1:
    if mode == "startup_only":
        print(json.dumps({"type": "thread.started"}), flush=True)
        print(json.dumps({"type": "turn.started"}), flush=True)
        raise SystemExit(1)
    if mode == "interrupt":
        sys.stderr.write("^C\n")
        sys.stderr.flush()
        raise SystemExit(1)
    if mode == "stream_disconnect":
        print(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "agent_message",
                        "text": "我先补齐读链，再继续核对 runtime-upgrade 和 schedules。",
                    },
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        print(
            json.dumps(
                {
                    "type": "error",
                    "message": "Reconnecting... 1/5 (stream disconnected before completion: simulated disconnect)",
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        print(
            json.dumps(
                {
                    "type": "turn.failed",
                    "error": {
                        "message": "stream disconnected before completion: simulated disconnect",
                    },
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        raise SystemExit(1)
    raise SystemExit(2)

payload = {
    "result_summary": f"{mode} retry succeeded",
    "artifact_label": f"{mode}.md",
    "artifact_markdown": f"{mode} retry succeeded",
    "artifact_files": [],
    "warnings": [],
}
print(
    json.dumps(
        {
            "type": "item.completed",
            "item": {
                "type": "agent_message",
                "text": json.dumps(payload, ensure_ascii=False),
            },
        },
        ensure_ascii=False,
    ),
    flush=True,
)
"""


def _setup_runtime_root(root: Path) -> None:
    if root.exists():
        import shutil

        shutil.rmtree(root, ignore_errors=True)
    (root / "state").mkdir(parents=True, exist_ok=True)
    agent_dir = root / "workflow"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENTS.md").write_text(
        "\n".join(
            [
                "# workflow",
                "",
                "## 角色定位",
                "你是 workflow 验收探针里的最小执行 agent。",
                "",
                "## 会话目标",
                "只输出结构化 JSON 结果。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "state" / "runtime-config.json").write_text(
        json.dumps(
            {
                "show_test_data": True,
                "agent_search_root": str(root.resolve()),
                "artifact_root": str((root / "artifacts-root").resolve()),
                "task_artifact_root": str((root / "artifacts-root").resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _create_running_node(ws, root: Path, *, graph_name: str, node_name: str) -> tuple[str, str]:
    cfg = type(
        "Cfg",
        (),
        {
            "root": root,
            "agent_search_root": root,
            "show_test_data": True,
        },
    )()
    graph = ws.create_assignment_graph(
        cfg,
        {
            "graph_name": graph_name,
            "source_workflow": "workflow-ui",
            "summary": graph_name,
            "review_mode": "none",
            "external_request_id": graph_name,
            "operator": "test",
        },
    )
    ticket_id = str(graph.get("ticket_id") or "").strip()
    created = ws.create_assignment_node(
        cfg,
        ticket_id,
        {
            "node_name": node_name,
            "assigned_agent_id": "workflow",
            "priority": "P1",
            "node_goal": node_name,
            "expected_artifact": "retry.md",
            "delivery_mode": "none",
            "operator": "test",
        },
        include_test_data=True,
    )
    node_id = str((created.get("node") or {}).get("node_id") or "").strip()
    assert ticket_id and node_id
    node_path = ws._assignment_node_record_path(root, ticket_id, node_id)
    node_payload = ws._assignment_read_json(node_path)
    node_payload["status"] = "running"
    node_payload["status_text"] = "进行中"
    node_payload["updated_at"] = ws.iso_ts(ws.now_local())
    ws._assignment_write_json(node_path, node_payload)
    return ticket_id, node_id


def _run_retry_case(ws, root: Path, *, mode: str) -> dict[str, object]:
    ticket_id, node_id = _create_running_node(
        ws,
        root,
        graph_name=f"assignment-transient-retry-{mode}",
        node_name=f"transient retry {mode}",
    )
    run_id = f"arun-test-transient-retry-{mode}"
    files = ws._assignment_run_file_paths(root, ticket_id, run_id)
    files["trace_dir"].mkdir(parents=True, exist_ok=True)
    workspace = root / "workspace" / mode
    workspace.mkdir(parents=True, exist_ok=True)
    stub_path = workspace / "stub_assignment_retry.py"
    stub_path.write_text(STUB_SCRIPT.strip() + "\n", encoding="utf-8")
    flag_path = workspace / f"{mode}.attempt"
    now_text = ws.iso_ts(ws.now_local())
    run_record = ws._assignment_build_run_record(
        run_id=run_id,
        ticket_id=ticket_id,
        node_id=node_id,
        provider="codex",
        workspace_path=workspace.as_posix(),
        status="starting",
        command_summary=f"transient retry {mode}",
        prompt_ref=files["prompt"].as_posix(),
        stdout_ref=files["stdout"].as_posix(),
        stderr_ref=files["stderr"].as_posix(),
        result_ref=files["result"].as_posix(),
        latest_event="已创建运行批次，等待 provider 启动。",
        latest_event_at=now_text,
        exit_code=0,
        started_at=now_text,
        finished_at="",
        created_at=now_text,
        updated_at=now_text,
        provider_pid=0,
    )
    ws._assignment_write_run_record(root, ticket_id=ticket_id, run_record=run_record)
    ws._write_assignment_run_text(files["prompt"], f"transient retry {mode}")
    ws._assignment_execution_worker(
        root,
        run_id=run_id,
        ticket_id=ticket_id,
        node_id=node_id,
        workspace_path=workspace,
        command=[sys.executable, stub_path.as_posix(), mode, flag_path.as_posix()],
        command_summary=f"transient retry {mode}",
        prompt_text="transient retry prompt",
    )
    refreshed_run = ws._assignment_load_run_record(root, ticket_id=ticket_id, run_id=run_id)
    refreshed_node = ws._assignment_read_json(ws._assignment_node_record_path(root, ticket_id, node_id))
    result_payload = json.loads(files["result"].read_text(encoding="utf-8"))
    events_text = files["events"].read_text(encoding="utf-8")
    artifact_paths = list(refreshed_node.get("artifact_paths") or [])
    assert str(refreshed_run.get("status") or "").strip().lower() == "succeeded", refreshed_run
    assert str(refreshed_node.get("status") or "").strip().lower() == "succeeded", refreshed_node
    assert str(result_payload.get("result_summary") or "").strip() == f"{mode} retry succeeded", result_payload
    assert '"event_type": "provider_retry"' in events_text, events_text
    assert flag_path.read_text(encoding="utf-8").strip() == "2", flag_path.read_text(encoding="utf-8")
    assert artifact_paths, refreshed_node
    return {
        "mode": mode,
        "ticket_id": ticket_id,
        "node_id": node_id,
        "run_id": run_id,
        "artifact_paths": artifact_paths,
        "latest_event": refreshed_run.get("latest_event"),
    }


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.bootstrap import web_server_runtime as ws

    root = Path.cwd() / ".test" / "runtime-assignment-transient-startup-retry"
    _setup_runtime_root(root)
    startup_only = _run_retry_case(ws, root, mode="startup_only")
    interrupt = _run_retry_case(ws, root, mode="interrupt")
    stream_disconnect = _run_retry_case(ws, root, mode="stream_disconnect")
    print(
        json.dumps(
            {
                "ok": True,
                "cases": [startup_only, interrupt, stream_disconnect],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
