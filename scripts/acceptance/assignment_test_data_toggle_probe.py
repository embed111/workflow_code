#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe assignment test-data visibility under environment policy."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8130)
    parser.add_argument("--root", default=".")
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


def api_request(
    base_url: str,
    method: str,
    route: str,
    body: dict[str, Any] | None = None,
) -> tuple[int, Any]:
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


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch_db_graph_row(db_path: Path, ticket_id: str) -> dict[str, Any]:
    conn = sqlite3.connect(db_path.as_posix())
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT ticket_id,graph_name,source_workflow,external_request_id,is_test_data,scheduler_state,updated_at
            FROM assignment_graphs
            WHERE ticket_id=?
            LIMIT 1
            """,
            (ticket_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return {}
    return {name: row[name] for name in row.keys()}


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
    proc = subprocess.Popen(
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
    return proc, stdout_handle, stderr_handle


def stop_server(proc: subprocess.Popen[bytes], stdout_handle: Any, stderr_handle: Any) -> None:
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)
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
    proc, stdout_handle, stderr_handle = launch_server(
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
        stop_server(proc, stdout_handle, stderr_handle)


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
    workspace_root = Path(args.root).resolve()
    artifacts_dir = Path(args.artifacts_dir).resolve()
    logs_dir = Path(args.logs_dir).resolve()
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    evidence_root = artifacts_dir / "assignment-test-data-toggle-probe"
    log_root = logs_dir / "assignment-test-data-toggle-probe"
    if evidence_root.exists():
        shutil.rmtree(evidence_root, ignore_errors=True)
    if log_root.exists():
        shutil.rmtree(log_root, ignore_errors=True)
    evidence_root.mkdir(parents=True, exist_ok=True)
    log_root.mkdir(parents=True, exist_ok=True)
    api_dir = evidence_root / "api"
    api_dir.mkdir(parents=True, exist_ok=True)
    runtime_base = Path(os.getenv("TEST_TMP_DIR") or (workspace_root / ".test" / "runtime")).resolve()
    runtime_root, bootstrap_cfg = prepare_isolated_runtime_root(
        workspace_root,
        runtime_base / "assignment-test-data-toggle-probe",
        show_test_data=True,
    )
    runtime_db = runtime_root / "state" / "workflow.db"
    base_url = f"http://{args.host}:{args.port}"
    evidence_path = evidence_root / "summary.json"
    evidence: dict[str, Any] = {
        "workspace_root": str(workspace_root),
        "runtime_root": str(runtime_root),
        "runtime_db": str(runtime_db),
        "runtime_bootstrap_config": bootstrap_cfg,
        "runtime_config_path": str(runtime_root / "state" / "runtime-config.json"),
        "base_url": base_url,
        "stages": {},
    }

    try:
        with running_server(
            workspace_root,
            runtime_root,
            host=args.host,
            port=args.port,
            environment="prod",
            stdout_path=log_root / "prod-hidden-before.stdout.log",
            stderr_path=log_root / "prod-hidden-before.stderr.log",
        ):
            evidence["stages"]["prod_hidden_before"] = {"healthz": wait_for_health(base_url)}

            status, artifact_root = api_request(base_url, "GET", "/api/config/artifact-root")
            record_api(
                api_dir,
                stage="prod_hidden_before",
                name="artifact_root",
                method="GET",
                path="/api/config/artifact-root",
                payload=None,
                status=status,
                body=artifact_root,
            )
            assert_true(
                status == 200 and isinstance(artifact_root, dict) and artifact_root.get("ok"),
                "artifact root config unavailable",
            )

            status, hidden_cfg = api_request(base_url, "GET", "/api/config/show-test-data")
            record_api(
                api_dir,
                stage="prod_hidden_before",
                name="show_test_data",
                method="GET",
                path="/api/config/show-test-data",
                payload=None,
                status=status,
                body=hidden_cfg,
            )
            assert_true(
                status == 200 and isinstance(hidden_cfg, dict) and hidden_cfg.get("ok"),
                "show-test-data config unavailable in prod",
            )
            assert_true(hidden_cfg.get("show_test_data") is False, "prod should fail closed to hidden")
            assert_true(str(hidden_cfg.get("environment") or "").strip() == "prod", "prod policy should expose prod environment")

            status, hidden_bootstrap = api_request(
                base_url,
                "POST",
                "/api/assignments/test-data/bootstrap",
                {"operator": "assignment-test-data-toggle-probe"},
            )
            record_api(
                api_dir,
                stage="prod_hidden_before",
                name="bootstrap",
                method="POST",
                path="/api/assignments/test-data/bootstrap",
                payload={"operator": "assignment-test-data-toggle-probe"},
                status=status,
                body=hidden_bootstrap,
            )
            assert_true(status == 409, "bootstrap should be rejected in prod")
            assert_true(
                isinstance(hidden_bootstrap, dict)
                and str(hidden_bootstrap.get("code") or "").strip() == "assignment_test_data_hidden",
                "unexpected prod hidden bootstrap error code",
            )

            status, hidden_list = api_request(base_url, "GET", "/api/assignments")
            record_api(
                api_dir,
                stage="prod_hidden_before",
                name="assignments",
                method="GET",
                path="/api/assignments",
                payload=None,
                status=status,
                body=hidden_list,
            )
            assert_true(
                status == 200 and isinstance(hidden_list, dict) and hidden_list.get("ok"),
                "assignment list unavailable in prod",
            )
            assert_true(not list(hidden_list.get("items") or []), "prod hidden list should not expose test graphs")
            evidence["stages"]["prod_hidden_before"].update(
                {
                    "policy": hidden_cfg,
                    "artifact_root": artifact_root,
                    "hidden_bootstrap": hidden_bootstrap,
                    "hidden_list": hidden_list,
                }
            )

        with running_server(
            workspace_root,
            runtime_root,
            host=args.host,
            port=args.port,
            environment="test",
            stdout_path=log_root / "test-visible.stdout.log",
            stderr_path=log_root / "test-visible.stderr.log",
        ):
            evidence["stages"]["test_visible"] = {"healthz": wait_for_health(base_url)}

            status, visible_cfg = api_request(base_url, "GET", "/api/config/show-test-data")
            record_api(
                api_dir,
                stage="test_visible",
                name="show_test_data",
                method="GET",
                path="/api/config/show-test-data",
                payload=None,
                status=status,
                body=visible_cfg,
            )
            assert_true(
                status == 200 and isinstance(visible_cfg, dict) and visible_cfg.get("ok"),
                "show-test-data config unavailable in test",
            )
            assert_true(visible_cfg.get("show_test_data") is True, "test environment should expose configured test data policy")
            assert_true(str(visible_cfg.get("environment") or "").strip() == "test", "test policy should expose test environment")

            status, bootstrap = api_request(
                base_url,
                "POST",
                "/api/assignments/test-data/bootstrap",
                {"operator": "assignment-test-data-toggle-probe"},
            )
            record_api(
                api_dir,
                stage="test_visible",
                name="bootstrap",
                method="POST",
                path="/api/assignments/test-data/bootstrap",
                payload={"operator": "assignment-test-data-toggle-probe"},
                status=status,
                body=bootstrap,
            )
            assert_true(
                status == 200 and isinstance(bootstrap, dict) and bootstrap.get("ok"),
                "bootstrap assignment test data failed in test",
            )
            ticket_id = str(bootstrap.get("ticket_id") or "").strip()
            assert_true(ticket_id, "bootstrap ticket_id missing")
            evidence["ticket_id"] = ticket_id

            status, visible_list = api_request(base_url, "GET", "/api/assignments")
            record_api(
                api_dir,
                stage="test_visible",
                name="assignments",
                method="GET",
                path="/api/assignments",
                payload=None,
                status=status,
                body=visible_list,
            )
            assert_true(
                status == 200 and isinstance(visible_list, dict) and visible_list.get("ok"),
                "visible assignment list unavailable",
            )
            visible_items = list(visible_list.get("items") or [])
            visible_graph = next(
                (
                    item
                    for item in visible_items
                    if str((item or {}).get("ticket_id") or "").strip() == ticket_id
                ),
                {},
            )
            assert_true(bool(visible_graph), "bootstrapped test graph missing from visible list")
            assert_true(bool(visible_graph.get("is_test_data")), "bootstrapped graph must be marked as test data")

            graph_path = f"/api/assignments/{ticket_id}/graph?history_loaded=24&history_batch_size=24"
            status, graph_payload = api_request(base_url, "GET", graph_path)
            record_api(
                api_dir,
                stage="test_visible",
                name="graph",
                method="GET",
                path=graph_path,
                payload=None,
                status=status,
                body=graph_payload,
            )
            assert_true(
                status == 200 and isinstance(graph_payload, dict) and graph_payload.get("ok"),
                "graph fetch after bootstrap failed",
            )
            graph = graph_payload.get("graph") or {}
            counts = ((graph_payload.get("metrics_summary") or {}).get("status_counts") or {})
            assert_true(bool(graph.get("is_test_data")), "graph payload should expose is_test_data=true")
            assert_true(
                int((graph_payload.get("metrics_summary") or {}).get("total_nodes") or 0) == 20,
                "prototype graph should seed 20 nodes",
            )
            assert_true(int(counts.get("running") or 0) == 1, "prototype graph should include one running node")
            assert_true(int(counts.get("failed") or 0) == 1, "prototype graph should include one failed node")

            preview_path = f"/api/assignments/{ticket_id}/nodes/T8/artifact-preview"
            status, preview_payload = api_request(base_url, "GET", preview_path)
            record_api(
                api_dir,
                stage="test_visible",
                name="artifact_preview",
                method="GET",
                path=preview_path,
                payload=None,
                status=status,
                body=preview_payload,
            )
            assert_true(status == 200 and isinstance(preview_payload, str), "artifact preview for seeded node T8 failed")
            assert_true(len(preview_payload.strip()) > 0, "artifact preview should not be empty")

            db_graph_row = fetch_db_graph_row(runtime_db, ticket_id)
            assert_true(bool(db_graph_row), "bootstrapped graph missing from runtime db")
            assert_true(int(db_graph_row.get("is_test_data") or 0) == 1, "runtime db graph should mark is_test_data=1")

            evidence["stages"]["test_visible"].update(
                {
                    "policy": visible_cfg,
                    "bootstrap": bootstrap,
                    "visible_list_count": len(visible_items),
                    "graph_summary": graph_payload.get("metrics_summary"),
                    "db_graph_row": db_graph_row,
                    "artifact_preview_excerpt": preview_payload[:240],
                }
            )

        with running_server(
            workspace_root,
            runtime_root,
            host=args.host,
            port=args.port,
            environment="prod",
            stdout_path=log_root / "prod-hidden-after.stdout.log",
            stderr_path=log_root / "prod-hidden-after.stderr.log",
        ):
            evidence["stages"]["prod_hidden_after"] = {"healthz": wait_for_health(base_url)}

            status, hidden_cfg_after = api_request(base_url, "GET", "/api/config/show-test-data")
            record_api(
                api_dir,
                stage="prod_hidden_after",
                name="show_test_data",
                method="GET",
                path="/api/config/show-test-data",
                payload=None,
                status=status,
                body=hidden_cfg_after,
            )
            assert_true(
                status == 200 and isinstance(hidden_cfg_after, dict) and hidden_cfg_after.get("ok"),
                "show-test-data config unavailable after switching back to prod",
            )
            assert_true(hidden_cfg_after.get("show_test_data") is False, "prod should ignore runtime-config show_test_data=true")

            status, hidden_again = api_request(base_url, "GET", "/api/assignments")
            record_api(
                api_dir,
                stage="prod_hidden_after",
                name="assignments",
                method="GET",
                path="/api/assignments",
                payload=None,
                status=status,
                body=hidden_again,
            )
            assert_true(
                status == 200 and isinstance(hidden_again, dict) and hidden_again.get("ok"),
                "assignment list unavailable after hide",
            )
            hidden_again_items = list(hidden_again.get("items") or [])
            assert_true(
                all(str((item or {}).get("ticket_id") or "").strip() != str(evidence.get("ticket_id") or "") for item in hidden_again_items),
                "test graph should disappear in prod after restart",
            )

            hidden_graph_path = f"/api/assignments/{evidence['ticket_id']}/graph?history_loaded=24&history_batch_size=24"
            status, hidden_graph = api_request(base_url, "GET", hidden_graph_path)
            record_api(
                api_dir,
                stage="prod_hidden_after",
                name="graph",
                method="GET",
                path=hidden_graph_path,
                payload=None,
                status=status,
                body=hidden_graph,
            )
            assert_true(status == 404, "hidden test graph should return 404 in prod")
            assert_true(
                isinstance(hidden_graph, dict)
                and str(hidden_graph.get("code") or "").strip() == "assignment_graph_not_found",
                "unexpected hidden graph error code",
            )

            hidden_preview_path = f"/api/assignments/{evidence['ticket_id']}/nodes/T8/artifact-preview"
            status, hidden_preview = api_request(base_url, "GET", hidden_preview_path)
            record_api(
                api_dir,
                stage="prod_hidden_after",
                name="artifact_preview",
                method="GET",
                path=hidden_preview_path,
                payload=None,
                status=status,
                body=hidden_preview,
            )
            assert_true(status == 404, "hidden test artifact preview should return 404 in prod")

            status, hidden_bootstrap_again = api_request(
                base_url,
                "POST",
                "/api/assignments/test-data/bootstrap",
                {"operator": "assignment-test-data-toggle-probe"},
            )
            record_api(
                api_dir,
                stage="prod_hidden_after",
                name="bootstrap",
                method="POST",
                path="/api/assignments/test-data/bootstrap",
                payload={"operator": "assignment-test-data-toggle-probe"},
                status=status,
                body=hidden_bootstrap_again,
            )
            assert_true(status == 409, "bootstrap should stay rejected in prod")
            evidence["stages"]["prod_hidden_after"].update(
                {
                    "policy": hidden_cfg_after,
                    "hidden_list": hidden_again,
                    "hidden_graph": hidden_graph,
                    "hidden_artifact_preview": hidden_preview,
                    "hidden_bootstrap": hidden_bootstrap_again,
                }
            )

        evidence["ok"] = True
        write_json(evidence_path, evidence)
        return 0
    finally:
        if not evidence_path.exists():
            write_json(evidence_path, evidence)


if __name__ == "__main__":
    raise SystemExit(main())
