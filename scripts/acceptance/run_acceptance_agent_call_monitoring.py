#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Acceptance: monitored agent call should outlive legacy timeout and reuse cache.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18131)
    return parser.parse_args()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(text or ""), encoding="utf-8")


def call(base_url: str, method: str, route: str, payload: dict[str, Any] | None = None, *, timeout: int = 120) -> tuple[int, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(base_url + route, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            content_type = str(response.headers.get("Content-Type") or "")
            if "application/json" in content_type:
                return int(response.status), (json.loads(raw.decode("utf-8")) if raw else {})
            return int(response.status), raw.decode("utf-8")
    except HTTPError as exc:
        raw = exc.read()
        content_type = str(exc.headers.get("Content-Type") or "")
        if "application/json" in content_type:
            return int(exc.code), (json.loads(raw.decode("utf-8")) if raw else {})
        return int(exc.code), raw.decode("utf-8")


def wait_health(base_url: str, timeout_s: int = 60) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            status, payload = call(base_url, "GET", "/healthz", timeout=10)
            if status == 200 and isinstance(payload, dict) and payload.get("ok"):
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError("healthz timeout")


def write_acceptance_codex_stub(bin_dir: Path) -> Path:
    # Acceptance-only stub. It is isolated under scripts/acceptance and must never be wired into test/prod formal flows.
    bin_dir.mkdir(parents=True, exist_ok=True)
    script_path = bin_dir / "codex_stub.py"
    cmd_path = bin_dir / "codex.cmd"
    script_path.write_text(
        "\n".join(
            [
                "import json",
                "import time",
                "",
                "payload = {",
                "  'role': '你是角色策略提取验收桩，只用于本地 acceptance 校验。',",
                "  'goal': '验证监控式 agent 调用可以超过旧总超时后仍成功返回结构化结果。',",
                "  'responsibilities': {",
                "    'must': [",
                "      {'text': '输出结构化 JSON 结果。', 'evidence': '## 职责边界\\n- 输出结构化 JSON 结果。', 'source_title': 'must'},",
                "      {'text': '只用于 acceptance 校验。', 'evidence': '## 职责边界\\n- 只用于 acceptance 校验。', 'source_title': 'must'}",
                "    ],",
                "    'must_not': [",
                "      {'text': '不得接入正式 test/prod 流程。', 'evidence': '## 职责边界\\n- 不得接入正式 test/prod 流程。', 'source_title': 'must_not'}",
                "    ],",
                "    'preconditions': [",
                "      {'text': '仅在 scripts/acceptance 启动的 mock 环境下使用。', 'evidence': '## 前置条件\\n- 仅在 scripts/acceptance 启动的 mock 环境下使用。', 'source_title': 'preconditions'}",
                "    ]",
                "  },",
                "  'evidence': [],",
                "  'parse_status': 'ok',",
                "  'clarity_score': 96,",
                "  'clarity_gate': 'auto',",
                "  'warnings': [],",
                "  'missing_fields': []",
                "}",
                "time.sleep(2.5)",
                "print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(payload, ensure_ascii=False)}}, ensure_ascii=False))",
                "print(json.dumps({'type': 'turn.completed', 'message': 'acceptance stub completed'}, ensure_ascii=False))",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    cmd_path.write_text("@echo off\r\n" + f"\"{sys.executable}\" \"{script_path.as_posix()}\" %*\r\n", encoding="utf-8")
    return cmd_path


def write_fixture_workspace(workspace_root: Path) -> Path:
    (workspace_root / "workflow").mkdir(parents=True, exist_ok=True)
    (workspace_root / "workflow" / "README.md").write_text("agent call monitoring acceptance\n", encoding="utf-8")
    agent_dir = workspace_root / "policy-monitor-agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENTS.md").write_text(
        "\n".join(
            [
                "# policy-monitor-agent",
                "",
                "## 角色定位",
                "你是策略提取验收用角色。",
                "",
                "## 会话目标",
                "输出清晰的角色边界与执行目标。",
                "",
                "## 职责边界",
                "### must",
                "- 输出结构化策略。",
                "- 说明边界与证据。",
                "",
                "### must_not",
                "- 不得省略关键字段。",
                "",
                "### preconditions",
                "- 仅在 workflow 根路径内工作。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return workspace_root


def write_summary(summary_path: Path, payload: dict[str, Any]) -> None:
    lines = [
        f"# Agent Call Monitoring Acceptance - {payload.get('timestamp')}",
        "",
        f"- base_url: {payload.get('base_url')}",
        f"- runtime_root: {payload.get('runtime_root')}",
        f"- workspace_root: {payload.get('workspace_root')}",
        f"- stub_path: {payload.get('stub_path')}",
        "",
        "## Result",
        "```json",
        json.dumps(payload, ensure_ascii=False, indent=2),
        "```",
        "",
    ]
    write_text(summary_path, "\n".join(lines))


def main() -> int:
    args = parse_args()
    repo_root = Path(args.root).resolve()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    evidence_root = (repo_root / "logs" / "runs" / f"agent-call-monitoring-{stamp}").resolve()
    runtime_root = (repo_root / ".test" / "runtime" / f"agent-call-monitoring-{stamp}").resolve()
    workspace_root = (runtime_root / "workspace-root").resolve()
    stub_bin = (evidence_root / "stub-bin").resolve()
    stdout_path = evidence_root / "server_stdout.log"
    stderr_path = evidence_root / "server_stderr.log"
    api_dir = evidence_root / "api"
    summary_json_path = evidence_root / "summary.json"
    summary_md_path = evidence_root / "summary.md"
    if runtime_root.exists():
        shutil.rmtree(runtime_root, ignore_errors=True)
    runtime_root.mkdir(parents=True, exist_ok=True)
    write_fixture_workspace(workspace_root)
    stub_cmd = write_acceptance_codex_stub(stub_bin)

    base_url = f"http://{args.host}:{args.port}"
    entry_script = (repo_root / "scripts" / "workflow_entry_cli.py").resolve()
    web_script = (repo_root / "scripts" / "workflow_web_server.py").resolve()
    server_env = os.environ.copy()
    server_env["PATH"] = str(stub_bin) + os.pathsep + str(server_env.get("PATH") or "")
    # Acceptance-only override to keep the stub isolated from formal test/prod flows.
    server_env["WORKFLOW_CODEX_BIN"] = stub_cmd.as_posix()
    # Deliberately keep the legacy timeout knob extremely low; monitored execution must ignore this total timeout.
    server_env["WORKFLOW_POLICY_CODEX_TIMEOUT_S"] = "1"

    stdout_handle = stdout_path.open("w", encoding="utf-8")
    stderr_handle = stderr_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [
            sys.executable,
            str(web_script),
            "--root",
            runtime_root.as_posix(),
            "--entry-script",
            entry_script.as_posix(),
            "--agent-search-root",
            workspace_root.as_posix(),
            "--host",
            args.host,
            "--port",
            str(args.port),
        ],
        cwd=str(repo_root),
        env=server_env,
        stdout=stdout_handle,
        stderr=stderr_handle,
        text=True,
    )

    summary: dict[str, Any] = {
        "timestamp": stamp,
        "base_url": base_url,
        "runtime_root": runtime_root.as_posix(),
        "workspace_root": workspace_root.as_posix(),
        "stub_path": stub_cmd.as_posix(),
        "legacy_timeout_env": server_env["WORKFLOW_POLICY_CODEX_TIMEOUT_S"],
        "result": "failed",
        "checks": {},
    }

    try:
        wait_health(base_url)
        status, agents_payload = call(base_url, "GET", "/api/agents", timeout=30)
        write_json(api_dir / "01_agents.json", {"status": status, "body": agents_payload})
        if status != 200 or not isinstance(agents_payload, dict) or not agents_payload.get("ok"):
            raise RuntimeError(f"load agents failed: {status} {agents_payload}")
        agent_names = [str((item or {}).get("agent_name") or "").strip() for item in (agents_payload.get("agents") or [])]
        if "policy-monitor-agent" not in agent_names:
            raise RuntimeError(f"policy-monitor-agent missing: {agent_names}")
        summary["checks"]["agents"] = {"status": status, "agent_names": agent_names}

        analyze_body = {
            "agent_name": "policy-monitor-agent",
            "agent_search_root": workspace_root.as_posix(),
        }

        started_first = time.perf_counter()
        first_status, first_payload = call(base_url, "POST", "/api/policy/analyze", analyze_body, timeout=120)
        first_elapsed_ms = int((time.perf_counter() - started_first) * 1000)
        write_json(api_dir / "02_policy_analyze_first.json", {"status": first_status, "body": first_payload, "elapsed_ms": first_elapsed_ms})
        if first_status != 200 or not isinstance(first_payload, dict) or not first_payload.get("ok"):
            raise RuntimeError(f"first policy analyze failed: {first_status} {first_payload}")

        first_policy = dict(first_payload.get("agent_policy") or {})
        first_chain = dict(first_policy.get("analysis_chain") or {})
        first_monitor = dict(first_chain.get("monitor") or {})
        if str(first_policy.get("parse_status") or "").strip().lower() != "ok":
            raise RuntimeError(f"first policy analyze parse_status unexpected: {first_policy}")
        if first_elapsed_ms < 2000:
            raise RuntimeError(f"first policy analyze should exceed legacy timeout window: {first_elapsed_ms}ms")
        if not first_monitor.get("pid"):
            raise RuntimeError(f"first policy analyze monitor missing pid: {first_monitor}")
        summary["checks"]["first_call"] = {
            "elapsed_ms": first_elapsed_ms,
            "parse_status": first_policy.get("parse_status"),
            "policy_cache_hit": bool(first_policy.get("policy_cache_hit")),
            "monitor": first_monitor,
            "ui_progress": first_chain.get("ui_progress"),
        }

        started_second = time.perf_counter()
        second_status, second_payload = call(base_url, "POST", "/api/policy/analyze", analyze_body, timeout=60)
        second_elapsed_ms = int((time.perf_counter() - started_second) * 1000)
        write_json(api_dir / "03_policy_analyze_second.json", {"status": second_status, "body": second_payload, "elapsed_ms": second_elapsed_ms})
        if second_status != 200 or not isinstance(second_payload, dict) or not second_payload.get("ok"):
            raise RuntimeError(f"second policy analyze failed: {second_status} {second_payload}")

        second_policy = dict(second_payload.get("agent_policy") or {})
        if str(second_policy.get("parse_status") or "").strip().lower() != "ok":
            raise RuntimeError(f"second policy analyze parse_status unexpected: {second_policy}")
        if not (second_elapsed_ms < first_elapsed_ms and second_elapsed_ms < 1000):
            raise RuntimeError(f"second policy analyze should reuse cache and be faster: first={first_elapsed_ms} second={second_elapsed_ms}")
        summary["checks"]["second_call"] = {
            "elapsed_ms": second_elapsed_ms,
            "parse_status": second_policy.get("parse_status"),
            "policy_cache_hit": bool(second_policy.get("policy_cache_hit")),
        }

        summary["result"] = "passed"
        write_json(summary_json_path, summary)
        write_summary(summary_md_path, summary)
        print(summary_md_path.as_posix())
        return 0
    except Exception as exc:
        summary["error"] = str(exc)
        write_json(summary_json_path, summary)
        write_summary(summary_md_path, summary)
        print(summary_md_path.as_posix())
        return 1
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        stdout_handle.close()
        stderr_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
