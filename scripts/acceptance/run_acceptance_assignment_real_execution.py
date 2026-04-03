#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode


GOOD_CODEX_COMMAND_TEMPLATE = (
    'cmd.exe /c ping -n 4 127.0.0.1 >nul && '
    '"{codex_path}" exec --dangerously-bypass-approvals-and-sandbox --json --skip-git-repo-check '
    '--add-dir "{workspace_path}" -C "{workspace_path}" -'
)
BAD_CODEX_COMMAND_TEMPLATE = (
    '"{codex_path}" exec --dangerously-bypass-approvals-and-sandbox --json --skip-git-repo-check '
    '--add-dir "{workspace_path}" -C "{workspace_path}" -'
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Acceptance for assignment real execution.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8138)
    parser.add_argument("--artifacts-dir", default=os.getenv("TEST_ARTIFACTS_DIR") or ".test/evidence")
    parser.add_argument("--logs-dir", default=os.getenv("TEST_LOG_DIR") or ".test/evidence")
    return parser.parse_args()


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json_response(response: urllib.request.addinfourl) -> dict[str, Any]:
    raw = response.read()
    if not raw:
        return {}
    payload = json.loads(raw.decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def api_request(base_url: str, method: str, route: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
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
        with urllib.request.urlopen(request, timeout=30) as response:
            content_type = str(response.headers.get("Content-Type") or "")
            if "application/json" in content_type:
                return int(response.status), read_json_response(response)
            return int(response.status), response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        content_type = str(exc.headers.get("Content-Type") or "")
        if "application/json" in content_type:
            return int(exc.code), read_json_response(exc)
        return int(exc.code), exc.read().decode("utf-8")


def wait_for_health(base_url: str, timeout_s: float = 30.0) -> dict[str, Any]:
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


def find_edge() -> Path:
    candidates = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    for path in candidates:
        if path.exists() and path.is_file():
            return path
    raise RuntimeError("msedge not found")


def edge_shot(
    edge_path: Path,
    url: str,
    shot_path: Path,
    *,
    profile_dir: Path,
    width: int = 1680,
    height: int = 1200,
    budget_ms: int = 24000,
) -> None:
    shot_path.parent.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(edge_path),
        "--headless=new",
        "--disable-gpu",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-sync",
        "--no-first-run",
        "--no-default-browser-check",
        f"--user-data-dir={profile_dir.as_posix()}",
        f"--window-size={width},{height}",
        f"--virtual-time-budget={max(1000, int(budget_ms))}",
        f"--screenshot={shot_path.as_posix()}",
        url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=180)
    if proc.returncode != 0:
        raise RuntimeError(f"edge screenshot failed: {proc.stderr}")


def edge_dom(
    edge_path: Path,
    url: str,
    *,
    profile_dir: Path,
    width: int = 1680,
    height: int = 1200,
    budget_ms: int = 24000,
) -> str:
    profile_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(edge_path),
        "--headless=new",
        "--disable-gpu",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-sync",
        "--no-first-run",
        "--no-default-browser-check",
        f"--user-data-dir={profile_dir.as_posix()}",
        f"--window-size={width},{height}",
        f"--virtual-time-budget={max(1000, int(budget_ms))}",
        "--dump-dom",
        url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=180)
    if proc.returncode != 0:
        raise RuntimeError(f"edge dump-dom failed: {proc.stderr}")
    return proc.stdout


def parse_assignment_probe(dom_text: str) -> dict[str, Any]:
    marker = "assignmentCenterProbeOutput"
    start = dom_text.find(marker)
    if start < 0:
        raise RuntimeError("assignmentCenterProbeOutput_not_found")
    pre_open = dom_text.rfind("<pre", 0, start)
    pre_close = dom_text.find(">", start)
    end = dom_text.find("</pre>", pre_close)
    if pre_open < 0 or pre_close < 0 or end < 0:
        raise RuntimeError("assignmentCenterProbeOutput_malformed")
    raw = html.unescape(dom_text[pre_close + 1 : end]).strip()
    if not raw:
        raise RuntimeError("assignmentCenterProbeOutput_empty")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError("assignmentCenterProbeOutput_not_dict")
    return payload


def assignment_probe_url(base_url: str, case_id: str, extra: dict[str, str] | None = None) -> str:
    query: dict[str, str] = {
        "assignment_probe": "1",
        "assignment_probe_case": str(case_id),
        "_ts": str(int(time.time() * 1000)),
    }
    if extra:
        for key, value in extra.items():
            query[str(key)] = str(value)
    return base_url.rstrip("/") + "/?" + urlencode(query)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def capture_probe(
    edge_path: Path,
    base_url: str,
    evidence_root: Path,
    *,
    name: str,
    case_id: str,
    extra: dict[str, str] | None = None,
) -> tuple[str, str, dict[str, Any]]:
    url = assignment_probe_url(base_url, case_id, extra)
    shot_path = evidence_root / "screenshots" / f"{name}.png"
    probe_path = evidence_root / "screenshots" / f"{name}.probe.json"
    profile_dir = evidence_root / "edge-profile" / name
    edge_shot(edge_path, url, shot_path, profile_dir=profile_dir)
    probe = parse_assignment_probe(edge_dom(edge_path, url, profile_dir=profile_dir))
    write_json(probe_path, probe)
    return shot_path.as_posix(), probe_path.as_posix(), probe


def capture_probe_with_retry(
    edge_path: Path,
    base_url: str,
    evidence_root: Path,
    *,
    name: str,
    case_id: str,
    extra: dict[str, str] | None = None,
    attempts: int = 3,
    retry_delay_s: float = 1.0,
) -> tuple[str, str, dict[str, Any]]:
    last_error: Exception | None = None
    last_result: tuple[str, str, dict[str, Any]] | None = None
    for attempt in range(max(1, attempts)):
        try:
            result = capture_probe(
                edge_path,
                base_url,
                evidence_root,
                name=name,
                case_id=case_id,
                extra=extra,
            )
            last_result = result
            if bool((result[2] or {}).get("pass")):
                return result
        except Exception as exc:
            last_error = exc
        if attempt + 1 < max(1, attempts):
            time.sleep(retry_delay_s)
    if last_result is not None:
        return last_result
    assert last_error is not None
    raise last_error


def wait_for_status_detail(
    base_url: str,
    *,
    ticket_id: str,
    node_id: str,
    timeout_s: float,
    predicate,
) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last_payload: dict[str, Any] = {}
    last_error = ""
    route = f"/api/assignments/{ticket_id}/status-detail?node_id={node_id}&include_test_data=0"
    while time.time() < deadline:
        try:
            status, body = api_request(base_url, "GET", route)
            assert_true(status == 200 and isinstance(body, dict) and body.get("ok"), f"status detail unavailable: {body}")
            last_payload = body
            last_error = ""
            if predicate(body):
                return body
        except Exception as exc:
            last_error = str(exc)
        time.sleep(0.8)
    detail = json.dumps(last_payload, ensure_ascii=False)[:4000] if last_payload else last_error
    raise RuntimeError(f"status detail wait timeout: {detail}")


def prepare_runtime_root(evidence_root: Path) -> Path:
    runtime_root = evidence_root.resolve()
    state_dir = runtime_root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "runtime-config.json").write_text(
        json.dumps({"show_test_data": False}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return runtime_root


def prepare_agent_root(evidence_root: Path) -> Path:
    agent_root = evidence_root / "agent-root"
    (agent_root / "workflow").mkdir(parents=True, exist_ok=True)
    worker_dir = agent_root / "mini-worker"
    worker_dir.mkdir(parents=True, exist_ok=True)
    (worker_dir / "AGENTS.md").write_text(
        "\n".join(
            [
                "# Mini Worker",
                "",
                "- Keep all work inside the current directory.",
                "- Do not scan unrelated files or parent directories.",
                "- If the task requests a file, write only `report.md`.",
                "- Return only the JSON object required by the scheduler prompt.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (worker_dir / "README.md").write_text(
        "# Mini Worker Workspace\n\nUse this workspace for assignment real execution acceptance.\n",
        encoding="utf-8",
    )
    return agent_root


def render_report(
    *,
    report_path: Path,
    evidence_root: Path,
    summary: dict[str, Any],
) -> None:
    screenshots = summary.get("screenshots") or {}
    api_files = summary.get("api_files") or {}
    files = summary.get("run_files") or {}
    run_ids = summary.get("run_ids") or {}
    lines = [
        "# Assignment Real Execution Acceptance",
        "",
        f"- generated_at: {iso_now()}",
        f"- evidence_root: {evidence_root.as_posix()}",
        f"- runtime_root: {str(summary.get('runtime_root') or '')}",
        f"- agent_search_root: {str(summary.get('agent_search_root') or '')}",
        "",
        "## Screenshots",
        "",
        f"- task center main view: {screenshots.get('success_detail', {}).get('image', '')}",
        f"- settings page: {screenshots.get('settings', {}).get('image', '')}",
        f"- running execution chain: {screenshots.get('running_detail', {}).get('image', '')}",
        f"- failed execution chain: {screenshots.get('failed_detail', {}).get('image', '')}",
        "",
        "## Execution Evidence",
        "",
        f"- failed run_id: {run_ids.get('failed', '')}",
        f"- rerun run_id: {run_ids.get('success', '')}",
        f"- prompt_ref: {files.get('prompt_ref', '')}",
        f"- stdout_ref: {files.get('stdout_ref', '')}",
        f"- stderr_ref: {files.get('stderr_ref', '')}",
        f"- result_ref: {files.get('result_ref', '')}",
        f"- workspace_report: {files.get('workspace_report', '')}",
        f"- delivered_artifact: {files.get('delivered_artifact', '')}",
        f"- task_structure_guide: {files.get('task_structure_guide', '')}",
        f"- root_structure_guide: {files.get('root_structure_guide', '')}",
        "",
        "## Behavior Verification",
        "",
        f"- failure blocked downstream: {summary.get('failure_blocked_downstream', False)}",
        f"- rerun created new run_id: {summary.get('rerun_new_run_id', False)}",
        f"- success auto wrote back result_ref: {summary.get('success_auto_writeback', False)}",
        f"- success auto delivered artifact: {summary.get('success_auto_delivery', False)}",
        f"- downstream released after success: {summary.get('downstream_released', False)}",
        "",
        "## API Files",
        "",
        f"- agents: {api_files.get('agents', '')}",
        f"- training_agents: {api_files.get('training_agents', '')}",
        f"- settings_bad: {api_files.get('settings_bad', '')}",
        f"- dispatch_failed: {api_files.get('dispatch_failed', '')}",
        f"- status_failed: {api_files.get('status_failed', '')}",
        f"- settings_good: {api_files.get('settings_good', '')}",
        f"- rerun: {api_files.get('rerun', '')}",
        f"- dispatch_rerun: {api_files.get('dispatch_rerun', '')}",
        f"- status_running: {api_files.get('status_running', '')}",
        f"- status_success: {api_files.get('status_success', '')}",
        "",
        "## Code Locations",
        "",
        "- provider abstraction / Codex execution: src/workflow_app/server/services/assignment_service.py",
        "- execution settings API: src/workflow_app/server/api/assignments.py",
        "- task detail execution chain UI: src/workflow_app/web_client/assignment_center.js",
        "- settings task execution UI: src/workflow_app/web_client/policy_confirm_and_interactions.js",
        "",
        "## Risk Notes",
        "",
        "- realtime mode prefers SSE event stream; `poll_interval_ms` only acts as disconnect fallback.",
        "- stdout and stderr are rendered as full text blocks; no segmented lazy loading is used in this version.",
        "",
    ]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    repo_root = Path(args.root).resolve()
    artifacts_dir = Path(args.artifacts_dir).resolve()
    logs_dir = Path(args.logs_dir).resolve()
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    evidence_root = artifacts_dir / f"assignment-real-exec-{stamp}"
    log_root = logs_dir / f"assignment-real-exec-{stamp}"
    api_dir = evidence_root / "api"
    shots_dir = evidence_root / "screenshots"
    api_dir.mkdir(parents=True, exist_ok=True)
    shots_dir.mkdir(parents=True, exist_ok=True)
    log_root.mkdir(parents=True, exist_ok=True)
    runtime_base = Path(os.getenv("TEST_TMP_DIR") or (repo_root / ".test" / "runtime")).resolve()
    runtime_root = prepare_runtime_root(runtime_base / f"assignment-real-exec-{stamp}")
    agent_root = prepare_agent_root(evidence_root)
    base_url = f"http://{args.host}:{args.port}"
    edge_path = find_edge()
    server_stdout = log_root / "server.stdout.log"
    server_stderr = log_root / "server.stderr.log"
    report_path = evidence_root / "acceptance-report.md"

    stdout_handle = server_stdout.open("wb")
    stderr_handle = server_stderr.open("wb")
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
        cwd=str(repo_root),
        stdout=stdout_handle,
        stderr=stderr_handle,
    )

    evidence: dict[str, Any] = {
        "repo_root": str(repo_root),
        "runtime_root": str(runtime_root),
        "agent_search_root": str(agent_root),
        "base_url": base_url,
        "edge_path": str(edge_path),
        "api_files": {},
        "screenshots": {},
        "run_ids": {},
        "run_files": {},
    }

    def record_api(name: str, method: str, path: str, payload: dict[str, Any] | None, status: int, body: Any) -> None:
        file_path = api_dir / f"{name}.json"
        write_json(
            file_path,
            {
                "request": {"method": method, "path": path, "payload": payload},
                "response": {"status": status, "body": body},
            },
        )
        evidence["api_files"][name] = file_path.as_posix()

    try:
        evidence["healthz"] = wait_for_health(base_url)

        set_root_payload = {"agent_search_root": agent_root.as_posix()}
        status, body = api_request(base_url, "POST", "/api/config/agent-search-root", set_root_payload)
        assert_true(status == 200 and isinstance(body, dict) and body.get("ok"), f"set agent root failed: {body}")
        record_api("set_agent_root", "POST", "/api/config/agent-search-root", set_root_payload, status, body)

        set_artifact_root_payload = {"artifact_root": (evidence_root / "task-output").as_posix()}
        status, body = api_request(base_url, "POST", "/api/config/artifact-root", set_artifact_root_payload)
        assert_true(status == 200 and isinstance(body, dict) and body.get("ok"), f"set artifact root failed: {body}")
        record_api(
            "set_task_artifact_root",
            "POST",
            "/api/config/artifact-root",
            set_artifact_root_payload,
            status,
            body,
        )

        status, agents_payload = api_request(base_url, "GET", "/api/agents")
        assert_true(status == 200 and isinstance(agents_payload, dict) and agents_payload.get("ok"), "agents api unavailable")
        record_api("agents", "GET", "/api/agents", None, status, agents_payload)
        evidence["task_artifact_root"] = str(agents_payload.get("task_artifact_root") or agents_payload.get("artifact_root") or "")

        status, training_agents = api_request(base_url, "GET", "/api/training/agents")
        assert_true(status == 200 and isinstance(training_agents, dict) and training_agents.get("ok"), "training agents unavailable")
        record_api("training_agents", "GET", "/api/training/agents", None, status, training_agents)
        items = list(training_agents.get("items") or [])
        assert_true(bool(items), "no training agents discovered")
        agent_id = str((items[0] or {}).get("agent_id") or "").strip()
        assert_true(agent_id == "mini-worker", f"unexpected agent id: {agent_id}")

        bad_settings_payload = {
            "execution_provider": "codex",
            "codex_command_path": (evidence_root / "missing-codex.cmd").as_posix(),
            "command_template": BAD_CODEX_COMMAND_TEMPLATE,
            "global_concurrency_limit": 1,
            "operator": "assignment-real-exec-acceptance",
        }
        status, body = api_request(base_url, "POST", "/api/assignments/settings/execution", bad_settings_payload)
        assert_true(status == 200 and isinstance(body, dict) and body.get("ok"), f"bad settings update failed: {body}")
        record_api("settings_bad", "POST", "/api/assignments/settings/execution", bad_settings_payload, status, body)

        create_graph_payload = {
            "graph_name": "assignment-real-exec-acceptance",
            "source_workflow": "assignment-real-exec-acceptance",
            "summary": "real execution acceptance graph",
            "review_mode": "none",
            "external_request_id": f"assignment-real-exec-{stamp}",
            "operator": "assignment-real-exec-acceptance",
        }
        status, body = api_request(base_url, "POST", "/api/assignments", create_graph_payload)
        assert_true(status == 200 and isinstance(body, dict) and body.get("ok"), f"create graph failed: {body}")
        record_api("create_graph", "POST", "/api/assignments", create_graph_payload, status, body)
        ticket_id = str(body.get("ticket_id") or "").strip()
        assert_true(ticket_id, "ticket_id missing")
        evidence["ticket_id"] = ticket_id

        create_node_primary = {
            "node_name": "primary-task",
            "assigned_agent_id": agent_id,
            "priority": "P0",
            "node_goal": "Write report.md with the text real execution success, then return the required JSON only.",
            "expected_artifact": "primary-report",
            "delivery_mode": "none",
            "operator": "assignment-real-exec-acceptance",
        }
        status, body = api_request(base_url, "POST", f"/api/assignments/{ticket_id}/nodes", create_node_primary)
        assert_true(status == 200 and isinstance(body, dict) and body.get("ok"), f"create primary node failed: {body}")
        record_api("create_node_primary", "POST", f"/api/assignments/{ticket_id}/nodes", create_node_primary, status, body)
        primary_node_id = str(((body.get("node") or {}).get("node_id")) or "").strip()
        assert_true(primary_node_id, "primary node id missing")

        create_node_downstream = {
            "node_name": "downstream-task",
            "assigned_agent_id": agent_id,
            "priority": "P1",
            "node_goal": "Use the upstream result and return a short confirmation in the required JSON only.",
            "expected_artifact": "downstream-report",
            "delivery_mode": "none",
            "upstream_node_ids": [primary_node_id],
            "operator": "assignment-real-exec-acceptance",
        }
        status, body = api_request(base_url, "POST", f"/api/assignments/{ticket_id}/nodes", create_node_downstream)
        assert_true(status == 200 and isinstance(body, dict) and body.get("ok"), f"create downstream node failed: {body}")
        record_api("create_node_downstream", "POST", f"/api/assignments/{ticket_id}/nodes", create_node_downstream, status, body)
        downstream_node_id = str(((body.get("node") or {}).get("node_id")) or "").strip()
        assert_true(downstream_node_id, "downstream node id missing")
        evidence["node_ids"] = {"primary": primary_node_id, "downstream": downstream_node_id}

        resume_payload = {"operator": "assignment-real-exec-acceptance"}
        status, body = api_request(base_url, "POST", f"/api/assignments/{ticket_id}/resume", resume_payload)
        assert_true(status == 200 and isinstance(body, dict) and body.get("ok"), f"resume failed: {body}")
        record_api("resume", "POST", f"/api/assignments/{ticket_id}/resume", resume_payload, status, body)

        dispatch_payload = {"operator": "assignment-real-exec-acceptance"}
        status, body = api_request(base_url, "POST", f"/api/assignments/{ticket_id}/dispatch-next", dispatch_payload)
        assert_true(status == 200 and isinstance(body, dict) and body.get("ok"), f"dispatch failed: {body}")
        record_api("dispatch_failed", "POST", f"/api/assignments/{ticket_id}/dispatch-next", dispatch_payload, status, body)

        failed_detail = wait_for_status_detail(
            base_url,
            ticket_id=ticket_id,
            node_id=primary_node_id,
            timeout_s=30,
            predicate=lambda payload: str((((payload.get("execution_chain") or {}).get("latest_run") or {}).get("status") or "")).lower() == "failed",
        )
        write_json(api_dir / "status_failed.json", failed_detail)
        evidence["api_files"]["status_failed"] = (api_dir / "status_failed.json").as_posix()
        failed_run = ((failed_detail.get("execution_chain") or {}).get("latest_run") or {})
        failed_run_id = str(failed_run.get("run_id") or "").strip()
        assert_true(failed_run_id, "failed run_id missing")
        evidence["run_ids"]["failed"] = failed_run_id
        failed_downstream = list(((failed_detail.get("selected_node") or {}).get("downstream_nodes") or []))
        evidence["failure_blocked_downstream"] = any(
            str((item or {}).get("node_id") or "").strip() == downstream_node_id
            and str((item or {}).get("status") or "").strip().lower() == "blocked"
            for item in failed_downstream
        )
        assert_true(evidence["failure_blocked_downstream"], "downstream node was not blocked after failure")

        shot, probe_file, probe = capture_probe_with_retry(
            edge_path,
            base_url,
            evidence_root,
            name="failed_detail",
            case_id="failed_detail",
            extra={
                "assignment_probe_ticket": ticket_id,
                "assignment_probe_node": primary_node_id,
                "assignment_probe_delay_ms": "1200",
            },
        )
        assert_true(bool(probe.get("pass")), f"failed_detail probe failed: {probe}")
        evidence["screenshots"]["failed_detail"] = {"image": shot, "probe": probe_file, "result": probe}

        good_settings_payload = {
            "execution_provider": "codex",
            "codex_command_path": r"C:/Users/think/AppData/Roaming/npm/codex.cmd",
            "command_template": GOOD_CODEX_COMMAND_TEMPLATE,
            "global_concurrency_limit": 1,
            "operator": "assignment-real-exec-acceptance",
        }
        status, body = api_request(base_url, "POST", "/api/assignments/settings/execution", good_settings_payload)
        assert_true(status == 200 and isinstance(body, dict) and body.get("ok"), f"good settings update failed: {body}")
        record_api("settings_good", "POST", "/api/assignments/settings/execution", good_settings_payload, status, body)

        shot, probe_file, probe = capture_probe_with_retry(
            edge_path,
            base_url,
            evidence_root,
            name="settings",
            case_id="settings",
            extra={"assignment_probe_delay_ms": "900"},
        )
        assert_true(bool(probe.get("pass")), f"settings probe failed: {probe}")
        evidence["screenshots"]["settings"] = {"image": shot, "probe": probe_file, "result": probe}

        rerun_payload = {
            "operator": "assignment-real-exec-acceptance",
            "reason": "retry with valid codex",
        }
        status, body = api_request(
            base_url,
            "POST",
            f"/api/assignments/{ticket_id}/nodes/{primary_node_id}/rerun",
            rerun_payload,
        )
        assert_true(status == 200 and isinstance(body, dict) and body.get("ok"), f"rerun failed: {body}")
        record_api("rerun", "POST", f"/api/assignments/{ticket_id}/nodes/{primary_node_id}/rerun", rerun_payload, status, body)

        status, body = api_request(base_url, "POST", f"/api/assignments/{ticket_id}/dispatch-next", dispatch_payload)
        assert_true(status == 200 and isinstance(body, dict) and body.get("ok"), f"dispatch rerun failed: {body}")
        record_api("dispatch_rerun", "POST", f"/api/assignments/{ticket_id}/dispatch-next", dispatch_payload, status, body)

        running_detail = wait_for_status_detail(
            base_url,
            ticket_id=ticket_id,
            node_id=primary_node_id,
            timeout_s=60,
            predicate=lambda payload: (
                str((((payload.get("execution_chain") or {}).get("latest_run") or {}).get("status") or "")).lower() in {"starting", "running"}
                and int((((payload.get("execution_chain") or {}).get("latest_run") or {}).get("event_count") or 0)) >= 4
            ),
        )
        write_json(api_dir / "status_running.json", running_detail)
        evidence["api_files"]["status_running"] = (api_dir / "status_running.json").as_posix()
        running_run = ((running_detail.get("execution_chain") or {}).get("latest_run") or {})
        running_run_id = str(running_run.get("run_id") or "").strip()
        assert_true(running_run_id, "running run_id missing")
        assert_true(running_run_id != failed_run_id, "rerun did not create a new run_id")
        evidence["run_ids"]["success"] = running_run_id
        evidence["rerun_new_run_id"] = True

        shot, probe_file, probe = capture_probe_with_retry(
            edge_path,
            base_url,
            evidence_root,
            name="running_detail",
            case_id="running_detail",
            extra={
                "assignment_probe_ticket": ticket_id,
                "assignment_probe_node": primary_node_id,
                "assignment_probe_delay_ms": "1200",
            },
        )
        assert_true(bool(probe.get("pass")), f"running_detail probe failed: {probe}")
        evidence["screenshots"]["running_detail"] = {"image": shot, "probe": probe_file, "result": probe}

        success_detail = wait_for_status_detail(
            base_url,
            ticket_id=ticket_id,
            node_id=primary_node_id,
            timeout_s=120,
            predicate=lambda payload: (
                str((((payload.get("execution_chain") or {}).get("latest_run") or {}).get("status") or "")).lower() == "succeeded"
                and str(((payload.get("selected_node") or {}).get("result_ref") or "")).strip() != ""
                and bool(list(((payload.get("selected_node") or {}).get("artifact_paths") or [])))
            ),
        )
        write_json(api_dir / "status_success.json", success_detail)
        evidence["api_files"]["status_success"] = (api_dir / "status_success.json").as_posix()
        selected_node = success_detail.get("selected_node") or {}
        success_run = ((success_detail.get("execution_chain") or {}).get("latest_run") or {})
        assert_true(str(selected_node.get("status") or "").strip().lower() == "succeeded", "primary node not succeeded")
        result_ref = str(selected_node.get("result_ref") or "").strip()
        artifact_paths = [str(item).strip() for item in list(selected_node.get("artifact_paths") or []) if str(item).strip()]
        assert_true(result_ref, "result_ref missing after success")
        assert_true(bool(artifact_paths), "artifact paths missing after success")
        evidence["success_auto_writeback"] = True
        evidence["success_auto_delivery"] = True
        downstream_after_success = list((selected_node.get("downstream_nodes") or []))
        evidence["downstream_released"] = any(
            str((item or {}).get("node_id") or "").strip() == downstream_node_id
            and str((item or {}).get("status") or "").strip().lower() in {"ready", "running", "succeeded"}
            for item in downstream_after_success
        )
        assert_true(evidence["downstream_released"], "downstream node was not released after success")

        shot, probe_file, probe = capture_probe_with_retry(
            edge_path,
            base_url,
            evidence_root,
            name="success_detail",
            case_id="success_detail",
            extra={
                "assignment_probe_ticket": ticket_id,
                "assignment_probe_node": primary_node_id,
                "assignment_probe_delay_ms": "1200",
            },
        )
        assert_true(bool(probe.get("pass")), f"success_detail probe failed: {probe}")
        evidence["screenshots"]["success_detail"] = {"image": shot, "probe": probe_file, "result": probe}

        prompt_ref = str(success_run.get("prompt_ref") or "").strip()
        stdout_ref = str(success_run.get("stdout_ref") or "").strip()
        stderr_ref = str(success_run.get("stderr_ref") or "").strip()
        result_run_ref = str(success_run.get("result_ref") or "").strip()
        prompt_path = Path(prompt_ref)
        stdout_path = Path(stdout_ref)
        stderr_path = Path(stderr_ref)
        result_path = Path(result_run_ref)
        workspace_report = agent_root / "mini-worker" / "report.md"
        delivered_artifact = Path(artifact_paths[0])
        task_dir = delivered_artifact.resolve().parents[3]
        task_structure_guide = task_dir / "TASK_STRUCTURE.md"
        root_structure_guide = task_dir.parent.parent / "TASKS_STRUCTURE.md"
        for path in [prompt_path, stdout_path, stderr_path, result_path, workspace_report, delivered_artifact]:
            assert_true(path.exists(), f"required evidence file missing: {path}")
        assert_true(task_structure_guide.exists(), f"task structure guide missing: {task_structure_guide}")
        assert_true(root_structure_guide.exists(), f"root structure guide missing: {root_structure_guide}")

        result_payload = json.loads(result_path.read_text(encoding="utf-8"))
        stdout_text = stdout_path.read_text(encoding="utf-8")
        delivered_text = delivered_artifact.read_text(encoding="utf-8")
        task_structure_text = task_structure_guide.read_text(encoding="utf-8")
        root_structure_text = root_structure_guide.read_text(encoding="utf-8")
        workspace_report_text = workspace_report.read_text(encoding="utf-8")
        assert_true("real execution success" in workspace_report_text, "workspace report content mismatch")
        assert_true("real execution success" in delivered_text, "delivered artifact content mismatch")
        assert_true("单任务目录结构说明" in task_structure_text, "task structure guide title mismatch")
        assert_true("artifacts/<node_id>/output/" in task_structure_text, "task structure guide should explain output path")
        assert_true("任务产物目录结构说明" in root_structure_text, "root structure guide title mismatch")
        assert_true("/tasks/<ticket_id>/" in root_structure_text, "root structure guide should explain task aggregation path")
        assert_true(str(result_payload.get("artifact_label") or "").strip() != "", "result payload artifact label missing")
        assert_true("agent_message" in stdout_text, "stdout trace missing agent_message event")

        evidence["run_files"] = {
            "prompt_ref": prompt_ref,
            "stdout_ref": stdout_ref,
            "stderr_ref": stderr_ref,
            "result_ref": result_run_ref,
            "workspace_report": workspace_report.as_posix(),
            "delivered_artifact": delivered_artifact.as_posix(),
            "task_structure_guide": task_structure_guide.as_posix(),
            "root_structure_guide": root_structure_guide.as_posix(),
        }
        evidence["success_summary"] = {
            "run_id": str(success_run.get("run_id") or "").strip(),
            "status": str(success_run.get("status") or "").strip(),
            "latest_event": str(success_run.get("latest_event") or "").strip(),
            "success_reason": str(selected_node.get("success_reason") or "").strip(),
            "artifact_paths": artifact_paths,
        }
        evidence["ok"] = True
        write_json(evidence_root / "summary.json", evidence)
        render_report(report_path=report_path, evidence_root=evidence_root, summary=evidence)
        print(
            json.dumps(
                {
                    "ok": True,
                    "evidence_root": evidence_root.as_posix(),
                    "report_path": report_path.as_posix(),
                    "ticket_id": ticket_id,
                    "failed_run_id": failed_run_id,
                    "success_run_id": running_run_id,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=10)
        stdout_handle.close()
        stderr_handle.close()
        if not (evidence_root / "summary.json").exists():
            write_json(evidence_root / "summary.json", evidence)


if __name__ == "__main__":
    raise SystemExit(main())
