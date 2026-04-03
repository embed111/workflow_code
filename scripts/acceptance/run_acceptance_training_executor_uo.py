#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def call(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout_s: int = 60,
) -> tuple[int, dict[str, Any]]:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url=base_url + path, data=data, method=method, headers=headers)
    try:
        with urlopen(req, timeout=max(10, int(timeout_s))) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, (json.loads(body) if body else {})
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            payload_obj = json.loads(body) if body else {}
        except Exception:
            payload_obj = {"raw": body}
        return exc.code, payload_obj


def wait_health(base_url: str, timeout_s: int = 60) -> None:
    end_at = time.time() + timeout_s
    while time.time() < end_at:
        st, payload = call(base_url, "GET", "/healthz", None, timeout_s=10)
        if st == 200 and bool(payload.get("ok")):
            return
        time.sleep(0.5)
    raise RuntimeError("healthz timeout")


def find_edge() -> Path:
    candidates = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    for p in candidates:
        if p.exists() and p.is_file():
            return p
    raise RuntimeError("msedge not found")


def edge_shot(
    edge_path: Path,
    url: str,
    shot_path: Path,
    *,
    width: int = 1440,
    height: int = 980,
    budget_ms: int = 20000,
) -> None:
    shot_path.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for _attempt in range(3):
        profile_dir = shot_path.parent / ".edge_profile" / f"shot-{uuid.uuid4().hex}"
        profile_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            str(edge_path),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={profile_dir.as_posix()}",
            f"--window-size={int(width)},{int(height)}",
            f"--virtual-time-budget={max(1000, int(budget_ms))}",
            f"--screenshot={shot_path.as_posix()}",
            url,
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=180)
            if proc.returncode != 0:
                raise RuntimeError(f"edge screenshot failed: {proc.stderr}")
            return
        except Exception as exc:
            last_error = exc
            time.sleep(1.0)
        finally:
            try:
                import shutil

                shutil.rmtree(profile_dir, ignore_errors=True)
            except Exception:
                pass
    if last_error is not None:
        raise last_error


def pick_port(host: str, start_port: int = 18090, attempts: int = 40) -> int:
    for port in range(int(start_port), int(start_port) + int(attempts)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, int(port)))
            except OSError:
                continue
            return int(port)
    raise RuntimeError("no free port available")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def pick_training_agent(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    rows = [row for row in items if isinstance(row, dict)]
    if not rows:
        return None
    for preferred_id in ("Analyst2",):
        for row in rows:
            if str(row.get("agent_id") or "").strip() == preferred_id:
                return row
    for row in rows:
        if str(row.get("agent_id") or "").strip() != "Analyst":
            return row
    return rows[0]


def dump_audit_log(db_path: Path, *, queue_task_id: str) -> list[dict[str, Any]]:
    conn = sqlite3.connect(db_path.as_posix())
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT audit_id,action,operator,target_id,detail_json,created_at
            FROM training_audit_log
            WHERE target_id=?
              AND action IN ('start','finish')
            ORDER BY created_at DESC
            LIMIT 50
            """,
            (queue_task_id,),
        ).fetchall()
    finally:
        conn.close()
    items: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        record = {k: row[k] for k in row.keys()}
        record["_row_index"] = idx + 1
        items.append(record)
    return items


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="0 means auto-pick a free port")
    parser.add_argument("--budget-ms", type=int, default=22000)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    runtime_root = repo_root / ".runtime"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    evidence_root = repo_root / "logs" / "runs" / f"tc-executor-internal-{ts}"
    shots_dir = evidence_root / "screenshots"
    api_dir = evidence_root / "api"
    db_path = runtime_root / "state" / "workflow.db"
    evidence_root.mkdir(parents=True, exist_ok=True)
    shots_dir.mkdir(parents=True, exist_ok=True)
    api_dir.mkdir(parents=True, exist_ok=True)

    host = str(args.host)
    port = int(args.port) if int(args.port) > 0 else pick_port(host)
    base_url = f"http://{host}:{port}"

    server_stdout = evidence_root / "server_stdout.log"
    server_stderr = evidence_root / "server_stderr.log"
    cmd = [
        sys.executable,
        str(repo_root / "scripts" / "workflow_web_server.py"),
        "--host",
        host,
        "--port",
        str(port),
        "--root",
        runtime_root.as_posix(),
    ]
    proc = subprocess.Popen(
        cmd,
        cwd=repo_root.as_posix(),
        stdout=server_stdout.open("w", encoding="utf-8"),
        stderr=server_stderr.open("w", encoding="utf-8"),
    )
    try:
        wait_health(base_url, timeout_s=80)

        st_agents, agents_payload = call(base_url, "GET", "/api/training/agents?include_test_data=0", None, timeout_s=90)
        if st_agents != 200 or not bool(agents_payload.get("ok")):
            raise RuntimeError(f"list agents failed: status={st_agents}")
        agents_items = agents_payload.get("items") if isinstance(agents_payload, dict) else []
        pick = pick_training_agent(agents_items if isinstance(agents_items, list) else [])
        target_agent_id = str((pick or {}).get("agent_id") or "").strip()
        if not target_agent_id:
            raise RuntimeError("agent_id missing")

        goal = f"tc-executor-internal {ts}"
        plan_payload = {
            "target_agent_id": target_agent_id,
            "capability_goal": goal,
            "training_tasks": [f"executor task {ts} 1", f"executor task {ts} 2"],
            "acceptance_criteria": f"acceptance {ts}",
            "priority": "P0",
            "execution_engine": "workflow_native",
            "operator": "acceptance-script",
            "created_by": "acceptance-script",
        }
        st_plan, plan_resp = call(base_url, "POST", "/api/training/plans/manual", plan_payload, timeout_s=90)
        if st_plan != 200 or not bool(plan_resp.get("ok")):
            raise RuntimeError(f"create plan failed: status={st_plan}, payload={plan_resp}")
        write_json(api_dir / "create_plan.json", plan_resp)
        queue_task_id = str(plan_resp.get("queue_task_id") or "").strip()
        if not queue_task_id:
            raise RuntimeError("queue_task_id missing")

        edge = find_edge()

        def url_for(params: dict[str, str]) -> str:
            return base_url + "/?" + urlencode(params)

        shot1 = shots_dir / "01_create_no_trainer.png"
        edge_shot(edge, url_for({"tc_loop_mode": "create"}), shot1, width=1440, height=980, budget_ms=int(args.budget_ms))

        shot2 = shots_dir / "02_status_no_trainer.png"
        params2 = {
            "tc_loop_mode": "status",
            "tc_loop_tab": "score",
            "tc_loop_task": queue_task_id,
            "tc_loop_node": queue_task_id,
            "tc_loop_search": goal,
        }
        edge_shot(edge, url_for(params2), shot2, width=1440, height=980, budget_ms=int(args.budget_ms))

        st_exec, exec_resp = call(
            base_url,
            "POST",
            f"/api/training/queue/{queue_task_id}/execute",
            {"operator": "acceptance-script"},
            timeout_s=90,
        )
        if st_exec != 200 or not bool(exec_resp.get("ok")):
            raise RuntimeError(f"execute failed: status={st_exec}, payload={exec_resp}")
        write_json(api_dir / "execute_queue.json", exec_resp)

        shot3 = shots_dir / "03_status_executor_workflow.png"
        edge_shot(edge, url_for(params2), shot3, width=1440, height=980, budget_ms=int(args.budget_ms))

        audit_rows = dump_audit_log(db_path, queue_task_id=queue_task_id)
        if not audit_rows:
            raise RuntimeError("audit log missing start/finish records")
        write_json(api_dir / "training_audit_log_executor.json", {"queue_task_id": queue_task_id, "rows": audit_rows})

        summary_md = evidence_root / "summary.md"
        lines = [
            f"# Training Executor Evidence ({ts})",
            "",
            f"- base_url: {base_url}",
            f"- db_path: {db_path.as_posix()}",
            f"- server_stdout: {server_stdout.as_posix()}",
            f"- server_stderr: {server_stderr.as_posix()}",
            "",
            "## API",
            f"- create_plan: {(api_dir / 'create_plan.json').as_posix()}",
            f"- execute_queue: {(api_dir / 'execute_queue.json').as_posix()}",
            f"- training_audit_log: {(api_dir / 'training_audit_log_executor.json').as_posix()}",
            "",
            "## Screenshots",
            f"- 创建任务-无训练师选择: {shot1.resolve().as_posix()}",
            f"- 任务状态-无训练师选择: {shot2.resolve().as_posix()}",
            f"- 任务状态-执行主体workflow: {shot3.resolve().as_posix()}",
        ]
        summary_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

        ok = (
            shot1.exists()
            and shot2.exists()
            and shot3.exists()
            and bool(exec_resp.get("execution_engine"))
            and bool(audit_rows)
        )
        print(summary_md.as_posix())
        return 0 if ok else 1
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
