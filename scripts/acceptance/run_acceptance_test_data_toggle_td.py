#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import time
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
) -> tuple[int, dict[str, Any]]:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url=base_url + path, data=data, method=method, headers=headers)
    try:
        with urlopen(req, timeout=30) as resp:
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
        st, payload = call(base_url, "GET", "/healthz")
        if st == 200 and bool(payload.get("ok")):
            return
        time.sleep(0.5)
    raise RuntimeError("healthz timeout")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def dump_sql(db_path: Path, sql: str, params: tuple[Any, ...], out_path: Path) -> None:
    conn = sqlite3.connect(db_path.as_posix())
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    write_json(
        out_path,
        [{"_row_index": i + 1, **{k: row[k] for k in row.keys()}} for i, row in enumerate(rows)],
    )


def fixture_agents(workspace_root: Path) -> tuple[str, str]:
    (workspace_root / "workflow").mkdir(parents=True, exist_ok=True)
    (workspace_root / "workflow" / "README.md").write_text("fixture\n", encoding="utf-8")

    prod_dir = workspace_root / "alpha-agent"
    sys_dir = workspace_root / "workflow" / "state" / "system-agent"
    prod_dir.mkdir(parents=True, exist_ok=True)
    sys_dir.mkdir(parents=True, exist_ok=True)

    agents_md = "\n".join(
        [
            "# AGENT",
            "",
            "## 角色定位",
            "你是测试数据开关统一治理助手。",
            "",
            "## 会话目标",
            "保证全局配置一致、可追溯、可验收。",
            "",
            "## 职责边界",
            "### must",
            "- 输出可验证证据。",
            "- 对失败场景给出明确错误信息。",
            "",
            "### must_not",
            "- 不绕过全局配置真值。",
            "- 不静默吞掉写入失败。",
        ]
    )
    (prod_dir / "AGENTS.md").write_text(agents_md + "\n", encoding="utf-8")
    (sys_dir / "AGENTS.md").write_text(agents_md + "\n", encoding="utf-8")
    return "alpha-agent", "system-agent"


def seed_dashboard_rows(
    db_path: Path,
    workspace_root: Path,
    prod_agent_name: str,
    system_agent_name: str,
) -> None:
    now_text = datetime.now().astimezone().isoformat(timespec="seconds")
    root_text = workspace_root.as_posix()
    prod_agents_path = (workspace_root / prod_agent_name / "AGENTS.md").as_posix()
    system_agents_path = (
        workspace_root / "workflow" / "state" / system_agent_name / "AGENTS.md"
    ).as_posix()
    rows_sessions = [
        (
            "sess-td-prod",
            prod_agent_name,
            "hash-prod",
            now_text,
            prod_agents_path,
            "v-prod",
            root_text,
            root_text,
            0,
            "active",
            now_text,
        ),
        (
            "sess-td-test",
            system_agent_name,
            "hash-test",
            now_text,
            system_agents_path,
            "v-test",
            root_text,
            root_text,
            1,
            "active",
            now_text,
        ),
    ]
    rows_events = [
        (
            "evt-td-prod-1",
            now_text,
            "sess-td-prod",
            "user",
            "chat",
            "send_message",
            "success",
            12,
            "",
            "[]",
            "",
        ),
        (
            "evt-td-test-1",
            now_text,
            "sess-td-test",
            "user",
            "chat",
            "send_message",
            "success",
            13,
            "",
            "[]",
            "",
        ),
    ]
    rows_analysis = [
        ("ana-td-prod", "sess-td-prod", "evt-td-prod-1", "pending", now_text, now_text),
        ("ana-td-test", "sess-td-test", "evt-td-test-1", "pending", now_text, now_text),
    ]
    rows_training = [
        ("trn-td-prod", "ana-td-prod", "pending", "", "", 0, "", now_text, now_text),
        ("trn-td-test", "ana-td-test", "pending", "", "", 0, "", now_text, now_text),
    ]
    conn = sqlite3.connect(db_path.as_posix())
    try:
        conn.executemany(
            """
            INSERT OR REPLACE INTO chat_sessions (
              session_id,agent_name,agents_hash,agents_loaded_at,agents_path,agents_version,
              agent_search_root,target_path,is_test_data,status,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            rows_sessions,
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO conversation_events (
              event_id,timestamp,session_id,actor,stage,action,status,latency_ms,task_id,reason_tags_json,ref
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            rows_events,
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO analysis_tasks (
              analysis_id,session_id,source_event_id,status,created_at,updated_at
            ) VALUES (?,?,?,?,?,?)
            """,
            rows_analysis,
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO training_tasks (
              training_id,analysis_id,status,result_summary,trainer_run_ref,attempts,last_error,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            rows_training,
        )
        conn.commit()
    finally:
        conn.close()


def find_agent(items: list[dict[str, Any]], name: str) -> dict[str, Any]:
    key = name.strip().lower()
    for row in items:
        if str(row.get("agent_name") or "").strip().lower() == key:
            return row
    raise RuntimeError(f"agent not found: {name}")


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
    width: int = 1440,
    height: int = 980,
    budget_ms: int = 20000,
) -> None:
    shot_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(edge_path),
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
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
    width: int = 1440,
    height: int = 980,
    budget_ms: int = 20000,
) -> str:
    cmd = [
        str(edge_path),
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        f"--window-size={width},{height}",
        f"--virtual-time-budget={max(1000, int(budget_ms))}",
        "--dump-dom",
        url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=180)
    if proc.returncode != 0:
        raise RuntimeError(f"edge dump-dom failed: {proc.stderr}")
    return proc.stdout


def parse_td_probe(dom_text: str) -> dict[str, Any]:
    matched = re.search(
        r"<pre[^>]*id=['\"]testDataToggleProbeOutput['\"][^>]*>(.*?)</pre>",
        str(dom_text or ""),
        flags=re.I | re.S,
    )
    if not matched:
        raise RuntimeError("testDataToggleProbeOutput_not_found")
    raw = html.unescape(matched.group(1) or "").strip()
    if not raw:
        raise RuntimeError("testDataToggleProbeOutput_empty")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError("testDataToggleProbeOutput_not_dict")
    return payload


def td_probe_url(base_url: str, case_id: str, extra: dict[str, str] | None = None) -> str:
    query: dict[str, str] = {
        "td_probe": "1",
        "td_probe_case": str(case_id),
        "_ts": str(int(time.time() * 1000)),
    }
    if extra:
        for k, v in extra.items():
            query[str(k)] = str(v)
    return base_url.rstrip("/") + "/?" + urlencode(query)


def capture_probe(
    edge_path: Path,
    base_url: str,
    evidence_root: Path,
    name: str,
    case_id: str,
    extra: dict[str, str] | None = None,
) -> tuple[str, str, dict[str, Any]]:
    url = td_probe_url(base_url, case_id, extra)
    shot = evidence_root / "screenshots" / f"{name}.png"
    probe_file = evidence_root / "screenshots" / f"{name}.probe.json"
    edge_shot(edge_path, url, shot)
    probe = parse_td_probe(edge_dom(edge_path, url))
    write_json(probe_file, probe)
    return shot.as_posix(), probe_file.as_posix(), probe


def object_has_key(payload: Any, key: str) -> bool:
    return isinstance(payload, dict) and key in payload


def main() -> int:
    parser = argparse.ArgumentParser(description="AC-TD-01~09 acceptance with full evidence")
    parser.add_argument("--root", default=".", help="repo root")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8152)
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    runtime_root = (repo_root / "state" / "acceptance-runtime-td").resolve()
    evidence_root = (repo_root / ".test" / "evidence" / f"test-data-toggle-td-{ts}").resolve()
    api_dir = evidence_root / "api"
    db_dir = evidence_root / "db"
    shots_dir = evidence_root / "screenshots"
    for d in [evidence_root, api_dir, db_dir, shots_dir]:
        d.mkdir(parents=True, exist_ok=True)

    if runtime_root.exists():
        shutil.rmtree(runtime_root, ignore_errors=True)
    runtime_root.mkdir(parents=True, exist_ok=True)

    workspace_root = runtime_root / "workspace-root"
    prod_agent_name, system_agent_name = fixture_agents(workspace_root)
    db_path = runtime_root / "state" / "workflow.db"
    runtime_cfg_path = runtime_root / "state" / "runtime-config.json"
    base_url = f"http://{args.host}:{args.port}"
    server_stdout = evidence_root / "server.stdout.log"
    server_stderr = evidence_root / "server.stderr.log"

    proc = subprocess.Popen(
        [
            sys.executable,
            str((repo_root / "scripts" / "workflow_web_server.py").resolve()),
            "--root",
            runtime_root.as_posix(),
            "--entry-script",
            str((repo_root / "scripts" / "workflow_entry_cli.py").resolve()),
            "--host",
            args.host,
            "--port",
            str(args.port),
        ],
        cwd=repo_root.as_posix(),
        stdout=server_stdout.open("w", encoding="utf-8"),
        stderr=server_stderr.open("w", encoding="utf-8"),
        text=True,
    )

    ac: dict[str, dict[str, Any]] = {}
    ac_ev: dict[str, dict[str, list[str]]] = {}

    code_refs_common = [
        (repo_root / "src" / "workflow_app" / "workflow_web_server.py").resolve().as_posix(),
        (repo_root / "src" / "workflow_app" / "runtime" / "training_center_runtime.py").resolve().as_posix(),
        (repo_root / "src" / "workflow_app" / "web_client" / "app_state_and_utils.js").resolve().as_posix(),
        (repo_root / "src" / "workflow_app" / "web_client" / "policy_confirm_and_interactions.js").resolve().as_posix(),
        (repo_root / "src" / "workflow_app" / "web_client" / "training_center_and_bootstrap.js").resolve().as_posix(),
    ]

    def api_file(
        name: str,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        status: int,
        body: dict[str, Any],
    ) -> str:
        out = api_dir / f"{name}.api.json"
        write_json(
            out,
            {
                "request": {"method": method, "path": path, "payload": payload},
                "response": {"status": status, "body": body},
            },
        )
        return out.as_posix()

    try:
        wait_health(base_url)

        setup_payload = {"agent_search_root": workspace_root.as_posix()}
        st_setup, body_setup = call(base_url, "POST", "/api/config/agent-search-root", setup_payload)
        api_setup = api_file("setup_switch_root", "POST", "/api/config/agent-search-root", setup_payload, st_setup, body_setup)
        if st_setup != 200 or not body_setup.get("ok"):
            raise RuntimeError(f"switch root failed: {st_setup} {body_setup}")

        st_seed_agents, body_seed_agents = call(base_url, "GET", "/api/training/agents")
        api_seed_agents = api_file("setup_training_agents", "GET", "/api/training/agents", None, st_seed_agents, body_seed_agents)
        seed_items = list(body_seed_agents.get("items") or [])
        prod_agent = find_agent(seed_items, prod_agent_name)
        prod_agent_id = str(prod_agent.get("agent_id") or "")
        if not prod_agent_id:
            raise RuntimeError("prod agent_id missing")

        seed_dashboard_rows(db_path, workspace_root, prod_agent_name, system_agent_name)
        dump_sql(
            db_path,
            "SELECT session_id,agent_name,is_test_data,status,created_at FROM chat_sessions WHERE session_id IN ('sess-td-prod','sess-td-test') ORDER BY session_id",
            (),
            db_dir / "ac_td_04_chat_sessions_seed.db.json",
        )
        dump_sql(
            db_path,
            "SELECT event_id,session_id,actor,stage,action,status,timestamp FROM conversation_events WHERE session_id IN ('sess-td-prod','sess-td-test') ORDER BY event_id",
            (),
            db_dir / "ac_td_04_conversation_events_seed.db.json",
        )
        dump_sql(
            db_path,
            "SELECT analysis_id,session_id,status,created_at FROM analysis_tasks WHERE analysis_id IN ('ana-td-prod','ana-td-test') ORDER BY analysis_id",
            (),
            db_dir / "ac_td_04_analysis_tasks_seed.db.json",
        )
        dump_sql(
            db_path,
            "SELECT training_id,analysis_id,status,created_at FROM training_tasks WHERE training_id IN ('trn-td-prod','trn-td-test') ORDER BY training_id",
            (),
            db_dir / "ac_td_04_training_tasks_seed.db.json",
        )

        p_seed_normal = {
            "target_agent_id": prod_agent_id,
            "capability_goal": "td queue normal",
            "training_tasks": ["normal-item"],
            "acceptance_criteria": "normal queued",
            "priority": "P2",
            "operator": "td-test",
            "is_test_data": False,
        }
        st_seed_q1, body_seed_q1 = call(base_url, "POST", "/api/training/plans/manual", p_seed_normal)
        api_seed_q1 = api_file("setup_training_queue_normal", "POST", "/api/training/plans/manual", p_seed_normal, st_seed_q1, body_seed_q1)

        p_seed_test = {
            "target_agent_id": prod_agent_id,
            "capability_goal": "td queue test",
            "training_tasks": ["test-item"],
            "acceptance_criteria": "test queued",
            "priority": "P3",
            "operator": "td-test",
            "is_test_data": True,
        }
        st_seed_q2, body_seed_q2 = call(base_url, "POST", "/api/training/plans/manual", p_seed_test)
        api_seed_q2 = api_file("setup_training_queue_test", "POST", "/api/training/plans/manual", p_seed_test, st_seed_q2, body_seed_q2)

        dump_sql(
            db_path,
            "SELECT p.plan_id,p.is_test_data,q.queue_task_id,q.status,q.priority FROM training_plan p INNER JOIN training_queue q ON q.plan_id=p.plan_id ORDER BY p.created_at DESC LIMIT 10",
            (),
            db_dir / "ac_td_05_training_seed.db.json",
        )

        st01a, body01a = call(base_url, "GET", "/api/agents")
        api01a = api_file("ac_td_01_agents", "GET", "/api/agents", None, st01a, body01a)
        st01b, body01b = call(base_url, "GET", "/api/config/show-test-data")
        api01b = api_file("ac_td_01_show_test_data_get", "GET", "/api/config/show-test-data", None, st01b, body01b)
        ac["AC-TD-01"] = {
            "pass": bool(
                st01a == 200
                and st01b == 200
                and object_has_key(body01a, "show_test_data")
                and object_has_key(body01b, "show_test_data")
            ),
            "api": [api01a, api01b, api_setup, api_seed_agents],
        }

        st02p, body02p = call(base_url, "POST", "/api/config/show-test-data", {"show_test_data": False})
        api02p = api_file("ac_td_02_set_false", "POST", "/api/config/show-test-data", {"show_test_data": False}, st02p, body02p)
        st02g, body02g = call(base_url, "GET", "/api/agents")
        api02g = api_file("ac_td_02_agents_after_reload", "GET", "/api/agents", None, st02g, body02g)
        runtime_cfg_02 = read_json(runtime_cfg_path)
        runtime_cfg_02_file = db_dir / "ac_td_02_runtime_config.json"
        write_json(runtime_cfg_02_file, runtime_cfg_02)
        ac["AC-TD-02"] = {
            "pass": bool(
                st02p == 200
                and st02g == 200
                and body02p.get("show_test_data") is False
                and body02g.get("show_test_data") is False
                and runtime_cfg_02.get("show_test_data") is False
            ),
            "api": [api02p, api02g],
        }

        st03p0, body03p0 = call(base_url, "POST", "/api/config/show-test-data", {"show_test_data": False})
        api03p0 = api_file("ac_td_03_set_false", "POST", "/api/config/show-test-data", {"show_test_data": False}, st03p0, body03p0)
        st03s0, body03s0 = call(base_url, "GET", "/api/status")
        api03s0 = api_file("ac_td_03_status_off", "GET", "/api/status", None, st03s0, body03s0)
        st03p1, body03p1 = call(base_url, "POST", "/api/config/show-test-data", {"show_test_data": True})
        api03p1 = api_file("ac_td_03_set_true", "POST", "/api/config/show-test-data", {"show_test_data": True}, st03p1, body03p1)
        st03s1, body03s1 = call(base_url, "GET", "/api/status")
        api03s1 = api_file("ac_td_03_status_on", "GET", "/api/status", None, st03s1, body03s1)
        ac["AC-TD-03"] = {
            "pass": bool(
                st03p0 == 200
                and st03s0 == 200
                and body03s0.get("show_test_data") is False
                and st03p1 == 200
                and st03s1 == 200
                and body03s1.get("show_test_data") is True
            ),
            "api": [api03p0, api03s0, api03p1, api03s1],
        }

        st04p0, body04p0 = call(base_url, "POST", "/api/config/show-test-data", {"show_test_data": False})
        api04p0 = api_file("ac_td_04_set_false", "POST", "/api/config/show-test-data", {"show_test_data": False}, st04p0, body04p0)
        st04d0, body04d0 = call(base_url, "GET", "/api/dashboard")
        api04d0 = api_file("ac_td_04_dashboard_off", "GET", "/api/dashboard", None, st04d0, body04d0)
        st04p1, body04p1 = call(base_url, "POST", "/api/config/show-test-data", {"show_test_data": True})
        api04p1 = api_file("ac_td_04_set_true", "POST", "/api/config/show-test-data", {"show_test_data": True}, st04p1, body04p1)
        st04d1, body04d1 = call(base_url, "GET", "/api/dashboard")
        api04d1 = api_file("ac_td_04_dashboard_on", "GET", "/api/dashboard", None, st04d1, body04d1)
        changed04 = (
            int(body04d0.get("new_sessions_24h") or 0) != int(body04d1.get("new_sessions_24h") or 0)
            or int(body04d0.get("pending_analysis") or 0) != int(body04d1.get("pending_analysis") or 0)
            or int(body04d0.get("pending_training") or 0) != int(body04d1.get("pending_training") or 0)
        )
        ac["AC-TD-04"] = {
            "pass": bool(st04d0 == 200 and st04d1 == 200 and changed04),
            "api": [api04p0, api04d0, api04p1, api04d1],
        }

        st05p0, body05p0 = call(base_url, "POST", "/api/config/show-test-data", {"show_test_data": False})
        api05p0 = api_file("ac_td_05_set_false", "POST", "/api/config/show-test-data", {"show_test_data": False}, st05p0, body05p0)
        st05a0, body05a0 = call(base_url, "GET", "/api/training/agents")
        api05a0 = api_file("ac_td_05_training_agents_off", "GET", "/api/training/agents", None, st05a0, body05a0)
        st05q0, body05q0 = call(base_url, "GET", "/api/training/queue?include_removed=1")
        api05q0 = api_file("ac_td_05_training_queue_off", "GET", "/api/training/queue?include_removed=1", None, st05q0, body05q0)
        st05p1, body05p1 = call(base_url, "POST", "/api/config/show-test-data", {"show_test_data": True})
        api05p1 = api_file("ac_td_05_set_true", "POST", "/api/config/show-test-data", {"show_test_data": True}, st05p1, body05p1)
        st05a1, body05a1 = call(base_url, "GET", "/api/training/agents")
        api05a1 = api_file("ac_td_05_training_agents_on", "GET", "/api/training/agents", None, st05a1, body05a1)
        st05q1, body05q1 = call(base_url, "GET", "/api/training/queue?include_removed=1")
        api05q1 = api_file("ac_td_05_training_queue_on", "GET", "/api/training/queue?include_removed=1", None, st05q1, body05q1)
        agents_off = len(list(body05a0.get("items") or []))
        agents_on = len(list(body05a1.get("items") or []))
        queue_off = len(list(body05q0.get("items") or []))
        queue_on = len(list(body05q1.get("items") or []))
        changed05 = agents_on > agents_off or queue_on > queue_off
        ac["AC-TD-05"] = {
            "pass": bool(
                st05a0 == 200
                and st05q0 == 200
                and st05a1 == 200
                and st05q1 == 200
                and agents_on >= agents_off
                and queue_on >= queue_off
                and changed05
            ),
            "api": [api05p0, api05a0, api05q0, api05p1, api05a1, api05q1, api_seed_q1, api_seed_q2],
        }

        st06g, body06g = call(base_url, "GET", "/api/config/show-test-data")
        api06g = api_file("ac_td_06_get_before", "GET", "/api/config/show-test-data", None, st06g, body06g)
        before06 = bool(body06g.get("show_test_data"))
        payload06 = {"show_test_data": (not before06), "force_fail": True}
        st06f, body06f = call(base_url, "POST", "/api/config/show-test-data", payload06)
        api06f = api_file("ac_td_06_force_fail", "POST", "/api/config/show-test-data", payload06, st06f, body06f)
        st06a, body06a = call(base_url, "GET", "/api/config/show-test-data")
        api06a = api_file("ac_td_06_get_after", "GET", "/api/config/show-test-data", None, st06a, body06a)
        ac["AC-TD-06"] = {
            "pass": bool(
                st06f == 500
                and str(body06f.get("code") or "") == "show_test_data_save_failed"
                and st06a == 200
                and bool(body06a.get("show_test_data")) == before06
            ),
            "api": [api06g, api06f, api06a],
        }

        fail_path07 = "/api/agents?force_show_test_data_read_fail=1"
        st07f, body07f = call(base_url, "GET", fail_path07)
        api07f = api_file("ac_td_07_force_read_fail", "GET", fail_path07, None, st07f, body07f)
        st07r, body07r = call(base_url, "GET", "/api/agents")
        api07r = api_file("ac_td_07_retry_agents", "GET", "/api/agents", None, st07r, body07r)
        ac["AC-TD-07"] = {
            "pass": bool(
                st07f == 500
                and str(body07f.get("code") or "") == "show_test_data_read_failed"
                and st07r == 200
                and object_has_key(body07r, "show_test_data")
            ),
            "api": [api07f, api07r],
        }

        st08p, body08p = call(base_url, "POST", "/api/config/show-test-data", {"show_test_data": False})
        api08p = api_file("ac_td_08_set_false", "POST", "/api/config/show-test-data", {"show_test_data": False}, st08p, body08p)
        st08g, body08g = call(base_url, "GET", "/api/agents")
        api08g = api_file("ac_td_08_agents", "GET", "/api/agents", None, st08g, body08g)
        runtime_cfg_08 = read_json(runtime_cfg_path)
        runtime_cfg_08_file = db_dir / "ac_td_08_runtime_config.json"
        write_json(runtime_cfg_08_file, runtime_cfg_08)
        ac["AC-TD-08"] = {
            "pass": bool(
                st08p == 200
                and st08g == 200
                and body08g.get("show_test_data") is False
                and runtime_cfg_08.get("show_test_data") is False
            ),
            "api": [api08p, api08g],
        }

        edge = find_edge()
        shot_refs: dict[str, str] = {}
        probe_refs: dict[str, str] = {}

        def cap(name: str, case_id: str, extra: dict[str, str] | None = None) -> tuple[str, dict[str, Any]]:
            shot, probe_file, probe_data = capture_probe(edge, base_url, evidence_root, name, case_id, extra)
            shot_refs[name] = shot
            probe_refs[name] = probe_file
            return shot, probe_data

        shot01, probe01 = cap("ac_td_01_unique_toggle", "ac_td_01")
        shot02, probe02 = cap("ac_td_02_persistence", "ac_td_02")
        shot03, probe03 = cap("ac_td_03_session_entry_linkage", "ac_td_03")
        shot04, probe04 = cap("ac_td_04_dashboard_linkage", "ac_td_04")
        shot05, probe05 = cap("ac_td_05_training_center_linkage", "ac_td_05")
        shot06, probe06 = cap("ac_td_06_write_fail_rollback", "ac_td_06", {"td_probe_force_write_fail": "1"})
        shot07, probe07 = cap("ac_td_07_startup_read_fail_retry", "ac_td_07")
        shot08, probe08 = cap("ac_td_08_legacy_key_no_effect", "ac_td_08")

        write_json(evidence_root / "screenshots_index.json", shot_refs)
        write_json(evidence_root / "probe_index.json", probe_refs)

        ac["AC-TD-01"]["pass"] = bool(ac["AC-TD-01"]["pass"] and probe01.get("pass"))
        ac["AC-TD-02"]["pass"] = bool(ac["AC-TD-02"]["pass"] and probe02.get("pass"))
        ac["AC-TD-03"]["pass"] = bool(ac["AC-TD-03"]["pass"] and probe03.get("pass"))
        ac["AC-TD-04"]["pass"] = bool(ac["AC-TD-04"]["pass"] and probe04.get("pass"))
        ac["AC-TD-05"]["pass"] = bool(ac["AC-TD-05"]["pass"] and probe05.get("pass"))
        ac["AC-TD-06"]["pass"] = bool(ac["AC-TD-06"]["pass"] and probe06.get("pass"))
        ac["AC-TD-07"]["pass"] = bool(ac["AC-TD-07"]["pass"] and probe07.get("pass"))
        ac["AC-TD-08"]["pass"] = bool(ac["AC-TD-08"]["pass"] and probe08.get("pass"))

        ac_ev["AC-TD-01"] = {
            "screenshots": [shot01],
            "recordings": [],
            "api": ac["AC-TD-01"]["api"],
            "db_or_logs": [server_stdout.as_posix(), server_stderr.as_posix(), probe_refs["ac_td_01_unique_toggle"]],
            "code": code_refs_common,
        }
        ac_ev["AC-TD-02"] = {
            "screenshots": [shot02],
            "recordings": [],
            "api": ac["AC-TD-02"]["api"],
            "db_or_logs": [runtime_cfg_02_file.as_posix(), probe_refs["ac_td_02_persistence"]],
            "code": code_refs_common,
        }
        ac_ev["AC-TD-03"] = {
            "screenshots": [shot03],
            "recordings": [],
            "api": ac["AC-TD-03"]["api"],
            "db_or_logs": [probe_refs["ac_td_03_session_entry_linkage"], server_stdout.as_posix()],
            "code": code_refs_common,
        }
        ac_ev["AC-TD-04"] = {
            "screenshots": [shot04],
            "recordings": [],
            "api": ac["AC-TD-04"]["api"],
            "db_or_logs": [
                (db_dir / "ac_td_04_chat_sessions_seed.db.json").as_posix(),
                (db_dir / "ac_td_04_conversation_events_seed.db.json").as_posix(),
                (db_dir / "ac_td_04_analysis_tasks_seed.db.json").as_posix(),
                (db_dir / "ac_td_04_training_tasks_seed.db.json").as_posix(),
                probe_refs["ac_td_04_dashboard_linkage"],
            ],
            "code": code_refs_common,
        }
        ac_ev["AC-TD-05"] = {
            "screenshots": [shot05],
            "recordings": [],
            "api": ac["AC-TD-05"]["api"],
            "db_or_logs": [(db_dir / "ac_td_05_training_seed.db.json").as_posix(), probe_refs["ac_td_05_training_center_linkage"]],
            "code": code_refs_common,
        }
        ac_ev["AC-TD-06"] = {
            "screenshots": [shot06],
            "recordings": [],
            "api": ac["AC-TD-06"]["api"],
            "db_or_logs": [server_stdout.as_posix(), server_stderr.as_posix(), probe_refs["ac_td_06_write_fail_rollback"]],
            "code": code_refs_common,
        }
        ac_ev["AC-TD-07"] = {
            "screenshots": [shot07],
            "recordings": [],
            "api": ac["AC-TD-07"]["api"],
            "db_or_logs": [server_stdout.as_posix(), server_stderr.as_posix(), probe_refs["ac_td_07_startup_read_fail_retry"]],
            "code": code_refs_common,
        }
        ac_ev["AC-TD-08"] = {
            "screenshots": [shot08],
            "recordings": [],
            "api": ac["AC-TD-08"]["api"],
            "db_or_logs": [runtime_cfg_08_file.as_posix(), probe_refs["ac_td_08_legacy_key_no_effect"]],
            "code": code_refs_common,
        }

        coverage: dict[str, Any] = {}
        for idx in range(1, 9):
            ac_id = f"AC-TD-{idx:02d}"
            ev = ac_ev.get(ac_id, {})
            coverage[ac_id] = {
                "has_screenshot": bool(ev.get("screenshots")),
                "has_api": bool(ev.get("api")),
                "has_db_or_logs": bool(ev.get("db_or_logs")),
                "has_code": bool(ev.get("code")),
            }

        matrix_json = evidence_root / "ac_td_09_evidence_matrix.json"
        write_json(
            matrix_json,
            {
                "coverage": coverage,
                "screenshots": shot_refs,
                "probes": probe_refs,
            },
        )
        matrix_html = evidence_root / "ac_td_09_evidence_matrix.html"
        lines = [
            "<html><head><meta charset='utf-8'><style>",
            "body{font-family:Segoe UI,Arial,sans-serif;padding:16px;background:#f8fafc;color:#1f2937}",
            "h1{font-size:18px;margin:0 0 12px 0}",
            "table{border-collapse:collapse;width:100%;background:#fff}",
            "th,td{border:1px solid #d1d5db;padding:6px 8px;font-size:12px;text-align:left}",
            ".ok{color:#166534;font-weight:600}.bad{color:#b91c1c;font-weight:600}",
            "</style></head><body>",
            "<h1>AC-TD-09 Evidence Completeness</h1>",
            "<table><tr><th>AC</th><th>screenshot</th><th>api</th><th>db/log</th><th>code</th></tr>",
        ]
        for idx in range(1, 9):
            ac_id = f"AC-TD-{idx:02d}"
            row = coverage.get(ac_id, {})
            lines.append(
                "<tr>"
                + f"<td>{ac_id}</td>"
                + f"<td class='{'ok' if row.get('has_screenshot') else 'bad'}'>{row.get('has_screenshot')}</td>"
                + f"<td class='{'ok' if row.get('has_api') else 'bad'}'>{row.get('has_api')}</td>"
                + f"<td class='{'ok' if row.get('has_db_or_logs') else 'bad'}'>{row.get('has_db_or_logs')}</td>"
                + f"<td class='{'ok' if row.get('has_code') else 'bad'}'>{row.get('has_code')}</td>"
                + "</tr>"
            )
        lines.append("</table></body></html>")
        matrix_html.write_text("\n".join(lines), encoding="utf-8")
        shot09 = shots_dir / "ac_td_09_evidence_matrix.png"
        edge_shot(edge, matrix_html.resolve().as_uri(), shot09)

        ac["AC-TD-09"] = {
            "pass": bool(
                all(
                    row["has_screenshot"]
                    and row["has_api"]
                    and row["has_db_or_logs"]
                    and row["has_code"]
                    for row in coverage.values()
                )
            ),
            "api": [matrix_json.as_posix()],
        }
        ac_ev["AC-TD-09"] = {
            "screenshots": [shot09.as_posix()],
            "recordings": [],
            "api": [matrix_json.as_posix()],
            "db_or_logs": [matrix_html.as_posix(), server_stdout.as_posix(), server_stderr.as_posix()],
            "code": [
                (repo_root / "scripts" / "acceptance" / "run_acceptance_test_data_toggle_td.py").resolve().as_posix(),
                *code_refs_common,
            ],
        }

        manifest = evidence_root / "ac_td_evidence_manifest.json"
        write_json(manifest, ac_ev)

        summary_md = evidence_root / "ac_td_summary.md"
        lines = [
            f"# AC-TD Acceptance Summary ({ts})",
            "",
            f"- runtime_root: {runtime_root.as_posix()}",
            f"- workspace_root: {workspace_root.as_posix()}",
            f"- db_path: {db_path.as_posix()}",
            f"- runtime_config: {runtime_cfg_path.as_posix()}",
            f"- server_stdout: {server_stdout.as_posix()}",
            f"- server_stderr: {server_stderr.as_posix()}",
            f"- screenshots_dir: {shots_dir.as_posix()}",
            f"- api_dir: {api_dir.as_posix()}",
            f"- db_dir: {db_dir.as_posix()}",
            f"- evidence_manifest: {manifest.as_posix()}",
            "",
            "| AC | pass | evidence |",
            "|---|---|---|",
        ]
        for ac_id in [f"AC-TD-{i:02d}" for i in range(1, 10)]:
            row = ac.get(ac_id, {"pass": False})
            ev = ac_ev.get(ac_id, {})
            refs = []
            if ev.get("screenshots"):
                refs.append("screenshot=" + "<br>".join(ev["screenshots"]))
            if ev.get("api"):
                refs.append("api=" + "<br>".join(ev["api"]))
            if ev.get("db_or_logs"):
                refs.append("db/log=" + "<br>".join(ev["db_or_logs"]))
            if ev.get("code"):
                refs.append("code=" + "<br>".join(ev["code"]))
            lines.append(f"| {ac_id} | {'pass' if row.get('pass') else 'fail'} | {'<br><br>'.join(refs)} |")
        summary_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

        write_json(evidence_root / "ac_td_summary.json", ac)
        print(summary_md.as_posix())
        return 0 if len(ac) == 9 and all(bool(v.get("pass")) for v in ac.values()) else 1
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())

