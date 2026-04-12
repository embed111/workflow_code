#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


RUNTIME_ENV_KEYS = (
    "WORKFLOW_RUNTIME_ENV",
    "WORKFLOW_RUNTIME_SOURCE_ROOT",
    "WORKFLOW_RUNTIME_CONTROL_ROOT",
    "WORKFLOW_RUNTIME_MANIFEST_PATH",
    "WORKFLOW_RUNTIME_DEPLOY_ROOT",
    "WORKFLOW_RUNTIME_VERSION",
    "WORKFLOW_RUNTIME_PID_FILE",
    "WORKFLOW_RUNTIME_INSTANCE_FILE",
)


class _DrainHitProbeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int]) -> None:
        super().__init__(server_address, _DrainHitProbeHandler)
        self.status_get_count = 0
        self.apply_calls: list[dict[str, object]] = []

    def current_status_payload(self) -> dict[str, object]:
        self.status_get_count += 1
        return {
            "ok": True,
            "current_version": "20260412-151337",
            "candidate_version": "20260412-201138",
            "candidate_available": True,
            "candidate_is_newer": True,
            "request_pending": False,
            "running_task_count": 0,
            "agent_call_count": 0,
            "blocking_reason": "",
            "blocking_reason_code": "",
            "can_upgrade": True,
        }


class _DrainHitProbeHandler(BaseHTTPRequestHandler):
    server: _DrainHitProbeServer

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
                "candidate_version": "20260412-201138",
            },
        )


def _wait_for(predicate, *, timeout_seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + max(0.1, float(timeout_seconds or 0.0))
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str((workspace_root / "src").resolve()))

    from workflow_app.server.services import runtime_upgrade_service

    backup = {key: os.environ.get(key) for key in RUNTIME_ENV_KEYS}
    server = _DrainHitProbeServer(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="workflow-runtime-drain-hit-") as tmp:
            temp_root = Path(tmp).resolve()
            control_root = temp_root / "control"
            envs_root = control_root / "envs"
            instances_root = control_root / "instances"
            deploy_root = temp_root / "prod"
            candidate_root = temp_root / "candidate-app"
            evidence_path = temp_root / "test-gate-20260412-201138.json"
            envs_root.mkdir(parents=True, exist_ok=True)
            instances_root.mkdir(parents=True, exist_ok=True)
            deploy_root.mkdir(parents=True, exist_ok=True)
            candidate_root.mkdir(parents=True, exist_ok=True)
            evidence_path.write_text("{}", encoding="utf-8")

            manifest_path = envs_root / "prod.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "environment": "prod",
                        "current_version": "20260412-151337",
                        "current_version_rank": "20260412-151337",
                        "deploy_root": deploy_root.as_posix(),
                        "host": "127.0.0.1",
                        "port": server.server_port,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            instance_path = instances_root / "prod.json"
            instance_path.write_text(
                json.dumps(
                    {
                        "environment": "prod",
                        "pid": 123,
                        "host": "127.0.0.1",
                        "port": server.server_port,
                        "status": "running",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            (control_root / "prod-candidate.json").write_text(
                json.dumps(
                    {
                        "version": "20260412-201138",
                        "version_rank": "20260412-201138",
                        "source_environment": "test",
                        "passed_at": "2026-04-12T12:11:45.9702935Z",
                        "evidence_path": evidence_path.as_posix(),
                        "candidate_app_root": candidate_root.as_posix(),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            for key in RUNTIME_ENV_KEYS:
                os.environ.pop(key, None)
            os.environ["WORKFLOW_RUNTIME_ENV"] = "prod"
            os.environ["WORKFLOW_RUNTIME_SOURCE_ROOT"] = workspace_root.as_posix()
            os.environ["WORKFLOW_RUNTIME_CONTROL_ROOT"] = control_root.as_posix()
            os.environ["WORKFLOW_RUNTIME_MANIFEST_PATH"] = manifest_path.as_posix()
            os.environ["WORKFLOW_RUNTIME_DEPLOY_ROOT"] = deploy_root.as_posix()
            os.environ["WORKFLOW_RUNTIME_INSTANCE_FILE"] = instance_path.as_posix()

            runtime_upgrade_service._PROD_AUTO_UPGRADE_SINGLE_CHECK_STATE["requested_at"] = 0.0
            runtime_upgrade_service._PROD_AUTO_UPGRADE_SINGLE_CHECK_STATE["candidate_version"] = ""
            runtime_upgrade_service._PROD_AUTO_UPGRADE_SINGLE_CHECK_STATE["pid"] = 0

            first = runtime_upgrade_service.request_prod_auto_upgrade_single_check(
                operator="drain-hit-probe",
                reason="probe-first",
                min_interval_seconds=300,
            )
            assert bool(first.get("ok")), first
            assert bool(first.get("requested")), first
            assert _wait_for(lambda: len(server.apply_calls) >= 1), server.apply_calls

            second = runtime_upgrade_service.request_prod_auto_upgrade_single_check(
                operator="drain-hit-probe",
                reason="probe-second",
                min_interval_seconds=300,
            )
            assert bool(second.get("ok")), second
            assert not bool(second.get("requested")), second
            assert str(second.get("reason") or "").strip() == "throttled", second
            assert len(server.apply_calls) == 1, server.apply_calls
            assert server.apply_calls[0].get("operator") == "drain-hit-probe", server.apply_calls[0]

            log_path = Path(str(first.get("log_path") or "")).resolve(strict=False)
            assert log_path.exists(), log_path
            log_text = log_path.read_text(encoding="utf-8")
            assert "单次检查已发起 apply，请交给 supervisor 完成后续切版。" in log_text, log_text

            print(
                json.dumps(
                    {
                        "ok": True,
                        "first": first,
                        "second": second,
                        "status_get_count": server.status_get_count,
                        "apply_calls": server.apply_calls,
                        "log_path": log_path.as_posix(),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        return 0
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        for key, value in backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
