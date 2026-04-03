#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run non-token release gate for deployed workflow env.")
    parser.add_argument("--workspace-root", required=True, help="deployed workspace root (.running/test)")
    parser.add_argument("--runtime-root", required=True, help="runtime root for the deployed environment")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8092)
    parser.add_argument("--version", required=True)
    parser.add_argument("--report-root", required=True)
    return parser.parse_args()


def api_request(base_url: str, method: str, route: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    payload = None
    headers = {"Accept": "application/json"}
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(base_url + route, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            content_type = str(response.headers.get("Content-Type") or "")
            raw = response.read()
            if "application/json" in content_type:
                payload_obj = json.loads(raw.decode("utf-8")) if raw else {}
                return int(response.status), payload_obj
            return int(response.status), raw.decode("utf-8")
    except urllib.error.HTTPError as exc:
        content_type = str(exc.headers.get("Content-Type") or "")
        raw = exc.read()
        if "application/json" in content_type:
            payload_obj = json.loads(raw.decode("utf-8")) if raw else {}
            return int(exc.code), payload_obj
        return int(exc.code), raw.decode("utf-8")


def wait_health(base_url: str, timeout_s: float = 45.0) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            status, payload = api_request(base_url, "GET", "/healthz")
            if status == 200 and isinstance(payload, dict) and payload.get("ok"):
                return payload
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError("healthz timeout")


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def write_fixture_workspace(root: Path) -> Path:
    fixture_root = (root / "fixture-workspace").resolve()
    (fixture_root / "workflow").mkdir(parents=True, exist_ok=True)
    (fixture_root / "workflow" / "README.md").write_text("runtime release gate fixture\n", encoding="utf-8")
    agent_dir = fixture_root / "trainer"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENTS.md").write_text(
        "\n".join(
            [
                "# trainer",
                "",
                "## 角色定位",
                "你是本地发布门禁探针助手。",
                "",
                "## 会话目标",
                "仅用于校验 workflow 页面和接口可用性。",
                "",
                "## 职责边界",
                "- 不调用任何外部 token 执行链路。",
                "- 仅验证本地 API 和页面基础能力。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return fixture_root


def patch_runtime_config(runtime_root: Path, fixture_root: Path) -> str:
    cfg_path = runtime_root / "state" / "runtime-config.json"
    original = ""
    if cfg_path.exists():
        original = cfg_path.read_text(encoding="utf-8")
    payload: dict[str, Any] = {}
    if original:
        try:
            payload = json.loads(original)
        except Exception:
            payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload["agent_search_root"] = fixture_root.as_posix()
    payload["show_test_data"] = True
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return original


def restore_runtime_config(runtime_root: Path, original_text: str) -> None:
    cfg_path = runtime_root / "state" / "runtime-config.json"
    if original_text:
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(original_text, encoding="utf-8")
        return
    try:
        cfg_path.unlink()
    except FileNotFoundError:
        return


def run_workspace_line_budget_gate(workspace_root: Path, report_root: Path, version: str) -> tuple[bool, dict[str, Any]]:
    checker = (workspace_root / "scripts" / "quality" / "check_workspace_line_budget.py").resolve()
    if not checker.exists():
        raise RuntimeError(f"line budget checker missing: {checker}")
    report_path = (report_root / f"workspace-line-budget-{version}.md").resolve()
    json_report_path = report_path.with_suffix(".json")
    proc = subprocess.run(
        [
            sys.executable,
            str(checker),
            "--root",
            workspace_root.as_posix(),
            "--report",
            report_path.as_posix(),
            "--json-report",
            json_report_path.as_posix(),
        ],
        cwd=str(workspace_root),
        capture_output=True,
        text=True,
    )
    if not json_report_path.exists():
        raise RuntimeError(f"line budget json report missing: {json_report_path}")
    payload = json.loads(json_report_path.read_text(encoding="utf-8"))
    hard_gate = payload.get("hard_gate") or {}
    refactor_gate = payload.get("refactor_trigger_gate") or {}
    guideline_gate = payload.get("guideline_gate") or {}
    detail = {
        "report_path": report_path.as_posix(),
        "json_report_path": json_report_path.as_posix(),
        "hard_gate_pass": bool(hard_gate.get("pass", proc.returncode == 0)),
        "hard_gate_offender_count": int(hard_gate.get("offender_count", 0) or 0),
        "refactor_triggered": bool(refactor_gate.get("triggered", False)),
        "refactor_trigger_count": int(refactor_gate.get("offender_count", 0) or 0),
        "guideline_triggered": bool(guideline_gate.get("triggered", False)),
        "guideline_trigger_count": int(guideline_gate.get("offender_count", 0) or 0),
        "trigger_action": str(payload.get("trigger_action") or "none"),
        "summary": payload,
    }
    if str(proc.stderr or "").strip():
        detail["stderr"] = str(proc.stderr or "").strip()
    return bool(detail["hard_gate_pass"]), detail


def main() -> int:
    args = parse_args()
    workspace_root = Path(args.workspace_root).resolve()
    runtime_root = Path(args.runtime_root).resolve()
    report_root = Path(args.report_root).resolve()
    report_root.mkdir(parents=True, exist_ok=True)
    report_path = report_root / f"test-gate-{args.version}.json"
    stdout_path = report_root / f"test-gate-{args.version}.stdout.log"
    stderr_path = report_root / f"test-gate-{args.version}.stderr.log"
    base_url = f"http://{args.host}:{args.port}"
    fixture_root = write_fixture_workspace(report_root / args.version)
    original_runtime_config = patch_runtime_config(runtime_root, fixture_root)
    launch_script = workspace_root / "scripts" / "launch_workflow.ps1"
    if not launch_script.exists():
        raise SystemExit(f"launch script missing: {launch_script}")

    stdout_handle = stdout_path.open("wb")
    stderr_handle = stderr_path.open("wb")
    proc = subprocess.Popen(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(launch_script),
            "-BindHost",
            args.host,
            "-Port",
            str(args.port),
            "-RuntimeRoot",
            str(runtime_root),
            "-SkipBackfill",
        ],
        cwd=str(workspace_root),
        stdout=stdout_handle,
        stderr=stderr_handle,
    )

    evidence: dict[str, Any] = {
        "workspace_root": workspace_root.as_posix(),
        "runtime_root": runtime_root.as_posix(),
        "host": args.host,
        "port": args.port,
        "version": args.version,
        "base_url": base_url,
        "fixture_root": fixture_root.as_posix(),
        "stdout_path": stdout_path.as_posix(),
        "stderr_path": stderr_path.as_posix(),
        "checks": {},
    }

    try:
        line_budget_ok, line_budget = run_workspace_line_budget_gate(workspace_root, report_root, args.version)
        evidence["checks"]["workspace_line_budget"] = line_budget
        assert_true(line_budget_ok, "workspace hard line budget failed")
        if bool(line_budget.get("refactor_triggered")):
            evidence.setdefault("warnings", []).append("workspace line budget triggered refactor_skill")

        evidence["healthz"] = wait_health(base_url)

        status, runtime_status = api_request(base_url, "GET", "/api/runtime-upgrade/status")
        assert_true(status == 200 and isinstance(runtime_status, dict) and runtime_status.get("ok"), "runtime upgrade status unavailable")
        assert_true(str(runtime_status.get("environment") or "").strip() == "test", "runtime upgrade status should expose test environment")
        evidence["checks"]["runtime_upgrade_status"] = runtime_status

        status, dashboard = api_request(base_url, "GET", "/api/status")
        assert_true(status == 200 and isinstance(dashboard, dict) and dashboard.get("ok"), "status api unavailable")
        evidence["checks"]["status"] = {
            "running_task_count": dashboard.get("running_task_count"),
            "agent_call_count": dashboard.get("agent_call_count"),
            "available_agents": dashboard.get("available_agents"),
        }

        status, artifact_root = api_request(base_url, "GET", "/api/config/artifact-root")
        assert_true(status == 200 and isinstance(artifact_root, dict) and artifact_root.get("ok"), "artifact root config unavailable")
        structure_path = Path(str(artifact_root.get("tasks_structure_path") or "")).resolve()
        assert_true(structure_path.exists(), "tasks structure guide missing")
        evidence["checks"]["artifact_root"] = artifact_root

        status, show_on = api_request(base_url, "GET", "/api/config/show-test-data")
        assert_true(status == 200 and isinstance(show_on, dict) and show_on.get("ok"), "show_test_data policy unavailable")
        assert_true(bool(show_on.get("show_test_data")), "test gate should run with show_test_data=true environment policy")
        assert_true(str(show_on.get("environment") or "").strip() == "test", "show_test_data policy should expose test environment")
        evidence["checks"]["show_test_data_policy"] = show_on
        status, bootstrap = api_request(base_url, "POST", "/api/assignments/test-data/bootstrap", {"operator": "release-gate"})
        assert_true(status == 200 and isinstance(bootstrap, dict) and bootstrap.get("ok"), "assignment test-data bootstrap failed")
        ticket_id = str(bootstrap.get("ticket_id") or "").strip()
        assert_true(ticket_id, "assignment bootstrap missing ticket_id")
        status, graph = api_request(base_url, "GET", f"/api/assignments/{ticket_id}/graph")
        assert_true(status == 200 and isinstance(graph, dict) and graph.get("ok"), "assignment graph fetch failed")
        metrics = (graph.get("metrics_summary") or {}).get("status_counts") or {}
        assert_true(int((graph.get("metrics_summary") or {}).get("total_nodes") or 0) == 20, "test assignment graph should contain 20 nodes")
        assert_true(int(metrics.get("running") or 0) >= 1, "test assignment graph should surface running nodes")
        evidence["checks"]["assignment_test_graph"] = {
            "ticket_id": ticket_id,
            "metrics_summary": graph.get("metrics_summary"),
        }

        status, agents = api_request(base_url, "GET", "/api/agents")
        assert_true(status == 200 and isinstance(agents, dict) and agents.get("ok"), "agents api unavailable")
        evidence["checks"]["agents"] = {
            "agent_search_root": agents.get("agent_search_root"),
            "agent_count": len(list(agents.get("agents") or [])),
        }

        evidence["result"] = "passed"
        report_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(report_path.as_posix())
        return 0
    except Exception as exc:
        evidence["result"] = "failed"
        evidence["error"] = str(exc)
        report_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(report_path.as_posix())
        return 1
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        restore_runtime_config(runtime_root, original_runtime_config)
        stdout_handle.close()
        stderr_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
