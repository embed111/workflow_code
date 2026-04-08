#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class _UpgradeWatcherProbeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address):
        super().__init__(server_address, _UpgradeWatcherProbeHandler)
        self.status_get_count = 0
        self.apply_calls: list[dict[str, object]] = []
        self.apply_requested = False

    def current_status_payload(self) -> dict[str, object]:
        if self.apply_requested:
            return {
                "ok": True,
                "current_version": "20260408-090000",
                "candidate_version": "20260408-090000",
                "candidate_available": True,
                "candidate_is_newer": False,
                "request_pending": False,
                "running_task_count": 0,
                "agent_call_count": 0,
                "blocking_reason": "",
                "blocking_reason_code": "",
                "can_upgrade": False,
            }
        self.status_get_count += 1
        if self.status_get_count < 3:
            return {
                "ok": True,
                "current_version": "20260408-070000",
                "candidate_version": "20260408-090000",
                "candidate_available": True,
                "candidate_is_newer": True,
                "request_pending": False,
                "running_task_count": 1,
                "agent_call_count": 1,
                "blocking_reason": "存在运行中任务，暂不可升级",
                "blocking_reason_code": "running_tasks_present",
                "can_upgrade": False,
            }
        return {
            "ok": True,
            "current_version": "20260408-070000",
            "candidate_version": "20260408-090000",
            "candidate_available": True,
            "candidate_is_newer": True,
            "request_pending": False,
            "running_task_count": 0,
            "agent_call_count": 0,
            "blocking_reason": "",
            "blocking_reason_code": "",
            "can_upgrade": True,
        }


class _UpgradeWatcherProbeHandler(BaseHTTPRequestHandler):
    server: _UpgradeWatcherProbeServer

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _write_json(self, status_code: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/api/runtime-upgrade/status":
            self._write_json(404, {"ok": False, "error": "not found"})
            return
        self._write_json(200, self.server.current_status_payload())

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/runtime-upgrade/apply":
            self._write_json(404, {"ok": False, "error": "not found"})
            return
        content_length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(content_length) if content_length > 0 else b""
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            payload = {}
        self.server.apply_calls.append(payload if isinstance(payload, dict) else {})
        self.server.apply_requested = True
        self._write_json(
            202,
            {
                "ok": True,
                "code": "runtime_upgrade_requested",
                "request_pending": True,
                "candidate_version": "20260408-090000",
            },
        )


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    verify_root = workspace_root / ".test" / "runtime-apply-prod-candidate-when-idle"
    if verify_root.exists():
        shutil.rmtree(verify_root, ignore_errors=True)
    verify_root.mkdir(parents=True, exist_ok=True)
    log_path = verify_root / "watcher.md"

    server = _UpgradeWatcherProbeServer(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        script_path = workspace_root / "scripts" / "apply_prod_candidate_when_idle.py"
        result = subprocess.run(
            [
                sys.executable,
                script_path.as_posix(),
                "--base-url",
                f"http://127.0.0.1:{server.server_port}",
                "--timeout-seconds",
                "5",
                "--poll-seconds",
                "0.1",
                "--request-timeout-seconds",
                "1",
                "--apply-wait-seconds",
                "2",
                "--log-path",
                log_path.as_posix(),
            ],
            cwd=workspace_root,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert result.returncode == 0, {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
    }
    assert server.status_get_count >= 3, server.status_get_count
    assert len(server.apply_calls) == 1, server.apply_calls
    assert server.apply_calls[0].get("operator") == "prod-idle-upgrade-watcher", server.apply_calls[0]
    assert log_path.exists(), log_path
    log_text = log_path.read_text(encoding="utf-8")
    assert "running_task_count=1" in log_text, log_text
    assert "running_task_count=0" in log_text, log_text
    assert "prod 已切到目标 candidate" in log_text, log_text

    print(
        json.dumps(
            {
                "ok": True,
                "status_get_count": server.status_get_count,
                "apply_calls": server.apply_calls,
                "log_path": log_path.as_posix(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
