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
from concurrent.futures import ThreadPoolExecutor
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
    timeout_s: int = 90,
) -> tuple[int, dict[str, Any]]:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(base_url + path, data=data, method=method, headers=headers)
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


def call_many(base_url: str, method: str, path: str, *, count: int) -> list[tuple[int, dict[str, Any]]]:
    with ThreadPoolExecutor(max_workers=max(1, int(count))) as pool:
        futures = [pool.submit(call, base_url, method, path, None) for _ in range(max(1, int(count)))]
        return [future.result() for future in futures]


def wait_health(base_url: str, timeout_s: int = 80) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status, payload = call(base_url, "GET", "/healthz", None, timeout_s=10)
        if status == 200 and bool(payload.get("ok")):
            return
        time.sleep(0.5)
    raise RuntimeError("healthz timeout")


def pick_port(host: str, start_port: int = 18090, attempts: int = 50) -> int:
    for port in range(start_port, start_port + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError("no free port")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def find_edge() -> Path:
    for candidate in (
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ):
        if candidate.exists() and candidate.is_file():
            return candidate
    raise RuntimeError("msedge not found")


def edge_shot(edge_path: Path, url: str, shot_path: Path, *, width: int, height: int, budget_ms: int) -> None:
    shot_path.parent.mkdir(parents=True, exist_ok=True)
    profile_dir = shot_path.parent / ".edge_profile" / f"shot-{uuid.uuid4().hex}"
    profile_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(edge_path),
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        f"--user-data-dir={profile_dir.as_posix()}",
        f"--window-size={width},{height}",
        f"--virtual-time-budget={budget_ms}",
        f"--screenshot={shot_path.as_posix()}",
        url,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=180)
        if proc.returncode != 0:
            raise RuntimeError(f"edge screenshot failed: {proc.stderr}")
    finally:
        try:
            import shutil

            shutil.rmtree(profile_dir, ignore_errors=True)
        except Exception:
            pass


def pick_training_agent(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    rows = [row for row in items if isinstance(row, dict)]
    for preferred_id in ("Analyst2",):
        for row in rows:
            if str(row.get("agent_id") or "").strip() == preferred_id:
                return row
    for row in rows:
        if str(row.get("agent_id") or "").strip() != "Analyst":
            return row
    return rows[0] if rows else None


def dump_query(db_path: Path, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    conn = sqlite3.connect(db_path.as_posix())
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return [{key: row[key] for key in row.keys()} for row in rows]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--budget-ms", type=int, default=24000)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    runtime_root = repo_root / ".runtime"
    db_path = runtime_root / "state" / "workflow.db"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_root = repo_root / "logs" / "runs" / f"tc-loop-evolution-{ts}"
    api_dir = run_root / "api"
    db_dir = run_root / "db"
    shots_dir = run_root / "screenshots"
    run_root.mkdir(parents=True, exist_ok=True)
    api_dir.mkdir(parents=True, exist_ok=True)
    db_dir.mkdir(parents=True, exist_ok=True)
    shots_dir.mkdir(parents=True, exist_ok=True)

    host = str(args.host)
    port = int(args.port) if int(args.port) > 0 else pick_port(host)
    base_url = f"http://{host}:{port}"
    stdout_path = run_root / "server_stdout.log"
    stderr_path = run_root / "server_stderr.log"
    proc = subprocess.Popen(
        [
            sys.executable,
            str(repo_root / "scripts" / "workflow_web_server.py"),
            "--host",
            host,
            "--port",
            str(port),
            "--root",
            runtime_root.as_posix(),
        ],
        cwd=repo_root.as_posix(),
        stdout=stdout_path.open("w", encoding="utf-8"),
        stderr=stderr_path.open("w", encoding="utf-8"),
    )
    try:
        wait_health(base_url)
        write_json(api_dir / "concurrent_training_agents.json", {"responses": call_many(base_url, "GET", "/api/training/agents", count=4)})

        st_agents, agents_payload = call(base_url, "GET", "/api/training/agents?include_test_data=0")
        if st_agents != 200 or not bool(agents_payload.get("ok")):
            raise RuntimeError(f"list agents failed: status={st_agents}")
        items = agents_payload.get("items") if isinstance(agents_payload, dict) else []
        picked = pick_training_agent(items if isinstance(items, list) else [])
        target_agent_id = str((picked or {}).get("agent_id") or "").strip()
        if not target_agent_id:
            raise RuntimeError("target agent missing")

        goal = f"tc-loop-real-backend {ts}"
        plan_payload = {
            "target_agent_id": target_agent_id,
            "capability_goal": goal,
            "training_tasks": [f"round task {ts} A", f"round task {ts} B"],
            "acceptance_criteria": f"acceptance {ts}",
            "priority": "P0",
            "operator": "acceptance-script",
            "created_by": "acceptance-script",
            "execution_engine": "workflow_native",
        }
        st_plan, plan_resp = call(base_url, "POST", "/api/training/plans/manual", plan_payload)
        if st_plan != 200 or not bool(plan_resp.get("ok")):
            raise RuntimeError(f"create plan failed: {plan_resp}")
        write_json(api_dir / "create_plan.json", plan_resp)
        queue_round1 = str(plan_resp.get("queue_task_id") or "").strip()
        if not queue_round1:
            raise RuntimeError("queue_round1 missing")

        st_exec1, exec1 = call(base_url, "POST", f"/api/training/queue/{queue_round1}/execute", {"operator": "acceptance-script"})
        if st_exec1 != 200 or not bool(exec1.get("ok")):
            raise RuntimeError(f"execute round1 failed: {exec1}")
        write_json(api_dir / "execute_round1.json", exec1)

        st_loop1, loop1 = call(base_url, "GET", f"/api/training/queue/{queue_round1}/loop")
        st_detail1, detail1 = call(base_url, "GET", f"/api/training/queue/{queue_round1}/status-detail")
        if st_loop1 != 200 or not bool(loop1.get("ok")) or st_detail1 != 200 or not bool(detail1.get("ok")):
            raise RuntimeError("round1 loop/detail fetch failed")
        write_json(api_dir / "loop_round1.json", loop1)
        write_json(api_dir / "status_detail_round1.json", detail1)
        loop_id = str(loop1.get("loop_id") or "").strip()
        if not loop_id:
            raise RuntimeError("loop_id missing")

        edge = find_edge()

        def page_url(task_id: str, tab: str, node_id: str = "") -> str:
            return base_url + "/?" + urlencode(
                {
                    "tc_loop_mode": "status",
                    "tc_loop_tab": tab,
                    "tc_loop_task": task_id,
                    "tc_loop_node": node_id or task_id,
                    "tc_loop_search": goal,
                }
            )

        screenshots: list[tuple[str, str, str]] = []
        for filename, title, tab in (
            ("01_status_overview_round1.png", "状态页-当前概览", "overview"),
            ("02_status_workset_round1.png", "状态页-工作集变化", "workset"),
            ("03_status_eval_round1.png", "状态页-三轮评测", "eval"),
            ("04_status_history_round1.png", "状态页-历史记录", "history"),
            ("05_before_enter_next_round.png", "进入下一轮前", "overview"),
        ):
            shot = shots_dir / filename
            edge_shot(edge, page_url(queue_round1, tab), shot, width=1440, height=980, budget_ms=int(args.budget_ms))
            screenshots.append((title, shot.as_posix(), page_url(queue_round1, tab)))

        st_enter, enter_resp = call(
            base_url,
            "POST",
            f"/api/training/queue/{queue_round1}/loop/enter-next-round",
            {"operator": "acceptance-script", "reason": "acceptance enter next round"},
        )
        if st_enter != 200 or not bool(enter_resp.get("ok")):
            raise RuntimeError(f"enter next round failed: {enter_resp}")
        write_json(api_dir / "enter_next_round.json", enter_resp)
        queue_round2 = str(enter_resp.get("created_queue_task_id") or "").strip()
        if not queue_round2:
            raise RuntimeError("queue_round2 missing")

        st_loop2q, loop2q = call(base_url, "GET", f"/api/training/queue/{queue_round2}/loop")
        st_detail2q, detail2q = call(base_url, "GET", f"/api/training/queue/{queue_round2}/status-detail")
        if st_loop2q != 200 or not bool(loop2q.get("ok")) or st_detail2q != 200 or not bool(detail2q.get("ok")):
            raise RuntimeError("round2 queued loop/detail fetch failed")
        write_json(api_dir / "loop_round2_queued.json", loop2q)
        write_json(api_dir / "status_detail_round2_queued.json", detail2q)
        shot_after_enter = shots_dir / "06_after_enter_next_round.png"
        edge_shot(edge, page_url(queue_round2, "overview"), shot_after_enter, width=1440, height=980, budget_ms=int(args.budget_ms))
        screenshots.append(("进入下一轮后", shot_after_enter.as_posix(), page_url(queue_round2, "overview")))

        st_exec2, exec2 = call(base_url, "POST", f"/api/training/queue/{queue_round2}/execute", {"operator": "acceptance-script"})
        if st_exec2 != 200 or not bool(exec2.get("ok")):
            raise RuntimeError(f"execute round2 failed: {exec2}")
        write_json(api_dir / "execute_round2.json", exec2)

        st_loop2b, loop2b = call(base_url, "GET", f"/api/training/queue/{queue_round2}/loop")
        st_detail2b, detail2b = call(base_url, "GET", f"/api/training/queue/{queue_round2}/status-detail")
        if st_loop2b != 200 or not bool(loop2b.get("ok")) or st_detail2b != 200 or not bool(detail2b.get("ok")):
            raise RuntimeError("round2 before rollback fetch failed")
        write_json(api_dir / "loop_round2_before_rollback.json", loop2b)
        write_json(api_dir / "status_detail_round2_before_rollback.json", detail2b)
        shot_before_rb = shots_dir / "07_before_rollback_round_increment.png"
        edge_shot(edge, page_url(queue_round2, "eval"), shot_before_rb, width=1440, height=980, budget_ms=int(args.budget_ms))
        screenshots.append(("回退本轮新增前", shot_before_rb.as_posix(), page_url(queue_round2, "eval")))

        st_rb, rollback_resp = call(
            base_url,
            "POST",
            f"/api/training/queue/{queue_round2}/loop/rollback-round-increment",
            {"operator": "acceptance-script", "reason": "acceptance rollback round increment"},
        )
        if st_rb != 200 or not bool(rollback_resp.get("ok")):
            raise RuntimeError(f"rollback round increment failed: {rollback_resp}")
        write_json(api_dir / "rollback_round_increment.json", rollback_resp)

        st_loop2a, loop2a = call(base_url, "GET", f"/api/training/queue/{queue_round2}/loop")
        st_detail2a, detail2a = call(base_url, "GET", f"/api/training/queue/{queue_round2}/status-detail")
        if st_loop2a != 200 or not bool(loop2a.get("ok")) or st_detail2a != 200 or not bool(detail2a.get("ok")):
            raise RuntimeError("round2 after rollback fetch failed")
        write_json(api_dir / "loop_after_rollback.json", loop2a)
        write_json(api_dir / "status_detail_after_rollback.json", detail2a)
        rb_node_id = str(rollback_resp.get("rollback_node_id") or rollback_resp.get("current_node_id") or "").strip()
        shot_after_rb = shots_dir / "08_after_rollback_round_increment.png"
        edge_shot(edge, page_url(queue_round2, "history", rb_node_id), shot_after_rb, width=1440, height=980, budget_ms=int(args.budget_ms))
        screenshots.append(("回退本轮新增后", shot_after_rb.as_posix(), page_url(queue_round2, "history", rb_node_id)))

        queue_ids = (queue_round1, queue_round2)
        write_json(
            db_dir / "training_eval_run.json",
            dump_query(
                db_path,
                "SELECT * FROM training_eval_run WHERE queue_task_id IN (?,?) ORDER BY queue_task_id,run_index",
                queue_ids,
            ),
        )
        write_json(
            db_dir / "training_loop_state.json",
            dump_query(db_path, "SELECT * FROM training_loop_state WHERE loop_id=?", (loop_id,)),
        )
        write_json(
            db_dir / "training_run.json",
            dump_query(
                db_path,
                "SELECT * FROM training_run WHERE queue_task_id IN (?,?) ORDER BY updated_at",
                queue_ids,
            ),
        )
        write_json(
            db_dir / "training_audit_log.json",
            dump_query(
                db_path,
                "SELECT * FROM training_audit_log WHERE target_id IN (?,?,?) ORDER BY created_at,audit_id",
                (loop_id, queue_round1, queue_round2),
            ),
        )

        summary_lines = [
            f"# Training Loop Real Backend Evidence ({ts})",
            "",
            f"- base_url: {base_url}",
            f"- loop_id: {loop_id}",
            f"- queue_round1: {queue_round1}",
            f"- queue_round2: {queue_round2}",
            f"- db_path: {db_path.as_posix()}",
            f"- server_stdout: {stdout_path.as_posix()}",
            f"- server_stderr: {stderr_path.as_posix()}",
            "",
            "## API",
        ]
        for path in sorted(api_dir.glob("*.json")):
            summary_lines.append(f"- {path.name}: {path.as_posix()}")
        summary_lines.extend(["", "## DB"])
        for path in sorted(db_dir.glob("*.json")):
            summary_lines.append(f"- {path.name}: {path.as_posix()}")
        summary_lines.extend(["", "## Screenshots"])
        for title, path, url in screenshots:
            summary_lines.append(f"- {title}: {path}")
            summary_lines.append(f"  url: {url}")
        summary_path = run_root / "summary.md"
        summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
        print(summary_path.as_posix())
        return 0
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
