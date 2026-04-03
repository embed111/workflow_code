#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlencode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Browser screenshot regression for assignment center.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8131)
    parser.add_argument(
        "--artifacts-dir",
        default=os.getenv("TEST_ARTIFACTS_DIR") or ".test/evidence",
    )
    parser.add_argument(
        "--logs-dir",
        default=os.getenv("TEST_LOG_DIR") or ".test/evidence",
    )
    return parser.parse_args()


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


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
        with urllib.request.urlopen(request, timeout=20) as response:
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


def load_workspace_runtime_config(workspace_root: Path) -> dict[str, Any]:
    config_path = workspace_root / ".runtime" / "state" / "runtime-config.json"
    if not config_path.exists():
        return {}
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def prepare_isolated_runtime_root(
    workspace_root: Path,
    runtime_root: Path,
    *,
    show_test_data: bool,
) -> tuple[Path, dict[str, Any]]:
    runtime_root = runtime_root.resolve()
    state_dir = runtime_root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    source_cfg = load_workspace_runtime_config(workspace_root)
    bootstrap_cfg: dict[str, Any] = {"show_test_data": bool(show_test_data)}
    agent_search_root = str(source_cfg.get("agent_search_root") or "").strip()
    if agent_search_root:
        bootstrap_cfg["agent_search_root"] = agent_search_root
    (state_dir / "runtime-config.json").write_text(
        json.dumps(bootstrap_cfg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return runtime_root, bootstrap_cfg


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
    matched = re.search(
        r"<pre[^>]*id=['\"]assignmentCenterProbeOutput['\"][^>]*>(.*?)</pre>",
        str(dom_text or ""),
        flags=re.I | re.S,
    )
    if not matched:
        raise RuntimeError("assignmentCenterProbeOutput_not_found")
    raw = html.unescape(matched.group(1) or "").strip()
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


def launch_server(
    workspace_root: Path,
    runtime_root: Path,
    *,
    host: str,
    port: int,
    environment: str,
    stdout_path: Path,
    stderr_path: Path,
) -> tuple[subprocess.Popen[bytes], Any, Any]:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_handle = stdout_path.open("wb")
    stderr_handle = stderr_path.open("wb")
    env = os.environ.copy()
    env["WORKFLOW_RUNTIME_ENV"] = str(environment or "").strip()
    server = subprocess.Popen(
        [
            sys.executable,
            "scripts/workflow_web_server.py",
            "--root",
            str(runtime_root),
            "--host",
            host,
            "--port",
            str(port),
        ],
        cwd=str(workspace_root),
        stdout=stdout_handle,
        stderr=stderr_handle,
        env=env,
    )
    return server, stdout_handle, stderr_handle


def stop_server(server: subprocess.Popen[bytes], stdout_handle: Any, stderr_handle: Any) -> None:
    try:
        server.terminate()
        server.wait(timeout=10)
    except subprocess.TimeoutExpired:
        server.kill()
        server.wait(timeout=10)
    finally:
        stdout_handle.close()
        stderr_handle.close()


@contextmanager
def running_server(
    workspace_root: Path,
    runtime_root: Path,
    *,
    host: str,
    port: int,
    environment: str,
    stdout_path: Path,
    stderr_path: Path,
) -> Iterator[None]:
    server, stdout_handle, stderr_handle = launch_server(
        workspace_root,
        runtime_root,
        host=host,
        port=port,
        environment=environment,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )
    try:
        yield
    finally:
        stop_server(server, stdout_handle, stderr_handle)


def record_api(
    api_dir: Path,
    *,
    stage: str,
    name: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None,
    status: int,
    body: Any,
) -> str:
    file_path = api_dir / f"{stage}-{name}.json"
    write_json(
        file_path,
        {
            "request": {"method": method, "path": path, "payload": payload},
            "response": {"status": status, "body": body},
        },
    )
    return file_path.as_posix()


def main() -> int:
    args = parse_args()
    repo_root = Path(args.root).resolve()
    artifacts_dir = Path(args.artifacts_dir).resolve()
    logs_dir = Path(args.logs_dir).resolve()
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    evidence_root = artifacts_dir / "assignment-browser-regression"
    log_root = logs_dir / "assignment-browser-regression"
    if evidence_root.exists():
        shutil.rmtree(evidence_root, ignore_errors=True)
    if log_root.exists():
        shutil.rmtree(log_root, ignore_errors=True)
    api_dir = evidence_root / "api"
    shots_dir = evidence_root / "screenshots"
    api_dir.mkdir(parents=True, exist_ok=True)
    shots_dir.mkdir(parents=True, exist_ok=True)
    log_root.mkdir(parents=True, exist_ok=True)
    runtime_base = Path(os.getenv("TEST_TMP_DIR") or (repo_root / ".test" / "runtime")).resolve()
    runtime_root, bootstrap_cfg = prepare_isolated_runtime_root(
        repo_root,
        runtime_base / "assignment-browser-regression",
        show_test_data=True,
    )
    base_url = f"http://{args.host}:{args.port}"
    edge_path = find_edge()
    evidence: dict[str, Any] = {
        "repo_root": str(repo_root),
        "runtime_root": str(runtime_root),
        "runtime_bootstrap_config": bootstrap_cfg,
        "base_url": base_url,
        "edge_path": str(edge_path),
        "api": {},
        "screenshots": {},
    }

    try:
        with running_server(
            repo_root,
            runtime_root,
            host=args.host,
            port=args.port,
            environment="test",
            stdout_path=log_root / "test-visible.stdout.log",
            stderr_path=log_root / "test-visible.stderr.log",
        ):
            evidence["test_healthz"] = wait_for_health(base_url)

            status, agents = api_request(base_url, "GET", "/api/agents")
            assert_true(status == 200 and isinstance(agents, dict) and agents.get("ok"), "agents api unavailable")
            evidence["api"]["agents_test"] = record_api(
                api_dir,
                stage="test_visible",
                name="agents",
                method="GET",
                path="/api/agents",
                payload=None,
                status=status,
                body=agents,
            )

            status, policy_test = api_request(base_url, "GET", "/api/config/show-test-data")
            assert_true(status == 200 and isinstance(policy_test, dict) and policy_test.get("ok"), "test policy unavailable")
            assert_true(policy_test.get("show_test_data") is True, "test environment should expose test data")
            evidence["api"]["policy_test"] = record_api(
                api_dir,
                stage="test_visible",
                name="policy",
                method="GET",
                path="/api/config/show-test-data",
                payload=None,
                status=status,
                body=policy_test,
            )

            configured_artifact_root = (evidence_root / "task-output").resolve()
            payload_artifact_root = {"artifact_root": configured_artifact_root.as_posix()}
            status, body_artifact_root = api_request(
                base_url,
                "POST",
                "/api/config/artifact-root",
                payload_artifact_root,
            )
            assert_true(
                status == 200 and isinstance(body_artifact_root, dict) and body_artifact_root.get("ok"),
                "set task artifact root failed",
            )
            evidence["api"]["artifact_root"] = record_api(
                api_dir,
                stage="test_visible",
                name="artifact_root",
                method="POST",
                path="/api/config/artifact-root",
                payload=payload_artifact_root,
                status=status,
                body=body_artifact_root,
            )
            evidence["artifact_root"] = str(body_artifact_root.get("artifact_root") or "")

            payload_bootstrap = {"operator": "assignment-browser-regression"}
            status, body_bootstrap = api_request(
                base_url,
                "POST",
                "/api/assignments/test-data/bootstrap",
                payload_bootstrap,
            )
            assert_true(
                status == 200 and isinstance(body_bootstrap, dict) and body_bootstrap.get("ok"),
                "bootstrap assignment test graph failed",
            )
            evidence["api"]["bootstrap"] = record_api(
                api_dir,
                stage="test_visible",
                name="bootstrap_assignment_test_graph",
                method="POST",
                path="/api/assignments/test-data/bootstrap",
                payload=payload_bootstrap,
                status=status,
                body=body_bootstrap,
            )
            ticket_id = str(body_bootstrap.get("ticket_id") or "").strip()
            assert_true(ticket_id, "bootstrapped ticket_id missing")
            evidence["ticket_id"] = ticket_id

            visible_shot, visible_probe_file, visible_probe = capture_probe(
                edge_path,
                base_url,
                evidence_root,
                "task_center_visible",
                "default",
                {
                    "assignment_probe_node": "T20",
                    "assignment_probe_delay_ms": "1200",
                },
            )
            assert_true(bool(visible_probe.get("pass")), f"visible probe failed: {visible_probe}")
            evidence["screenshots"]["visible"] = {
                "image": visible_shot,
                "probe": visible_probe_file,
                "result": visible_probe,
            }

        with running_server(
            repo_root,
            runtime_root,
            host=args.host,
            port=args.port,
            environment="prod",
            stdout_path=log_root / "prod-hidden.stdout.log",
            stderr_path=log_root / "prod-hidden.stderr.log",
        ):
            evidence["prod_healthz"] = wait_for_health(base_url)

            status, policy_prod = api_request(base_url, "GET", "/api/config/show-test-data")
            assert_true(status == 200 and isinstance(policy_prod, dict) and policy_prod.get("ok"), "prod policy unavailable")
            assert_true(policy_prod.get("show_test_data") is False, "prod should hide test data")
            evidence["api"]["policy_prod"] = record_api(
                api_dir,
                stage="prod_hidden",
                name="policy",
                method="GET",
                path="/api/config/show-test-data",
                payload=None,
                status=status,
                body=policy_prod,
            )

            hidden_shot, hidden_probe_file, hidden_probe = capture_probe(
                edge_path,
                base_url,
                evidence_root,
                "task_center_hidden",
                "hidden",
                {
                    "assignment_probe_delay_ms": "900",
                },
            )
            assert_true(bool(hidden_probe.get("pass")), f"hidden probe failed: {hidden_probe}")
            evidence["screenshots"]["hidden"] = {
                "image": hidden_shot,
                "probe": hidden_probe_file,
                "result": hidden_probe,
            }

            status, hidden_list = api_request(base_url, "GET", "/api/assignments")
            assert_true(
                status == 200 and isinstance(hidden_list, dict) and hidden_list.get("ok"),
                "hidden assignment list unavailable",
            )
            evidence["api"]["assignments_hidden"] = record_api(
                api_dir,
                stage="prod_hidden",
                name="assignments",
                method="GET",
                path="/api/assignments",
                payload=None,
                status=status,
                body=hidden_list,
            )
            evidence["hidden_assignment_count"] = len(list(hidden_list.get("items") or []))
            evidence["ok"] = True

        write_json(evidence_root / "summary.json", evidence)
        return 0
    finally:
        if not (evidence_root / "summary.json").exists():
            write_json(evidence_root / "summary.json", evidence)


if __name__ == "__main__":
    raise SystemExit(main())
