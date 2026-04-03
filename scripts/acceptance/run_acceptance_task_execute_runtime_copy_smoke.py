#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from policy_cache_seed import upsert_policy_cache


def call(base_url: str, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url=base_url + path, data=data, method=method, headers=headers)
    try:
        with urlopen(req, timeout=120) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, (json.loads(body) if body else {})
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            payload_obj = json.loads(body) if body else {}
        except Exception:
            payload_obj = {"raw": body}
        return exc.code, payload_obj


def wait_health(base_url: str, timeout_s: int = 90) -> None:
    end_at = time.time() + max(10, timeout_s)
    while time.time() < end_at:
        status, payload = call(base_url, "GET", "/healthz")
        if status == 200 and payload.get("ok"):
            return
        time.sleep(0.5)
    raise RuntimeError("healthz timeout")


def wait_task_done(base_url: str, task_id: str, timeout_s: int = 180) -> dict:
    end_at = time.time() + max(10, timeout_s)
    while time.time() < end_at:
        status, payload = call(base_url, "GET", f"/api/tasks/{task_id}")
        if status == 200 and payload.get("ok"):
            task_status = str(payload.get("status") or "").lower()
            if task_status in {"success", "failed", "interrupted"}:
                return payload
        time.sleep(0.5)
    raise RuntimeError(f"task timeout: {task_id}")


def write_task_runner_wrapper(runtime_root: Path, server_root: Path) -> Path:
    scripts_dir = runtime_root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    wrapper_path = scripts_dir / "task_agent_runner.py"
    src_root = (server_root / "src").resolve()
    wrapper_path.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "from __future__ import annotations",
                "",
                "import sys",
                f"SRC_ROOT = {src_root.as_posix()!r}",
                "if SRC_ROOT not in sys.path:",
                "    sys.path.insert(0, SRC_ROOT)",
                "",
                "from workflow_app.runtime.task_agent_runner import main",
                "",
                'if __name__ == "__main__":',
                "    raise SystemExit(main())",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return wrapper_path


def build_fixture(runtime_root: Path) -> tuple[Path, str]:
    workspace_root = runtime_root / "workspace-root"
    if workspace_root.exists():
        shutil.rmtree(workspace_root, ignore_errors=True)
    (workspace_root / "workflow").mkdir(parents=True, exist_ok=True)
    (workspace_root / "workflow" / "README.md").write_text("fixture\n", encoding="utf-8")
    agent_dir = workspace_root / "probe-agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENTS.md").write_text(
        "\n".join(
            [
                "# probe-agent",
                "## Role",
                "You are a minimal probe agent for workflow task execution smoke tests.",
                "## Session Goal",
                "Reply with the requested verification token in a short sentence.",
                "## Duty Constraints",
                "- Keep the reply short and directly verifiable.",
                "- Do not perform filesystem writes.",
                "- Stay within the requested scope.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    upsert_policy_cache(
        runtime_root=runtime_root,
        workspace_root=workspace_root,
        specs=[
            {
                "agent_name": "probe-agent",
                "role_profile": "You are a minimal probe agent for workflow task execution smoke tests.",
                "session_goal": "Reply with the requested verification token in a short sentence.",
                "duty_constraints": [
                    "Keep the reply short and directly verifiable.",
                    "Do not perform filesystem writes.",
                    "Stay within the requested scope.",
                ],
                "clarity_score": 90,
                "clarity_gate": "auto",
                "parse_status": "ok",
                "policy_extract_ok": True,
            }
        ],
    )
    return workspace_root, "probe-agent"


def output_summary_path(runtime_root: Path) -> Path:
    artifact_dir = str(os.getenv("TEST_ARTIFACTS_DIR") or "").strip()
    if artifact_dir:
        path = Path(artifact_dir) / "task-execute-runtime-copy-smoke-summary.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    return runtime_root / "task-execute-runtime-copy-smoke-summary.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test /api/tasks/execute against a specific runtime copy.")
    parser.add_argument("--root", default=".", help="workspace root")
    parser.add_argument("--server-root", default=".running/prod", help="runtime copy root that provides scripts/src")
    parser.add_argument("--host", default="127.0.0.1", help="bind host")
    parser.add_argument("--port", type=int, default=8106, help="bind port")
    parser.add_argument(
        "--runtime-root",
        default="",
        help="isolated runtime root (default: TEST_TMP_DIR/runtime-task-execute-smoke or .test/runtime/task-execute-smoke)",
    )
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    server_root = (repo_root / args.server_root).resolve()
    runtime_root = (
        Path(args.runtime_root).resolve()
        if str(args.runtime_root or "").strip()
        else (
            Path(str(os.getenv("TEST_TMP_DIR") or "")).resolve() / "runtime-task-execute-smoke"
            if str(os.getenv("TEST_TMP_DIR") or "").strip()
            else (repo_root / ".test" / "runtime" / "task-execute-smoke").resolve()
        )
    )
    if runtime_root.exists():
        shutil.rmtree(runtime_root, ignore_errors=True)
    runtime_root.mkdir(parents=True, exist_ok=True)

    web_script = (server_root / "scripts" / "workflow_web_server.py").resolve()
    entry_script = (server_root / "scripts" / "workflow_entry_cli.py").resolve()
    if not web_script.exists():
        raise RuntimeError(f"workflow_web_server.py missing under {server_root.as_posix()}")
    if not entry_script.exists():
        raise RuntimeError(f"workflow_entry_cli.py missing under {server_root.as_posix()}")

    write_task_runner_wrapper(runtime_root, server_root)
    workspace_root, agent_name = build_fixture(runtime_root)
    base_url = f"http://{args.host}:{args.port}"
    expected_token = "FIX-PROBE-20260327"
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
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    result: dict[str, object] = {
        "base_url": base_url,
        "server_root": server_root.as_posix(),
        "runtime_root": runtime_root.as_posix(),
        "agent_search_root": workspace_root.as_posix(),
        "expected_token": expected_token,
    }
    summary_path = output_summary_path(runtime_root)
    exit_code = 1
    try:
        wait_health(base_url)
        status, session_payload = call(
            base_url,
            "POST",
            "/api/sessions",
            {
                "agent_name": agent_name,
                "focus": "runtime copy smoke",
                "agent_search_root": workspace_root.as_posix(),
                "is_test_data": True,
            },
        )
        if status != 200 or not session_payload.get("ok"):
            raise RuntimeError(f"session create failed: {status} {session_payload}")
        session_id = str(session_payload.get("session_id") or "")
        if not session_id:
            raise RuntimeError("session_id missing")

        status, task_payload = call(
            base_url,
            "POST",
            "/api/tasks/execute",
            {
                "agent_name": agent_name,
                "session_id": session_id,
                "focus": "runtime copy smoke",
                "agent_search_root": workspace_root.as_posix(),
                "message": f"Reply with token {expected_token}",
                "is_test_data": True,
            },
        )
        if status != 202 or not task_payload.get("ok"):
            raise RuntimeError(f"task create failed: {status} {task_payload}")
        task_id = str(task_payload.get("task_id") or "")
        if not task_id:
            raise RuntimeError("task_id missing")

        task_row = wait_task_done(base_url, task_id)
        msg_status, msg_payload = call(base_url, "GET", f"/api/chat/sessions/{session_id}/messages")
        assistant_messages = []
        if msg_status == 200 and msg_payload.get("ok"):
            assistant_messages = [
                str(item.get("content") or "")
                for item in (msg_payload.get("messages") or [])
                if str(item.get("role") or "") == "assistant"
            ]
        assistant_reply = assistant_messages[-1] if assistant_messages else ""

        result.update(
            {
                "session_id": session_id,
                "task_id": task_id,
                "task_status": task_row.get("status"),
                "task_summary": task_row.get("summary"),
                "assistant_reply": assistant_reply,
                "assistant_contains_expected": expected_token in assistant_reply,
            }
        )
        if str(task_row.get("status") or "").lower() != "success":
            raise RuntimeError(f"unexpected task status: {task_row.get('status')} {task_row.get('summary')}")
        if expected_token not in assistant_reply:
            raise RuntimeError(f"assistant reply missing expected token: {assistant_reply!r}")
        exit_code = 0
        return 0
    except Exception as exc:
        result["error"] = str(exc)
        raise
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        result["server_stdout_tail"] = ((proc.stdout.read() if proc.stdout else "") or "")[-2000:]
        result["server_stderr_tail"] = ((proc.stderr.read() if proc.stderr else "") or "")[-2000:]
        result["exit_code"] = exit_code
        summary_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(summary_path.as_posix())


if __name__ == "__main__":
    raise SystemExit(main())
