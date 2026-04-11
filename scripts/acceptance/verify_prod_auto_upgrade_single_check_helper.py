#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class _HelperProbeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int]) -> None:
        super().__init__(server_address, _HelperProbeHandler)
        self.status_get_count = 0
        self.apply_calls: list[dict[str, object]] = []

    def current_status_payload(self) -> dict[str, object]:
        self.status_get_count += 1
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


class _HelperProbeHandler(BaseHTTPRequestHandler):
    server: _HelperProbeServer

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
    verify_root = workspace_root / ".test" / "prod-auto-upgrade-single-check-helper"
    if verify_root.exists():
        shutil.rmtree(verify_root, ignore_errors=True)
    verify_root.mkdir(parents=True, exist_ok=True)
    log_path = verify_root / "watchdog-live.md"

    server = _HelperProbeServer(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        command = [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                f". '{(workspace_root / 'scripts' / 'workflow_env_common.ps1').as_posix()}'; "
                f"$descriptor = @{{ environment='prod'; host='127.0.0.1'; port={server.server_port} }}; "
                f"$result = Invoke-WorkflowProdAutoUpgradeSingleCheck -SourceRoot '{workspace_root.as_posix()}' "
                f"-Descriptor $descriptor -Operator 'prod-auto-upgrade-helper-probe' "
                f"-RequestTimeoutSeconds 1 -TimeoutSeconds 5 -LogPath '{log_path.as_posix()}'; "
                "$result | ConvertTo-Json -Depth 8"
            ),
        ]
        proc = subprocess.run(
            command,
            cwd=workspace_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert proc.returncode == 0, {
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "returncode": proc.returncode,
    }
    result_payload = json.loads(proc.stdout)
    assert bool(result_payload.get("ok")), result_payload
    exit_code = result_payload.get("exit_code")
    assert exit_code is not None and int(exit_code) == 0, result_payload
    assert result_payload.get("operator") == "prod-auto-upgrade-helper-probe", result_payload
    assert server.status_get_count == 1, server.status_get_count
    assert len(server.apply_calls) == 1, server.apply_calls
    assert server.apply_calls[0].get("operator") == "prod-auto-upgrade-helper-probe", server.apply_calls[0]
    assert log_path.exists(), log_path
    log_text = log_path.read_text(encoding="utf-8")
    assert "单次检查已发起 apply，请交给 supervisor 完成后续切版。" in log_text, log_text

    print(
        json.dumps(
            {
                "ok": True,
                "result_payload": result_payload,
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
