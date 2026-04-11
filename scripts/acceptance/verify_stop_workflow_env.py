#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path


def _copy_script_fixture(repo_root: Path, fixture_root: Path) -> None:
    for relative_path in (
        "scripts/stop_workflow_env.ps1",
        "scripts/workflow_env_common.ps1",
    ):
        source = repo_root / relative_path
        target = fixture_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _allocate_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _wait_for_port(port: int, *, expect_listening: bool, timeout_seconds: float = 10.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            connected = sock.connect_ex(("127.0.0.1", port)) == 0
        if connected == expect_listening:
            return
        time.sleep(0.2)
    raise AssertionError(f"port {port} expect_listening={expect_listening} not reached within timeout")


def _write_environment_files(fixture_root: Path, environment: str, port: int, *, process: subprocess.Popen[str] | None) -> None:
    control_root = fixture_root / ".running" / "control"
    deploy_root = fixture_root / ".running" / environment
    runtime_root = control_root / "runtime" / environment
    manifest_path = control_root / "envs" / f"{environment}.json"
    pid_file = control_root / "pids" / f"{environment}.pid"
    instance_file = control_root / "instances" / f"{environment}.json"

    runtime_root.mkdir(parents=True, exist_ok=True)
    deploy_root.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    instance_file.parent.mkdir(parents=True, exist_ok=True)

    manifest_payload = {
        "environment": environment,
        "host": "127.0.0.1",
        "port": port,
        "current_version": "fixture-version",
        "runtime_root": runtime_root.as_posix(),
        "deploy_root": deploy_root.as_posix(),
        "control_root": control_root.as_posix(),
        "manifest_path": manifest_path.as_posix(),
    }
    manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if process is not None:
        pid_file.write_text(f"{process.pid}\n", encoding="utf-8")
    instance_payload = {
        "environment": environment,
        "control_root": control_root.as_posix(),
        "deploy_root": deploy_root.as_posix(),
        "manifest_path": manifest_path.as_posix(),
    }
    instance_file.write_text(json.dumps(instance_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _build_fixture_workflow_server(fixture_root: Path) -> Path:
    script_path = fixture_root / "scripts" / "bin" / "workflow_web_server.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(
        "\n".join(
            [
                "import argparse",
                "from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer",
                "",
                "parser = argparse.ArgumentParser()",
                "parser.add_argument('--root', default='.')",
                "parser.add_argument('--host', default='127.0.0.1')",
                "parser.add_argument('--port', type=int, required=True)",
                "args = parser.parse_args()",
                "server = ThreadingHTTPServer((args.host, args.port), SimpleHTTPRequestHandler)",
                "try:",
                "    server.serve_forever()",
                "except KeyboardInterrupt:",
                "    pass",
                "finally:",
                "    server.server_close()",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return script_path


def _run_stop_script(fixture_root: Path, *, environment: str, extra_args: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    script_path = fixture_root / "scripts" / "stop_workflow_env.ps1"
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
        "-Environment",
        environment,
        *(extra_args or []),
    ]
    return subprocess.run(
        command,
        cwd=str(fixture_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )


def _exercise_trusted_test_stop(repo_root: Path, verify_root: Path) -> dict[str, object]:
    fixture_root = verify_root / "trusted-test-stop"
    fixture_root.mkdir(parents=True, exist_ok=True)
    _copy_script_fixture(repo_root, fixture_root)

    port = _allocate_port()
    server_root = fixture_root / "server-root"
    server_root.mkdir(parents=True, exist_ok=True)
    runtime_root = fixture_root / ".running" / "control" / "runtime" / "test"
    runtime_root.mkdir(parents=True, exist_ok=True)
    fixture_server = _build_fixture_workflow_server(fixture_root)
    proc = subprocess.Popen(
        [
            sys.executable,
            str(fixture_server),
            "--root",
            str(runtime_root),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(server_root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        _wait_for_port(port, expect_listening=True)
        _write_environment_files(fixture_root, "test", port, process=proc)
        result = _run_stop_script(fixture_root, environment="test")
        assert result.returncode == 0, {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }
        proc.wait(timeout=10)
        _wait_for_port(port, expect_listening=False)
        payload = json.loads(result.stdout)
        pid_file = fixture_root / ".running" / "control" / "pids" / "test.pid"
        instance_file = fixture_root / ".running" / "control" / "instances" / "test.json"
        assert payload["status"] == "stopped", payload
        assert not pid_file.exists(), pid_file
        assert not instance_file.exists(), instance_file
        return {
            "returncode": result.returncode,
            "payload": payload,
        }
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


def _exercise_untrusted_listener_fail_closed(repo_root: Path, verify_root: Path) -> dict[str, object]:
    fixture_root = verify_root / "untrusted-listener"
    fixture_root.mkdir(parents=True, exist_ok=True)
    _copy_script_fixture(repo_root, fixture_root)

    port = _allocate_port()
    server_root = fixture_root / "server-root"
    server_root.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=str(server_root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        _wait_for_port(port, expect_listening=True)
        control_root = fixture_root / ".running" / "control"
        manifest_path = control_root / "envs" / "test.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(
                {
                    "environment": "test",
                    "host": "127.0.0.1",
                    "port": port,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        result = _run_stop_script(fixture_root, environment="test")
        assert result.returncode != 0, result.stdout
        assert "fail-closed" in (result.stderr or result.stdout), {
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        assert proc.poll() is None, "untrusted listener should still be alive"
        return {
            "returncode": result.returncode,
            "stderr": result.stderr.strip(),
        }
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
        _wait_for_port(port, expect_listening=False)


def _exercise_prod_guard(repo_root: Path, verify_root: Path) -> dict[str, object]:
    fixture_root = verify_root / "prod-guard"
    fixture_root.mkdir(parents=True, exist_ok=True)
    _copy_script_fixture(repo_root, fixture_root)

    result = _run_stop_script(fixture_root, environment="prod")
    assert result.returncode != 0, result.stdout
    assert "direct prod stop is disabled by default" in (result.stderr or result.stdout), {
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    return {
        "returncode": result.returncode,
        "stderr": result.stderr.strip(),
    }


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    verify_root = repo_root / ".test" / "runtime-stop-workflow-env"
    if verify_root.exists():
        shutil.rmtree(verify_root, ignore_errors=True)
    verify_root.mkdir(parents=True, exist_ok=True)

    payload = {
        "ok": True,
        "trusted_test_stop": _exercise_trusted_test_stop(repo_root, verify_root),
        "untrusted_listener_fail_closed": _exercise_untrusted_listener_fail_closed(repo_root, verify_root),
        "prod_guard": _exercise_prod_guard(repo_root, verify_root),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
