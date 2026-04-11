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

    def __init__(
        self,
        server_address: tuple[str, int],
        *,
        before_apply_payloads: list[dict[str, object]],
        after_apply_payload: dict[str, object] | None = None,
    ) -> None:
        super().__init__(server_address, _UpgradeWatcherProbeHandler)
        self.status_get_count = 0
        self.apply_calls: list[dict[str, object]] = []
        self.apply_requested = False
        self._before_apply_payloads = [dict(payload) for payload in before_apply_payloads]
        self._after_apply_payload = dict(after_apply_payload or {}) if after_apply_payload is not None else None

    def current_status_payload(self) -> dict[str, object]:
        self.status_get_count += 1
        if self.apply_requested and self._after_apply_payload is not None:
            return dict(self._after_apply_payload)
        if not self._before_apply_payloads:
            return {
                "ok": False,
                "error": "no status payload configured",
            }
        index = min(self.status_get_count - 1, len(self._before_apply_payloads) - 1)
        return dict(self._before_apply_payloads[index])


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


def _run_script(
    *,
    workspace_root: Path,
    server: _UpgradeWatcherProbeServer,
    extra_args: list[str],
    log_path: Path,
    timeout_seconds: int = 15,
) -> subprocess.CompletedProcess[str]:
    script_path = workspace_root / "scripts" / "apply_prod_candidate_when_idle.py"
    return subprocess.run(
        [
            sys.executable,
            script_path.as_posix(),
            "--base-url",
            f"http://127.0.0.1:{server.server_port}",
            "--request-timeout-seconds",
            "1",
            "--log-path",
            log_path.as_posix(),
            *extra_args,
        ],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


def _exercise_long_poll_probe(workspace_root: Path, verify_root: Path) -> dict[str, object]:
    log_path = verify_root / "watcher-long-poll.md"
    server = _UpgradeWatcherProbeServer(
        ("127.0.0.1", 0),
        before_apply_payloads=[
            {
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
            },
            {
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
            },
            {
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
            },
        ],
        after_apply_payload={
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
        },
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = _run_script(
            workspace_root=workspace_root,
            server=server,
            extra_args=[
                "--timeout-seconds",
                "5",
                "--poll-seconds",
                "0.1",
                "--apply-wait-seconds",
                "2",
            ],
            log_path=log_path,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert result.returncode == 0, {
        "scenario": "long_poll",
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
    }
    assert server.status_get_count >= 3, server.status_get_count
    assert len(server.apply_calls) == 1, server.apply_calls
    assert server.apply_calls[0].get("operator") == "prod-idle-upgrade-watcher", server.apply_calls[0]
    log_text = log_path.read_text(encoding="utf-8")
    assert "running_task_count=1" in log_text, log_text
    assert "running_task_count=0" in log_text, log_text
    assert "prod 已切到目标 candidate" in log_text, log_text
    return {
        "status_get_count": server.status_get_count,
        "apply_calls": server.apply_calls,
        "log_path": log_path.as_posix(),
    }


def _exercise_single_check_skip_probe(workspace_root: Path, verify_root: Path) -> dict[str, object]:
    log_path = verify_root / "watcher-single-check-skip.md"
    server = _UpgradeWatcherProbeServer(
        ("127.0.0.1", 0),
        before_apply_payloads=[
            {
                "ok": True,
                "current_version": "20260408-090000",
                "candidate_version": "20260408-090000",
                "candidate_available": True,
                "candidate_is_newer": False,
                "request_pending": False,
                "running_task_count": 0,
                "agent_call_count": 0,
                "blocking_reason": "暂无可升级版本",
                "blocking_reason_code": "no_candidate",
                "can_upgrade": False,
            }
        ],
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = _run_script(
            workspace_root=workspace_root,
            server=server,
            extra_args=["--single-check", "--timeout-seconds", "5"],
            log_path=log_path,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert result.returncode == 0, {
        "scenario": "single_check_skip",
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
    }
    assert server.status_get_count == 1, server.status_get_count
    assert len(server.apply_calls) == 0, server.apply_calls
    log_text = log_path.read_text(encoding="utf-8")
    assert "candidate 已不比 current 更新，单次检查跳过。" in log_text, log_text
    return {
        "status_get_count": server.status_get_count,
        "apply_calls": server.apply_calls,
        "log_path": log_path.as_posix(),
    }


def _exercise_single_check_apply_probe(workspace_root: Path, verify_root: Path) -> dict[str, object]:
    log_path = verify_root / "watcher-single-check-apply.md"
    server = _UpgradeWatcherProbeServer(
        ("127.0.0.1", 0),
        before_apply_payloads=[
            {
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
        ],
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = _run_script(
            workspace_root=workspace_root,
            server=server,
            extra_args=["--single-check", "--timeout-seconds", "5"],
            log_path=log_path,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert result.returncode == 0, {
        "scenario": "single_check_apply",
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
    }
    assert server.status_get_count == 1, server.status_get_count
    assert len(server.apply_calls) == 1, server.apply_calls
    assert server.apply_calls[0].get("operator") == "prod-idle-upgrade-watcher", server.apply_calls[0]
    log_text = log_path.read_text(encoding="utf-8")
    assert "单次检查已发起 apply，请交给 supervisor 完成后续切版。" in log_text, log_text
    assert "等待升级完成中" not in log_text, log_text
    return {
        "status_get_count": server.status_get_count,
        "apply_calls": server.apply_calls,
        "log_path": log_path.as_posix(),
    }


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    verify_root = workspace_root / ".test" / "runtime-apply-prod-candidate-when-idle"
    if verify_root.exists():
        shutil.rmtree(verify_root, ignore_errors=True)
    verify_root.mkdir(parents=True, exist_ok=True)

    result_payload = {
        "ok": True,
        "long_poll": _exercise_long_poll_probe(workspace_root, verify_root),
        "single_check_skip": _exercise_single_check_skip_probe(workspace_root, verify_root),
        "single_check_apply": _exercise_single_check_apply_probe(workspace_root, verify_root),
    }
    print(json.dumps(result_payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
