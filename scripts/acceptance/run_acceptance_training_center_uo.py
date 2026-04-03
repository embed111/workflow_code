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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REQ_GIF = ("AC-UO-01", "AC-UO-02", "AC-UO-05", "AC-UO-09")


def call(base_url: str, method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
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


def call_many(
    base_url: str,
    method: str,
    path: str,
    *,
    count: int,
    payload: dict[str, Any] | None = None,
) -> list[tuple[int, dict[str, Any]]]:
    with ThreadPoolExecutor(max_workers=max(1, int(count))) as pool:
        futures = [pool.submit(call, base_url, method, path, payload) for _ in range(max(1, int(count)))]
        return [future.result() for future in futures]


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


def dump_sql(db_path: Path, sql: str, params: tuple[Any, ...], out_path: Path) -> None:
    conn = sqlite3.connect(db_path.as_posix())
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    write_json(out_path, [{"_row_index": i + 1, **{k: row[k] for k in row.keys()}} for i, row in enumerate(rows)])


def run_cmd(args: list[str], cwd: Path) -> None:
    proc = subprocess.run(args, cwd=cwd.as_posix(), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("cmd failed: " + " ".join(args) + "\n" + str(proc.stdout) + "\n" + str(proc.stderr))


def fixture_agents(workspace_root: Path) -> tuple[Path, Path]:
    (workspace_root / "workflow").mkdir(parents=True, exist_ok=True)
    (workspace_root / "workflow" / "README.md").write_text("fixture\n", encoding="utf-8")
    alpha = workspace_root / "alpha-agent"
    beta = workspace_root / "beta-agent"
    alpha.mkdir(parents=True, exist_ok=True)
    beta.mkdir(parents=True, exist_ok=True)
    agents_md = "\n".join(
        [
            "# AGENT",
            "",
            "## 角色定位",
            "你是训练优化助手。",
            "",
            "## 会话目标",
            "提升工作区能力与交付质量。",
            "",
            "## 职责边界",
            "### must",
            "- 输出可验证证据。",
            "- 严格遵守优先级与审计要求。",
            "",
            "### must_not",
            "- 不做越界写入。",
            "- 不执行未授权高风险操作。",
        ]
    )
    (alpha / "AGENTS.md").write_text(agents_md + "\n", encoding="utf-8")
    (beta / "AGENTS.md").write_text(agents_md + "\n", encoding="utf-8")

    run_cmd(["git", "init"], alpha)
    run_cmd(["git", "config", "user.email", "uo-test@example.com"], alpha)
    run_cmd(["git", "config", "user.name", "uo-test"], alpha)
    run_cmd(["git", "add", "AGENTS.md"], alpha)
    run_cmd(["git", "commit", "-m", "init"], alpha)
    run_cmd(["git", "tag", "-a", "v1.0.0", "-m", "release note: baseline capability"], alpha)
    (alpha / "CHANGELOG.md").write_text("improve capability quality\n", encoding="utf-8")
    run_cmd(["git", "add", "CHANGELOG.md"], alpha)
    run_cmd(["git", "commit", "-m", "improve capability"], alpha)
    run_cmd(["git", "tag", "-a", "v1.1.0", "-m", "release note: improve capability quality"], alpha)
    return alpha, beta


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


def edge_shot(edge_path: Path, url: str, shot_path: Path, width: int = 1440, height: int = 980, budget_ms: int = 15000) -> None:
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


def edge_dom(edge_path: Path, url: str, width: int = 1440, height: int = 980, budget_ms: int = 15000) -> str:
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


def parse_probe(dom_text: str) -> dict[str, Any]:
    matched = re.search(r"<pre[^>]*id=['\"]trainingCenterProbeOutput['\"][^>]*>(.*?)</pre>", str(dom_text or ""), flags=re.I | re.S)
    if not matched:
        raise RuntimeError("trainingCenterProbeOutput_not_found")
    raw = html.unescape(matched.group(1) or "").strip()
    if not raw:
        raise RuntimeError("trainingCenterProbeOutput_empty")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError("trainingCenterProbeOutput_not_dict")
    return payload


def ps_quote(text: str) -> str:
    return "'" + str(text or "").replace("'", "''") + "'"


def make_gif(gif_path: Path, frames: list[Path]) -> None:
    use_frames = [f.resolve(strict=False) for f in frames if f and f.exists()]
    if not use_frames:
        raise RuntimeError(f"gif frames missing: {gif_path.as_posix()}")
    frames_literal = ",".join([ps_quote(p.as_posix()) for p in use_frames])
    out_literal = ps_quote(gif_path.resolve(strict=False).as_posix())
    cmd = (
        "Add-Type -AssemblyName PresentationCore; "
        "$encoder = New-Object System.Windows.Media.Imaging.GifBitmapEncoder; "
        + f"foreach($f in @({frames_literal}))"
        + "{" 
        + "$uri = New-Object System.Uri($f); "
        + "$frame = [System.Windows.Media.Imaging.BitmapFrame]::Create($uri); "
        + "$encoder.Frames.Add($frame);"
        + "}; "
        + f"$out={out_literal}; "
        + "$stream=[System.IO.File]::Open($out,[System.IO.FileMode]::Create); "
        + "try{$encoder.Save($stream)} finally {$stream.Close()}"
    )
    proc = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, encoding="utf-8", timeout=120)
    if proc.returncode != 0:
        raise RuntimeError("gif failed\n" + str(proc.stdout) + "\n" + str(proc.stderr))


def tc_probe_url(base_url: str, case_id: str, extra: dict[str, str] | None = None) -> str:
    q: dict[str, str] = {"tc_probe": "1", "tc_probe_case": str(case_id), "_ts": str(int(time.time() * 1000))}
    if extra:
        for k, v in extra.items():
            q[str(k)] = str(v)
    return base_url.rstrip("/") + "/?" + urlencode(q)


def capture_probe(edge_path: Path, base_url: str, evidence_root: Path, name: str, case_id: str, extra: dict[str, str] | None = None) -> tuple[str, str, dict[str, Any]]:
    url = tc_probe_url(base_url, case_id, extra)
    shot = evidence_root / "screenshots" / f"{name}.png"
    probe_file = evidence_root / "screenshots" / f"{name}.probe.json"
    edge_shot(edge_path, url, shot)
    probe = parse_probe(edge_dom(edge_path, url))
    write_json(probe_file, probe)
    return shot.as_posix(), probe_file.as_posix(), probe

def main() -> int:
    parser = argparse.ArgumentParser(description="AC-UO-01~12 acceptance with UI evidence")
    parser.add_argument("--root", default=".", help="repo root")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8122)
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    runtime_root = (repo_root / ".test" / "runtime" / "training-center-uo").resolve()
    evidence_root = (repo_root / ".test" / "evidence" / f"training-center-uo-{ts}").resolve()
    api_dir = evidence_root / "api"
    db_dir = evidence_root / "db"
    shots_dir = evidence_root / "screenshots"
    rec_dir = evidence_root / "recordings"
    for d in [evidence_root, api_dir, db_dir, shots_dir, rec_dir]:
        d.mkdir(parents=True, exist_ok=True)

    if runtime_root.exists():
        shutil.rmtree(runtime_root, ignore_errors=True)
    runtime_root.mkdir(parents=True, exist_ok=True)

    workspace_root = runtime_root / "workspace-root"
    fixture_agents(workspace_root)
    db_path = runtime_root / "state" / "workflow.db"

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
        (repo_root / "src" / "workflow_app" / "runtime" / "training_center_runtime.py").resolve().as_posix(),
        (repo_root / "src" / "workflow_app" / "workflow_web_server.py").resolve().as_posix(),
        (repo_root / "src" / "workflow_app" / "web_client" / "training_center_and_bootstrap.js").resolve().as_posix(),
        (repo_root / "src" / "workflow_app" / "web_client" / "app_state_and_utils.js").resolve().as_posix(),
    ]

    def api_file(name: str, method: str, path: str, payload: dict[str, Any] | None, status: int, body: dict[str, Any]) -> str:
        out = api_dir / f"{name}.api.json"
        write_json(out, {"request": {"method": method, "path": path, "payload": payload}, "response": {"status": status, "body": body}})
        return out.as_posix()

    try:
        wait_health(base_url)

        st_sw, body_sw = call(base_url, "POST", "/api/config/agent-search-root", {"agent_search_root": workspace_root.as_posix()})
        api_file("setup_switch_root", "POST", "/api/config/agent-search-root", {"agent_search_root": workspace_root.as_posix()}, st_sw, body_sw)
        if st_sw != 200 or not body_sw.get("ok"):
            raise RuntimeError(f"switch root failed: {st_sw} {body_sw}")

        trainer_q = "/api/training/trainers?" + urlencode({"query": "trainer"})
        st_tr, body_tr = call(base_url, "GET", trainer_q)
        api_file("setup_trainers", "GET", trainer_q, None, st_tr, body_tr)
        trainer_rows = list(body_tr.get("items") or []) if st_tr == 200 else []
        trainer_name = str((trainer_rows[0] if trainer_rows else {}).get("trainer_name") or "trainer").strip() or "trainer"

        st_agents, body_agents = call(base_url, "GET", "/api/training/agents")
        ac01_api = api_file("ac_uo_01_agents", "GET", "/api/training/agents", None, st_agents, body_agents)
        ac01_concurrent_api = api_dir / "ac_uo_01_agents_concurrent.api.json"
        concurrent_agents = call_many(base_url, "GET", "/api/training/agents", count=4)
        write_json(
            ac01_concurrent_api,
            {
                "request": {"method": "GET", "path": "/api/training/agents", "concurrency": 4},
                "responses": [
                    {"index": idx + 1, "status": status, "body": body}
                    for idx, (status, body) in enumerate(concurrent_agents)
                ],
            },
        )
        items = list(body_agents.get("items") or [])
        alpha = find_agent(items, "alpha-agent")
        beta = find_agent(items, "beta-agent")
        ac["AC-UO-01"] = {
            "pass": bool(
                st_agents == 200
                and items
                and all(k in alpha for k in ["agent_name", "vector_icon", "current_version", "core_capabilities", "last_release_at"])
                and all(status == 200 for status, _body in concurrent_agents)
            ),
            "api": [ac01_api, ac01_concurrent_api.as_posix()],
        }
        dump_sql(db_path, "SELECT agent_id,agent_name,vector_icon,current_version,core_capabilities,last_release_at,status_tags_json FROM agent_registry ORDER BY agent_name", (), db_dir / "ac_uo_01_agent_registry.db.json")

        alpha_id = str(alpha.get("agent_id") or "")
        beta_id = str(beta.get("agent_id") or "")

        rel_path = f"/api/training/agents/{alpha_id}/releases?page=1&page_size=120"
        st_rel, body_rel = call(base_url, "GET", rel_path)
        ac02_api = api_file("ac_uo_02_releases", "GET", rel_path, None, st_rel, body_rel)
        releases = list(body_rel.get("releases") or [])
        has_commit_ref = any("commit_ref" in r for r in releases if isinstance(r, dict))
        ac["AC-UO-02"] = {"pass": bool(st_rel == 200 and len(releases) >= 1 and all(str(r.get("version_label") or "").strip() for r in releases)), "api": [ac02_api]}
        ac["AC-UO-03"] = {"pass": bool(st_rel == 200 and len(releases) >= 1 and not has_commit_ref), "api": [ac02_api]}
        dump_sql(db_path, "SELECT release_id,agent_id,version_label,released_at,change_summary,commit_ref,created_at FROM agent_release_history WHERE agent_id=? ORDER BY released_at DESC", (alpha_id,), db_dir / "ac_uo_03_release_history.db.json")

        ac04_payload = {
            "target_agent_id": beta_id,
            "capability_goal": "non-git plan still allowed",
            "training_tasks": ["verify non git compatibility"],
            "acceptance_criteria": "queue item created",
            "priority": "P3",
            "trainer_match": trainer_name,
            "operator": "uo-test",
        }
        st04, body04 = call(base_url, "POST", "/api/training/plans/manual", ac04_payload)
        ac04_api = api_file("ac_uo_04_non_git_manual_plan", "POST", "/api/training/plans/manual", ac04_payload, st04, body04)
        qid04 = str(body04.get("queue_task_id") or "")
        beta_tags = [str(x) for x in (beta.get("status_tags") or [])]
        ac["AC-UO-04"] = {"pass": bool(st04 == 200 and body04.get("ok") is True and "git_unavailable" in beta_tags), "api": [ac04_api]}
        dump_sql(db_path, "SELECT p.plan_id,p.source,p.target_agent_id,p.priority,q.queue_task_id,q.status,q.enqueued_at FROM training_plan p INNER JOIN training_queue q ON q.plan_id=p.plan_id WHERE q.queue_task_id=?", (qid04,), db_dir / "ac_uo_04_non_git_plan_queue.db.json")

        ac05_payload = {
            "target_agent_id": alpha_id,
            "capability_goal": "manual enqueue baseline",
            "training_tasks": ["task-a", "task-b"],
            "acceptance_criteria": "manual queue accepted",
            "priority": "P1",
            "trainer_match": trainer_name,
            "operator": "uo-test",
        }
        st05, body05 = call(base_url, "POST", "/api/training/plans/manual", ac05_payload)
        ac05_api = api_file("ac_uo_05_manual_enqueue", "POST", "/api/training/plans/manual", ac05_payload, st05, body05)
        qid05 = str(body05.get("queue_task_id") or "")
        ac["AC-UO-05"] = {"pass": bool(st05 == 200 and body05.get("source") == "manual" and qid05), "api": [ac05_api]}
        dump_sql(db_path, "SELECT p.plan_id,p.source,p.target_agent_id,p.priority,q.queue_task_id,q.status,q.enqueued_at FROM training_plan p INNER JOIN training_queue q ON q.plan_id=p.plan_id WHERE q.queue_task_id=?", (qid05,), db_dir / "ac_uo_05_plan_queue.db.json")

        payload06_missing = {
            "target_agent_id": alpha_id,
            "capability_goal": "priority required case",
            "training_tasks": ["task-x"],
            "acceptance_criteria": "must fail",
        }
        st06a, body06a = call(base_url, "POST", "/api/training/plans/manual", payload06_missing)
        api06a = api_file("ac_uo_06_priority_missing", "POST", "/api/training/plans/manual", payload06_missing, st06a, body06a)
        payload06_invalid = {
            "target_agent_id": alpha_id,
            "capability_goal": "priority invalid case",
            "training_tasks": ["task-y"],
            "acceptance_criteria": "must fail",
            "priority": "PX",
        }
        st06b, body06b = call(base_url, "POST", "/api/training/plans/manual", payload06_invalid)
        api06b = api_file("ac_uo_06_priority_invalid", "POST", "/api/training/plans/manual", payload06_invalid, st06b, body06b)
        ac["AC-UO-06"] = {
            "pass": bool(st06a == 400 and body06a.get("code") == "priority_required" and st06b == 400 and body06b.get("code") == "priority_invalid"),
            "api": [api06a, api06b],
        }

        payload08 = {
            "target_agent_id": alpha_id,
            "capability_goal": "similarity target capability",
            "training_tasks": ["normalize output format", "stabilize retry policy"],
            "acceptance_criteria": "response shape stable",
            "priority": "P2",
            "trainer_match": trainer_name,
            "operator": "uo-test",
        }
        st08a, body08a = call(base_url, "POST", "/api/training/plans/manual", payload08)
        api08a = api_file("ac_uo_08_similarity_first", "POST", "/api/training/plans/manual", payload08, st08a, body08a)
        st08b, body08b = call(base_url, "POST", "/api/training/plans/manual", payload08)
        api08b = api_file("ac_uo_08_similarity_second", "POST", "/api/training/plans/manual", payload08, st08b, body08b)
        ac["AC-UO-08"] = {"pass": bool(st08a == 200 and st08b == 200 and bool(body08b.get("similar_flag")) and bool(body08b.get("similar_plan_ids"))), "api": [api08a, api08b]}
        dump_sql(db_path, "SELECT plan_id,source,target_agent_id,priority,similar_flag,created_at FROM training_plan WHERE target_agent_id=? ORDER BY created_at DESC LIMIT 6", (alpha_id,), db_dir / "ac_uo_08_similar_plan.db.json")
        dump_sql(db_path, "SELECT audit_id,action,target_id,detail_json,created_at FROM training_audit_log WHERE action='mark_similar' ORDER BY created_at DESC LIMIT 5", (), db_dir / "ac_uo_08_mark_similar_audit.db.json")

        payload09 = {"operator": "uo-test", "reason": "manual_remove_from_acceptance"}
        path09 = f"/api/training/queue/{qid05}/remove"
        st09, body09 = call(base_url, "POST", path09, payload09)
        api09 = api_file("ac_uo_09_remove", "POST", path09, payload09, st09, body09)
        ac["AC-UO-09"] = {"pass": bool(st09 == 200 and body09.get("status") == "removed"), "api": [api09]}
        dump_sql(db_path, "SELECT queue_task_id,status,finished_at FROM training_queue WHERE queue_task_id=?", (qid05,), db_dir / "ac_uo_09_queue_removed.db.json")
        dump_sql(db_path, "SELECT audit_id,action,target_id,detail_json,created_at FROM training_audit_log WHERE action='remove' AND target_id=? ORDER BY created_at DESC LIMIT 5", (qid05,), db_dir / "ac_uo_09_remove_audit.db.json")

        payload10m = {
            "target_agent_id": alpha_id,
            "capability_goal": "manual parallel source",
            "training_tasks": ["manual-path"],
            "acceptance_criteria": "manual visible",
            "priority": "P3",
            "trainer_match": trainer_name,
            "operator": "uo-test",
        }
        st10m, body10m = call(base_url, "POST", "/api/training/plans/manual", payload10m)
        api10m = api_file("ac_uo_10_manual_plan", "POST", "/api/training/plans/manual", payload10m, st10m, body10m)
        payload10a = {
            "target_agent_id": alpha_id,
            "capability_goal": "auto parallel source",
            "training_tasks": ["auto-path"],
            "acceptance_criteria": "auto visible",
            "priority": "P3",
            "trainer_match": trainer_name,
            "operator": "uo-test",
        }
        st10a, body10a = call(base_url, "POST", "/api/training/plans/auto", payload10a)
        api10a = api_file("ac_uo_10_auto_plan", "POST", "/api/training/plans/auto", payload10a, st10a, body10a)
        st10q, body10q = call(base_url, "GET", "/api/training/queue?include_removed=1")
        api10q = api_file("ac_uo_10_queue", "GET", "/api/training/queue?include_removed=1", None, st10q, body10q)
        sources = {str((row or {}).get("source") or "") for row in list(body10q.get("items") or [])}
        ac["AC-UO-10"] = {"pass": bool(st10m == 200 and st10a == 200 and st10q == 200 and {"manual", "auto_analysis"}.issubset(sources)), "api": [api10m, api10a, api10q]}
        dump_sql(db_path, "SELECT q.queue_task_id,p.source,p.priority,q.status,q.enqueued_at FROM training_queue q INNER JOIN training_plan p ON p.plan_id=q.plan_id ORDER BY q.enqueued_at DESC LIMIT 40", (), db_dir / "ac_uo_10_queue_sources.db.json")

        p07_p2 = {"target_agent_id": alpha_id, "capability_goal": "dispatch p2", "training_tasks": ["p2"], "acceptance_criteria": "ordered", "priority": "P2", "trainer_match": trainer_name, "operator": "uo-test"}
        p07_p0 = {"target_agent_id": alpha_id, "capability_goal": "dispatch p0", "training_tasks": ["p0"], "acceptance_criteria": "ordered", "priority": "P0", "trainer_match": trainer_name, "operator": "uo-test"}
        p07_p1 = {"target_agent_id": alpha_id, "capability_goal": "dispatch p1", "training_tasks": ["p1"], "acceptance_criteria": "ordered", "priority": "P1", "trainer_match": trainer_name, "operator": "uo-test"}
        st07a, body07a = call(base_url, "POST", "/api/training/plans/manual", p07_p2)
        st07b, body07b = call(base_url, "POST", "/api/training/plans/manual", p07_p0)
        st07c, body07c = call(base_url, "POST", "/api/training/plans/manual", p07_p1)
        api07a = api_file("ac_uo_07_enqueue_p2", "POST", "/api/training/plans/manual", p07_p2, st07a, body07a)
        api07b = api_file("ac_uo_07_enqueue_p0", "POST", "/api/training/plans/manual", p07_p0, st07b, body07b)
        api07c = api_file("ac_uo_07_enqueue_p1", "POST", "/api/training/plans/manual", p07_p1, st07c, body07c)
        st07d1, body07d1 = call(base_url, "POST", "/api/training/queue/dispatch-next", {"operator": "uo-test"})
        st07d2, body07d2 = call(base_url, "POST", "/api/training/queue/dispatch-next", {"operator": "uo-test"})
        st07d3, body07d3 = call(base_url, "POST", "/api/training/queue/dispatch-next", {"operator": "uo-test"})
        api07d1 = api_file("ac_uo_07_dispatch_1", "POST", "/api/training/queue/dispatch-next", {"operator": "uo-test"}, st07d1, body07d1)
        api07d2 = api_file("ac_uo_07_dispatch_2", "POST", "/api/training/queue/dispatch-next", {"operator": "uo-test"}, st07d2, body07d2)
        api07d3 = api_file("ac_uo_07_dispatch_3", "POST", "/api/training/queue/dispatch-next", {"operator": "uo-test"}, st07d3, body07d3)
        qids07 = [
            str((body07d1.get("result") or {}).get("queue_task_id") or body07d1.get("queue_task_id") or ""),
            str((body07d2.get("result") or {}).get("queue_task_id") or body07d2.get("queue_task_id") or ""),
            str((body07d3.get("result") or {}).get("queue_task_id") or body07d3.get("queue_task_id") or ""),
        ]
        conn = sqlite3.connect(db_path.as_posix())
        conn.row_factory = sqlite3.Row
        try:
            rows07 = []
            for qid in qids07:
                if not qid:
                    continue
                row = conn.execute("SELECT queue_task_id,priority,enqueued_at,status FROM training_queue WHERE queue_task_id=?", (qid,)).fetchone()
                if row is not None:
                    rows07.append({k: row[k] for k in row.keys()})
        finally:
            conn.close()
        write_json(db_dir / "ac_uo_07_dispatch_priority.db.json", rows07)
        priorities = [str(r.get("priority") or "") for r in rows07[:3]]
        ac["AC-UO-07"] = {"pass": bool(st07d1 == 200 and st07d2 == 200 and st07d3 == 200 and priorities == ["P0", "P1", "P2"]), "api": [api07a, api07b, api07c, api07d1, api07d2, api07d3]}

        st11s, body11s = call(base_url, "GET", "/api/chat/sessions")
        api11s = api_file("ac_uo_11_sessions", "GET", "/api/chat/sessions", None, st11s, body11s)
        p11 = {
            "target_agent_id": alpha_id,
            "capability_goal": "decoupled training flow",
            "training_tasks": ["train without active chat session"],
            "acceptance_criteria": "training done",
            "priority": "P2",
            "trainer_match": trainer_name,
            "operator": "uo-test",
        }
        st11e, body11e = call(base_url, "POST", "/api/training/plans/manual", p11)
        api11e = api_file("ac_uo_11_enqueue", "POST", "/api/training/plans/manual", p11, st11e, body11e)
        qid11 = str(body11e.get("queue_task_id") or "")
        st11x, body11x = call(base_url, "POST", f"/api/training/queue/{qid11}/execute", {"operator": "uo-test"})
        api11x = api_file("ac_uo_11_execute", "POST", f"/api/training/queue/{qid11}/execute", {"operator": "uo-test"}, st11x, body11x)
        run11 = str(body11x.get("run_id") or "")
        st11r, body11r = call(base_url, "GET", f"/api/training/runs/{run11}")
        api11r = api_file("ac_uo_11_run", "GET", f"/api/training/runs/{run11}", None, st11r, body11r)
        sessions11 = list(body11s.get("items") or []) if isinstance(body11s, dict) else []
        ac["AC-UO-11"] = {
            "pass": bool(st11s == 200 and len(sessions11) == 0 and st11e == 200 and st11x == 200 and body11x.get("status") == "done" and st11r == 200 and body11r.get("status") == "done"),
            "api": [api11s, api11e, api11x, api11r],
        }
        dump_sql(db_path, "SELECT run_id,queue_task_id,status,run_ref,result_summary,updated_at FROM training_run WHERE run_id=?", (run11,), db_dir / "ac_uo_11_training_run.db.json")

        dump_sql(db_path, "SELECT audit_id,action,operator,target_id,detail_json,created_at FROM training_audit_log ORDER BY created_at DESC LIMIT 50", (), db_dir / "training_audit_log_tail.db.json")
        dump_sql(db_path, "SELECT queue_task_id,plan_id,priority,status,enqueued_at,started_at,finished_at FROM training_queue ORDER BY enqueued_at DESC LIMIT 50", (), db_dir / "training_queue_tail.db.json")
        dump_sql(db_path, "SELECT plan_id,source,target_agent_id,priority,similar_flag,created_at FROM training_plan ORDER BY created_at DESC LIMIT 50", (), db_dir / "training_plan_tail.db.json")

        edge = find_edge()
        shot_refs: dict[str, str] = {}
        probe_refs: dict[str, str] = {}

        def cap(name: str, case_id: str, extra: dict[str, str] | None = None) -> tuple[str, dict[str, Any]]:
            shot, probe_file, probe_data = capture_probe(edge, base_url, evidence_root, name, case_id, extra)
            shot_refs[name] = shot
            probe_refs[name] = probe_file
            return shot, probe_data

        shot01, probe01 = cap("ac_uo_01_entry", "ac_uo_01")
        shot02, probe02 = cap("ac_uo_02_detail", "ac_uo_02")
        shot03, probe03 = cap("ac_uo_03_published", "ac_uo_03")
        shot04, probe04 = cap("ac_uo_04_non_git", "ac_uo_04", {"tc_probe_agent": "beta-agent"})
        shot05b, _probe05b = cap("ac_uo_05_enqueue_before", "ac_uo_05_before")
        shot05a, probe05a = cap("ac_uo_05_enqueue_after", "ac_uo_05_after")
        shot06, probe06 = cap("ac_uo_06_priority_required", "ac_uo_06")
        shot07, probe07 = cap("ac_uo_07_dispatch", "ac_uo_07")
        shot08, probe08 = cap("ac_uo_08_similar", "ac_uo_08")
        shot09b, _probe09b = cap("ac_uo_09_remove_before", "ac_uo_09_before")
        shot09a, probe09a = cap("ac_uo_09_remove_after", "ac_uo_09_after")
        shot10, probe10 = cap("ac_uo_10_parallel_source", "ac_uo_10")
        shot11, probe11 = cap("ac_uo_11_decoupled", "ac_uo_11")

        gif_refs: dict[str, str] = {}
        gif01 = rec_dir / "ac_uo_01_entry.gif"
        gif02 = rec_dir / "ac_uo_02_detail.gif"
        gif05 = rec_dir / "ac_uo_05_enqueue.gif"
        gif09 = rec_dir / "ac_uo_09_remove.gif"
        make_gif(gif01, [Path(shot01)])
        make_gif(gif02, [Path(shot01), Path(shot02)])
        make_gif(gif05, [Path(shot05b), Path(shot05a)])
        make_gif(gif09, [Path(shot09b), Path(shot09a)])
        gif_refs["AC-UO-01"] = gif01.as_posix()
        gif_refs["AC-UO-02"] = gif02.as_posix()
        gif_refs["AC-UO-05"] = gif05.as_posix()
        gif_refs["AC-UO-09"] = gif09.as_posix()

        write_json(evidence_root / "screenshots_index.json", shot_refs)
        write_json(evidence_root / "probe_index.json", probe_refs)

        # apply probe pass supplement
        ac["AC-UO-01"]["pass"] = bool(ac["AC-UO-01"]["pass"] and probe01.get("pass"))
        ac["AC-UO-02"]["pass"] = bool(ac["AC-UO-02"]["pass"] and probe02.get("pass"))
        ac["AC-UO-03"]["pass"] = bool(ac["AC-UO-03"]["pass"] and probe03.get("pass"))
        ac["AC-UO-04"]["pass"] = bool(ac["AC-UO-04"]["pass"] and probe04.get("pass"))
        ac["AC-UO-05"]["pass"] = bool(ac["AC-UO-05"]["pass"] and probe05a.get("pass"))
        ac["AC-UO-06"]["pass"] = bool(ac["AC-UO-06"]["pass"] and probe06.get("pass"))
        ac["AC-UO-07"]["pass"] = bool(ac["AC-UO-07"]["pass"] and probe07.get("pass"))
        ac["AC-UO-08"]["pass"] = bool(ac["AC-UO-08"]["pass"] and probe08.get("pass"))
        ac["AC-UO-09"]["pass"] = bool(ac["AC-UO-09"]["pass"] and probe09a.get("pass"))
        ac["AC-UO-10"]["pass"] = bool(ac["AC-UO-10"]["pass"] and probe10.get("pass"))
        ac["AC-UO-11"]["pass"] = bool(ac["AC-UO-11"]["pass"] and probe11.get("pass"))

        ac_ev["AC-UO-01"] = {
            "screenshots": [shot01],
            "recordings": [gif_refs["AC-UO-01"]],
            "api": ac["AC-UO-01"]["api"],
            "db_or_logs": [(db_dir / "ac_uo_01_agent_registry.db.json").as_posix(), server_stdout.as_posix(), server_stderr.as_posix(), probe_refs["ac_uo_01_entry"]],
            "code": code_refs_common,
        }
        ac_ev["AC-UO-02"] = {
            "screenshots": [shot02],
            "recordings": [gif_refs["AC-UO-02"]],
            "api": ac["AC-UO-02"]["api"],
            "db_or_logs": [(db_dir / "ac_uo_03_release_history.db.json").as_posix(), probe_refs["ac_uo_02_detail"]],
            "code": code_refs_common,
        }
        ac_ev["AC-UO-03"] = {"screenshots": [shot03], "recordings": [], "api": ac["AC-UO-03"]["api"], "db_or_logs": [(db_dir / "ac_uo_03_release_history.db.json").as_posix(), probe_refs["ac_uo_03_published"]], "code": code_refs_common}
        ac_ev["AC-UO-04"] = {"screenshots": [shot04], "recordings": [], "api": ac["AC-UO-04"]["api"], "db_or_logs": [(db_dir / "ac_uo_04_non_git_plan_queue.db.json").as_posix(), probe_refs["ac_uo_04_non_git"]], "code": code_refs_common}
        ac_ev["AC-UO-05"] = {"screenshots": [shot05a], "recordings": [gif_refs["AC-UO-05"]], "api": ac["AC-UO-05"]["api"], "db_or_logs": [(db_dir / "ac_uo_05_plan_queue.db.json").as_posix(), probe_refs["ac_uo_05_enqueue_after"]], "code": code_refs_common}
        ac_ev["AC-UO-06"] = {"screenshots": [shot06], "recordings": [], "api": ac["AC-UO-06"]["api"], "db_or_logs": [server_stdout.as_posix(), server_stderr.as_posix(), probe_refs["ac_uo_06_priority_required"]], "code": code_refs_common}
        ac_ev["AC-UO-07"] = {"screenshots": [shot07], "recordings": [], "api": ac["AC-UO-07"]["api"], "db_or_logs": [(db_dir / "ac_uo_07_dispatch_priority.db.json").as_posix(), probe_refs["ac_uo_07_dispatch"]], "code": code_refs_common}
        ac_ev["AC-UO-08"] = {"screenshots": [shot08], "recordings": [], "api": ac["AC-UO-08"]["api"], "db_or_logs": [(db_dir / "ac_uo_08_similar_plan.db.json").as_posix(), (db_dir / "ac_uo_08_mark_similar_audit.db.json").as_posix(), probe_refs["ac_uo_08_similar"]], "code": code_refs_common}
        ac_ev["AC-UO-09"] = {"screenshots": [shot09a], "recordings": [gif_refs["AC-UO-09"]], "api": ac["AC-UO-09"]["api"], "db_or_logs": [(db_dir / "ac_uo_09_queue_removed.db.json").as_posix(), (db_dir / "ac_uo_09_remove_audit.db.json").as_posix(), probe_refs["ac_uo_09_remove_after"]], "code": code_refs_common}
        ac_ev["AC-UO-10"] = {"screenshots": [shot10], "recordings": [], "api": ac["AC-UO-10"]["api"], "db_or_logs": [(db_dir / "ac_uo_10_queue_sources.db.json").as_posix(), probe_refs["ac_uo_10_parallel_source"]], "code": code_refs_common}
        ac_ev["AC-UO-11"] = {"screenshots": [shot11], "recordings": [], "api": ac["AC-UO-11"]["api"], "db_or_logs": [(db_dir / "ac_uo_11_training_run.db.json").as_posix(), probe_refs["ac_uo_11_decoupled"]], "code": code_refs_common}

        coverage: dict[str, Any] = {}
        for idx in range(1, 12):
            ac_id = f"AC-UO-{idx:02d}"
            ev = ac_ev.get(ac_id, {})
            coverage[ac_id] = {
                "has_screenshot": bool(ev.get("screenshots")),
                "has_api": bool(ev.get("api")),
                "has_db_or_logs": bool(ev.get("db_or_logs")),
                "has_code": bool(ev.get("code")),
            }
        gif_cov = {ac_id: bool(ac_ev.get(ac_id, {}).get("recordings")) and Path(ac_ev[ac_id]["recordings"][0]).exists() for ac_id in REQ_GIF}
        matrix_json = evidence_root / "ac_uo_12_evidence_matrix.json"
        write_json(matrix_json, {"coverage": coverage, "required_gif_coverage": gif_cov, "screenshots": shot_refs, "recordings": gif_refs})

        matrix_html = evidence_root / "ac_uo_12_evidence_matrix.html"
        lines = [
            "<html><head><meta charset='utf-8'><style>",
            "body{font-family:Segoe UI,Arial,sans-serif;padding:16px;background:#f8fafc;color:#1f2937}",
            "h1{font-size:18px;margin:0 0 12px 0}",
            "table{border-collapse:collapse;width:100%;background:#fff}",
            "th,td{border:1px solid #d1d5db;padding:6px 8px;font-size:12px;text-align:left}",
            ".ok{color:#166534;font-weight:600}.bad{color:#b91c1c;font-weight:600}",
            "</style></head><body>",
            "<h1>AC-UO-12 Evidence Completeness</h1>",
            "<table><tr><th>AC</th><th>screenshot</th><th>api</th><th>db/log</th><th>code</th></tr>",
        ]
        for idx in range(1, 12):
            ac_id = f"AC-UO-{idx:02d}"
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
        lines.append("</table><h1 style='margin-top:16px'>Required GIF</h1><table><tr><th>AC</th><th>gif_ready</th></tr>")
        for ac_id, ok in gif_cov.items():
            lines.append(f"<tr><td>{ac_id}</td><td class='{'ok' if ok else 'bad'}'>{ok}</td></tr>")
        lines.append("</table></body></html>")
        matrix_html.write_text("\n".join(lines), encoding="utf-8")

        shot12 = shots_dir / "ac_uo_12_evidence_matrix.png"
        edge_shot(edge, matrix_html.resolve().as_uri(), shot12)

        ac["AC-UO-12"] = {"pass": bool(all(v["has_screenshot"] and v["has_api"] and v["has_db_or_logs"] and v["has_code"] for v in coverage.values()) and all(gif_cov.values())), "api": [matrix_json.as_posix()]}
        ac_ev["AC-UO-12"] = {
            "screenshots": [shot12.as_posix()],
            "recordings": [gif_refs[k] for k in REQ_GIF if k in gif_refs],
            "api": [matrix_json.as_posix()],
            "db_or_logs": [server_stdout.as_posix(), server_stderr.as_posix(), matrix_html.as_posix()],
            "code": [
                (repo_root / "scripts" / "acceptance" / "run_acceptance_training_center_uo.py").resolve().as_posix(),
                (repo_root / "src" / "workflow_app" / "web_client" / "training_center_and_bootstrap.js").resolve().as_posix(),
                (repo_root / "src" / "workflow_app" / "web_client" / "app_state_and_utils.js").resolve().as_posix(),
            ],
        }

        manifest = evidence_root / "ac_uo_evidence_manifest.json"
        write_json(manifest, ac_ev)

        summary_md = evidence_root / "ac_uo_summary.md"
        lines = [
            f"# AC-UO Acceptance Summary ({ts})",
            "",
            f"- runtime_root: {runtime_root.as_posix()}",
            f"- workspace_root: {workspace_root.as_posix()}",
            f"- db_path: {db_path.as_posix()}",
            f"- server_stdout: {server_stdout.as_posix()}",
            f"- server_stderr: {server_stderr.as_posix()}",
            f"- event_log_dir: {(runtime_root / 'logs' / 'events').as_posix()}",
            f"- screenshots_dir: {shots_dir.as_posix()}",
            f"- recordings_dir: {rec_dir.as_posix()}",
            f"- api_dir: {api_dir.as_posix()}",
            f"- db_dir: {db_dir.as_posix()}",
            f"- evidence_manifest: {manifest.as_posix()}",
            "",
            "| AC | pass | evidence |",
            "|---|---|---|",
        ]
        for ac_id in [f"AC-UO-{i:02d}" for i in range(1, 13)]:
            row = ac.get(ac_id, {"pass": False})
            ev = ac_ev.get(ac_id, {})
            refs = []
            if ev.get("screenshots"):
                refs.append("screenshot=" + "<br>".join(ev["screenshots"]))
            if ev.get("recordings"):
                refs.append("recording=" + "<br>".join(ev["recordings"]))
            if ev.get("api"):
                refs.append("api=" + "<br>".join(ev["api"]))
            if ev.get("db_or_logs"):
                refs.append("db/log=" + "<br>".join(ev["db_or_logs"]))
            if ev.get("code"):
                refs.append("code=" + "<br>".join(ev["code"]))
            lines.append(f"| {ac_id} | {'pass' if row.get('pass') else 'fail'} | {'<br><br>'.join(refs)} |")
        summary_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

        write_json(evidence_root / "ac_uo_summary.json", ac)
        print(summary_md.as_posix())
        return 0 if len(ac) == 12 and all(bool(v.get("pass")) for v in ac.values()) else 1
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())

