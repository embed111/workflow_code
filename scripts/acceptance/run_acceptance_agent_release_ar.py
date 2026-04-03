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

REQ_GIF = ("AC-AR-03", "AC-AR-04", "AC-AR-06", "AC-AR-08")


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
    proc = subprocess.run(args, cwd=cwd.as_posix(), capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError("cmd failed: " + " ".join(args) + "\n" + str(proc.stdout) + "\n" + str(proc.stderr))


def run_cmd_out(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(args, cwd=cwd.as_posix(), capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError("cmd failed: " + " ".join(args) + "\n" + str(proc.stdout) + "\n" + str(proc.stderr))
    return str(proc.stdout or "").strip()


def fixture_agents(workspace_root: Path) -> tuple[str, Path, Path]:
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
            "你是发布管理与训练治理助手。",
            "",
            "## 会话目标",
            "保障版本切换、训练门禁、发布评估的可追溯性。",
            "",
            "## 职责边界",
            "### must",
            "- 输出可验证证据。",
            "- 严格按发布版本执行切换。",
            "",
            "### must_not",
            "- 不做越界写入。",
            "- 禁止绕过门禁强行训练。",
        ]
    )
    (alpha / "AGENTS.md").write_text(agents_md + "\n", encoding="utf-8")
    (beta / "AGENTS.md").write_text(agents_md + "\n", encoding="utf-8")

    run_cmd(["git", "init"], alpha)
    run_cmd(["git", "config", "user.email", "ar-alpha@example.com"], alpha)
    run_cmd(["git", "config", "user.name", "ar-alpha"], alpha)
    run_cmd(["git", "add", "AGENTS.md"], alpha)
    run_cmd(["git", "commit", "-m", "init"], alpha)
    run_cmd(["git", "tag", "-a", "v1.0.0", "-m", "release note: baseline"], alpha)
    (alpha / "CHANGELOG.md").write_text("improve release\n", encoding="utf-8")
    run_cmd(["git", "add", "CHANGELOG.md"], alpha)
    run_cmd(["git", "commit", "-m", "improve release"], alpha)
    run_cmd(["git", "tag", "-a", "v1.1.0", "-m", "release note: improve release"], alpha)
    (alpha / "WIP.md").write_text("pre-release work\n", encoding="utf-8")
    run_cmd(["git", "add", "WIP.md"], alpha)
    run_cmd(["git", "commit", "-m", "wip pre release"], alpha)
    alpha_non_release = run_cmd_out(["git", "rev-parse", "--short", "HEAD"], alpha)

    run_cmd(["git", "init"], beta)
    run_cmd(["git", "config", "user.email", "ar-beta@example.com"], beta)
    run_cmd(["git", "config", "user.name", "ar-beta"], beta)
    run_cmd(["git", "add", "AGENTS.md"], beta)
    run_cmd(["git", "commit", "-m", "init"], beta)
    run_cmd(["git", "tag", "-a", "v1.0.0", "-m", "release note: beta baseline"], beta)
    (beta / "CHANGELOG.md").write_text("beta improve\n", encoding="utf-8")
    run_cmd(["git", "add", "CHANGELOG.md"], beta)
    run_cmd(["git", "commit", "-m", "beta improve"], beta)
    run_cmd(["git", "tag", "-a", "v1.1.0", "-m", "release note: beta improve"], beta)

    return alpha_non_release, alpha, beta


def find_agent(items: list[dict[str, Any]], name: str) -> dict[str, Any]:
    key = name.strip().lower()
    for row in items:
        if str(row.get("agent_name") or "").strip().lower() == key:
            return row
    raise RuntimeError(f"agent not found: {name}")


def find_agent_optional(items: list[dict[str, Any]], name: str) -> dict[str, Any]:
    key = name.strip().lower()
    for row in items:
        if str(row.get("agent_name") or "").strip().lower() == key:
            return row
        if str(row.get("agent_id") or "").strip().lower() == key:
            return row
    return {}


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
    parser = argparse.ArgumentParser(description="AC-AR-01~10 acceptance with UI evidence")
    parser.add_argument("--root", default=".", help="repo root")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8132)
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    runtime_root = (repo_root / ".test" / "runtime" / "agent-release-ar").resolve()
    evidence_root = (repo_root / ".test" / "evidence" / f"agent-release-ar-{ts}").resolve()
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
    alpha_non_release_commit, _alpha_path, _beta_path = fixture_agents(workspace_root)
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
        (repo_root / "src" / "workflow_app" / "web_client" / "policy_confirm_and_interactions.js").resolve().as_posix(),
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

        trainer_name = "trainer-ar"

        st_agents, body_agents = call(base_url, "GET", "/api/training/agents")
        api01 = api_file("ac_ar_01_agents", "GET", "/api/training/agents", None, st_agents, body_agents)
        items = list(body_agents.get("items") or [])
        alpha = find_agent(items, "alpha-agent")
        beta = find_agent(items, "beta-agent")
        alpha_id = str(alpha.get("agent_id") or "")
        beta_id = str(beta.get("agent_id") or "")
        ac["AC-AR-01"] = {"pass": bool(st_agents == 200 and len(items) >= 2), "api": [api01]}
        dump_sql(db_path, "SELECT agent_id,agent_name,workspace_path,current_version,latest_release_version,bound_release_version,lifecycle_state,training_gate_state,parent_agent_id FROM agent_registry ORDER BY agent_name", (), db_dir / "ac_ar_01_agent_registry.db.json")

        rel_path = f"/api/training/agents/{alpha_id}/releases?page=1&page_size=120"
        st_rel, body_rel = call(base_url, "GET", rel_path)
        api02 = api_file("ac_ar_02_releases", "GET", rel_path, None, st_rel, body_rel)
        releases = list(body_rel.get("releases") or [])
        has_commit_ref = any("commit_ref" in r for r in releases if isinstance(r, dict))
        ac["AC-AR-02"] = {"pass": bool(st_rel == 200 and len(releases) >= 2 and not has_commit_ref), "api": [api02]}
        dump_sql(db_path, "SELECT release_id,agent_id,version_label,released_at,change_summary,commit_ref,created_at FROM agent_release_history WHERE agent_id=? ORDER BY released_at DESC", (alpha_id,), db_dir / "ac_ar_02_release_history.db.json")

        p03 = {"version_label": alpha_non_release_commit, "operator": "ar-test"}
        st03, body03 = call(base_url, "POST", f"/api/training/agents/{alpha_id}/switch", p03)
        api03 = api_file("ac_ar_03_reject_non_release", "POST", f"/api/training/agents/{alpha_id}/switch", p03, st03, body03)
        ac["AC-AR-03"] = {"pass": bool(st03 == 409 and str(body03.get("code") or "") == "version_not_released"), "api": [api03]}

        p04s = {"version_label": "v1.0.0", "operator": "ar-test"}
        st04s, body04s = call(base_url, "POST", f"/api/training/agents/{alpha_id}/switch", p04s)
        api04s = api_file("ac_ar_04_switch_old", "POST", f"/api/training/agents/{alpha_id}/switch", p04s, st04s, body04s)
        p04t = {
            "target_agent_id": alpha_id,
            "capability_goal": "frozen agent cannot enqueue",
            "training_tasks": ["verify frozen gate block"],
            "acceptance_criteria": "must block",
            "priority": "P1",
            "trainer_match": trainer_name,
            "operator": "ar-test",
        }
        st04t, body04t = call(base_url, "POST", "/api/training/plans/manual", p04t)
        api04t = api_file("ac_ar_04_frozen_enqueue", "POST", "/api/training/plans/manual", p04t, st04t, body04t)
        st04a, body04a = call(base_url, "GET", "/api/training/agents")
        alpha04 = find_agent(list(body04a.get("items") or []), "alpha-agent")
        ac["AC-AR-04"] = {
            "pass": bool(st04s == 200 and st04t == 409 and str(body04t.get("code") or "") == "training_frozen_after_switch" and str(alpha04.get("training_gate_state") or "") == "frozen_switched"),
            "api": [api04s, api04t],
        }
        dump_sql(db_path, "SELECT agent_id,current_version,latest_release_version,bound_release_version,lifecycle_state,training_gate_state,updated_at FROM agent_registry WHERE agent_id=?", (alpha_id,), db_dir / "ac_ar_04_alpha_state.db.json")

        p05s = {"version_label": "v1.1.0", "operator": "ar-test"}
        st05s, body05s = call(base_url, "POST", f"/api/training/agents/{alpha_id}/switch", p05s)
        api05s = api_file("ac_ar_05_switch_latest", "POST", f"/api/training/agents/{alpha_id}/switch", p05s, st05s, body05s)
        p05t = {
            "target_agent_id": alpha_id,
            "capability_goal": "unfrozen enqueue check",
            "training_tasks": ["verify trainable gate"],
            "acceptance_criteria": "must enqueue",
            "priority": "P1",
            "trainer_match": trainer_name,
            "operator": "ar-test",
        }
        st05t, body05t = call(base_url, "POST", "/api/training/plans/manual", p05t)
        api05t = api_file("ac_ar_05_unfreeze_enqueue", "POST", "/api/training/plans/manual", p05t, st05t, body05t)
        st05a, body05a = call(base_url, "GET", "/api/training/agents")
        alpha05 = find_agent(list(body05a.get("items") or []), "alpha-agent")
        ac["AC-AR-05"] = {"pass": bool(st05s == 200 and st05t == 200 and str(alpha05.get("training_gate_state") or "") == "trainable"), "api": [api05s, api05t]}
        dump_sql(db_path, "SELECT queue_task_id,plan_id,status,priority,enqueued_at FROM training_queue WHERE queue_task_id=?", (str(body05t.get("queue_task_id") or ""),), db_dir / "ac_ar_05_queue.db.json")

        p06s = {"version_label": "v1.0.0", "operator": "ar-test"}
        st06s, body06s = call(base_url, "POST", f"/api/training/agents/{alpha_id}/switch", p06s)
        api06s = api_file("ac_ar_06_switch_old", "POST", f"/api/training/agents/{alpha_id}/switch", p06s, st06s, body06s)
        clone_name = f"{alpha_id}-clone-{str(int(time.time() * 1000))[-5:]}"
        p06c = {"new_agent_name": clone_name, "operator": "ar-test"}
        st06c, body06c = call(base_url, "POST", f"/api/training/agents/{alpha_id}/clone", p06c)
        api06c = api_file("ac_ar_06_clone", "POST", f"/api/training/agents/{alpha_id}/clone", p06c, st06c, body06c)
        clone_real_id = str(body06c.get("agent_id") or "")
        p06t = {
            "target_agent_id": clone_real_id,
            "capability_goal": "clone can enqueue",
            "training_tasks": ["verify clone trainable"],
            "acceptance_criteria": "clone queue created",
            "priority": "P1",
            "trainer_match": trainer_name,
            "operator": "ar-test",
        }
        st06t, body06t = call(base_url, "POST", "/api/training/plans/manual", p06t)
        api06t = api_file("ac_ar_06_clone_enqueue", "POST", "/api/training/plans/manual", p06t, st06t, body06t)
        st06a, body06a = call(base_url, "GET", "/api/training/agents")
        clone06 = find_agent_optional(list(body06a.get("items") or []), clone_real_id)
        ac["AC-AR-06"] = {
            "pass": bool(st06s == 200 and st06c == 200 and st06t == 200 and str(clone06.get("training_gate_state") or "") == "trainable"),
            "api": [api06s, api06c, api06t],
        }
        qid06 = str(body06t.get("queue_task_id") or "")
        dump_sql(db_path, "SELECT agent_id,parent_agent_id,current_version,latest_release_version,bound_release_version,lifecycle_state,training_gate_state FROM agent_registry WHERE agent_id=?", (clone_real_id,), db_dir / "ac_ar_06_clone_state.db.json")

        st07x, body07x = call(base_url, "POST", f"/api/training/queue/{qid06}/execute", {"operator": "ar-test"})
        api07x = api_file("ac_ar_07_execute_clone", "POST", f"/api/training/queue/{qid06}/execute", {"operator": "ar-test"}, st07x, body07x)
        st07a, body07a = call(base_url, "GET", "/api/training/agents")
        clone07 = find_agent_optional(list(body07a.get("items") or []), clone_real_id)
        ac["AC-AR-07"] = {
            "pass": bool(st07x == 200 and str(body07x.get("status") or "") == "done" and str(clone07.get("lifecycle_state") or "") == "pre_release"),
            "api": [api07x],
        }
        dump_sql(db_path, "SELECT run_id,queue_task_id,status,run_ref,result_summary,updated_at FROM training_run WHERE queue_task_id=? ORDER BY updated_at DESC", (qid06,), db_dir / "ac_ar_07_clone_run.db.json")

        st08_before, body08_before = call(base_url, "GET", "/api/training/agents")
        alpha08_before = find_agent_optional(list(body08_before.get("items") or []), "alpha-agent")
        p08d = {"operator": "ar-test"}
        st08d, body08d = call(base_url, "POST", f"/api/training/agents/{clone_real_id}/pre-release/discard", p08d)
        api08d = api_file("ac_ar_08_discard", "POST", f"/api/training/agents/{clone_real_id}/pre-release/discard", p08d, st08d, body08d)
        st08a, body08a = call(base_url, "GET", "/api/training/agents")
        clone08 = find_agent_optional(list(body08a.get("items") or []), clone_real_id)
        alpha08_after = find_agent_optional(list(body08a.get("items") or []), "alpha-agent")
        ac["AC-AR-08"] = {
            "pass": bool(st08d == 200 and bool(body08d.get("discarded")) and str(clone08.get("lifecycle_state") or "") == "released" and str(alpha08_before.get("training_gate_state") or "") == str(alpha08_after.get("training_gate_state") or "")),
            "api": [api08d],
        }
        dump_sql(db_path, "SELECT agent_id,lifecycle_state,training_gate_state,current_version,bound_release_version,updated_at FROM agent_registry WHERE agent_id IN (?,?) ORDER BY agent_id", (clone_real_id, alpha_id), db_dir / "ac_ar_08_states.db.json")

        p09t1 = {
            "target_agent_id": beta_id,
            "capability_goal": "beta eval prepare 1",
            "training_tasks": ["beta training 1"],
            "acceptance_criteria": "to pre-release",
            "priority": "P1",
            "trainer_match": trainer_name,
            "operator": "ar-test",
        }
        st09t1, body09t1 = call(base_url, "POST", "/api/training/plans/manual", p09t1)
        qid09_1 = str(body09t1.get("queue_task_id") or "")
        st09x1, body09x1 = call(base_url, "POST", f"/api/training/queue/{qid09_1}/execute", {"operator": "ar-test"})
        p09e1 = {"decision": "reject_continue_training", "reviewer": "ar-reviewer", "summary": "continue training", "operator": "ar-test"}
        st09e1, body09e1 = call(base_url, "POST", f"/api/training/agents/{beta_id}/release-evaluations/manual", p09e1)
        api09e1 = api_file("ac_ar_09_eval_reject_continue", "POST", f"/api/training/agents/{beta_id}/release-evaluations/manual", p09e1, st09e1, body09e1)
        p09e2 = {"decision": "reject_discard", "reviewer": "ar-reviewer", "summary": "discard pre release", "operator": "ar-test"}
        st09e2, body09e2 = call(base_url, "POST", f"/api/training/agents/{beta_id}/release-evaluations/manual", p09e2)
        api09e2 = api_file("ac_ar_09_eval_reject_discard", "POST", f"/api/training/agents/{beta_id}/release-evaluations/manual", p09e2, st09e2, body09e2)
        p09t2 = {
            "target_agent_id": beta_id,
            "capability_goal": "beta eval prepare 2",
            "training_tasks": ["beta training 2"],
            "acceptance_criteria": "to pre-release for approve",
            "priority": "P1",
            "trainer_match": trainer_name,
            "operator": "ar-test",
        }
        st09t2, body09t2 = call(base_url, "POST", "/api/training/plans/manual", p09t2)
        qid09_2 = str(body09t2.get("queue_task_id") or "")
        st09x2, body09x2 = call(base_url, "POST", f"/api/training/queue/{qid09_2}/execute", {"operator": "ar-test"})
        p09e3 = {"decision": "approve", "reviewer": "ar-reviewer", "summary": "approve release", "operator": "ar-test"}
        st09e3, body09e3 = call(base_url, "POST", f"/api/training/agents/{beta_id}/release-evaluations/manual", p09e3)
        api09e3 = api_file("ac_ar_09_eval_approve", "POST", f"/api/training/agents/{beta_id}/release-evaluations/manual", p09e3, st09e3, body09e3)
        st09a, body09a = call(base_url, "GET", "/api/training/agents")
        beta09 = find_agent_optional(list(body09a.get("items") or []), "beta-agent")
        ac["AC-AR-09"] = {
            "pass": bool(st09t1 == 200 and st09x1 == 200 and st09e1 == 200 and str(body09e1.get("decision") or "") == "reject_continue_training" and st09e2 == 200 and str(body09e2.get("decision") or "") == "reject_discard" and st09t2 == 200 and st09x2 == 200 and st09e3 == 200 and str(body09e3.get("decision") or "") == "approve" and str(beta09.get("lifecycle_state") or "") == "released"),
            "api": [api09e1, api09e2, api09e3],
        }
        dump_sql(db_path, "SELECT evaluation_id,agent_id,target_version,decision,reviewer,summary,created_at FROM agent_release_evaluation ORDER BY created_at DESC LIMIT 30", (), db_dir / "ac_ar_09_release_evaluations.db.json")
        dump_sql(db_path, "SELECT audit_id,action,target_id,detail_json,created_at FROM training_audit_log WHERE action IN ('manual_release_evaluation','discard_pre_release','switch_release','clone_agent') ORDER BY created_at DESC LIMIT 80", (), db_dir / "ac_ar_09_audit.db.json")

        dump_sql(db_path, "SELECT queue_task_id,plan_id,priority,status,enqueued_at,started_at,finished_at FROM training_queue ORDER BY enqueued_at DESC LIMIT 80", (), db_dir / "training_queue_tail.db.json")
        dump_sql(db_path, "SELECT run_id,queue_task_id,status,run_ref,result_summary,updated_at FROM training_run ORDER BY updated_at DESC LIMIT 80", (), db_dir / "training_run_tail.db.json")
        dump_sql(db_path, "SELECT audit_id,action,operator,target_id,detail_json,created_at FROM training_audit_log ORDER BY created_at DESC LIMIT 120", (), db_dir / "training_audit_tail.db.json")

        edge = find_edge()
        shot_refs: dict[str, str] = {}
        probe_refs: dict[str, str] = {}

        def cap(name: str, case_id: str, extra: dict[str, str] | None = None) -> tuple[str, dict[str, Any]]:
            shot, probe_file, probe_data = capture_probe(edge, base_url, evidence_root, name, case_id, extra)
            shot_refs[name] = shot
            probe_refs[name] = probe_file
            return shot, probe_data

        shot01, probe01 = cap("ac_ar_01_overview", "ac_ar_01")
        shot02, probe02 = cap("ac_ar_02_releases", "ac_ar_02")
        shot03, probe03 = cap("ac_ar_03_reject", "ac_ar_03")
        shot04, probe04 = cap("ac_ar_04_frozen", "ac_ar_04")
        shot05, probe05 = cap("ac_ar_05_unfreeze", "ac_ar_05")
        shot06, probe06 = cap("ac_ar_06_clone", "ac_ar_06")
        shot07, probe07 = cap("ac_ar_07_pre_release", "ac_ar_07")
        shot08, probe08 = cap("ac_ar_08_discard", "ac_ar_08")
        shot09, probe09 = cap("ac_ar_09_manual_eval", "ac_ar_09")

        gif_refs: dict[str, str] = {}
        gif03 = rec_dir / "ac_ar_03_reject.gif"
        gif04 = rec_dir / "ac_ar_04_frozen.gif"
        gif06 = rec_dir / "ac_ar_06_clone.gif"
        gif08 = rec_dir / "ac_ar_08_discard.gif"
        make_gif(gif03, [Path(shot02), Path(shot03)])
        make_gif(gif04, [Path(shot03), Path(shot04)])
        make_gif(gif06, [Path(shot05), Path(shot06)])
        make_gif(gif08, [Path(shot07), Path(shot08)])
        gif_refs["AC-AR-03"] = gif03.as_posix()
        gif_refs["AC-AR-04"] = gif04.as_posix()
        gif_refs["AC-AR-06"] = gif06.as_posix()
        gif_refs["AC-AR-08"] = gif08.as_posix()

        write_json(evidence_root / "screenshots_index.json", shot_refs)
        write_json(evidence_root / "probe_index.json", probe_refs)

        ac["AC-AR-01"]["pass"] = bool(ac["AC-AR-01"]["pass"])
        ac["AC-AR-02"]["pass"] = bool(ac["AC-AR-02"]["pass"])
        ac["AC-AR-03"]["pass"] = bool(ac["AC-AR-03"]["pass"])
        ac["AC-AR-04"]["pass"] = bool(ac["AC-AR-04"]["pass"])
        ac["AC-AR-05"]["pass"] = bool(ac["AC-AR-05"]["pass"])
        ac["AC-AR-06"]["pass"] = bool(ac["AC-AR-06"]["pass"])
        ac["AC-AR-07"]["pass"] = bool(ac["AC-AR-07"]["pass"])
        ac["AC-AR-08"]["pass"] = bool(ac["AC-AR-08"]["pass"])
        ac["AC-AR-09"]["pass"] = bool(ac["AC-AR-09"]["pass"])

        ac_ev["AC-AR-01"] = {"screenshots": [shot01], "recordings": [], "api": ac["AC-AR-01"]["api"], "db_or_logs": [(db_dir / "ac_ar_01_agent_registry.db.json").as_posix(), server_stdout.as_posix(), server_stderr.as_posix(), probe_refs["ac_ar_01_overview"]], "code": code_refs_common}
        ac_ev["AC-AR-02"] = {"screenshots": [shot02], "recordings": [], "api": ac["AC-AR-02"]["api"], "db_or_logs": [(db_dir / "ac_ar_02_release_history.db.json").as_posix(), probe_refs["ac_ar_02_releases"]], "code": code_refs_common}
        ac_ev["AC-AR-03"] = {"screenshots": [shot03], "recordings": [gif_refs["AC-AR-03"]], "api": ac["AC-AR-03"]["api"], "db_or_logs": [server_stdout.as_posix(), server_stderr.as_posix(), probe_refs["ac_ar_03_reject"]], "code": code_refs_common}
        ac_ev["AC-AR-04"] = {"screenshots": [shot04], "recordings": [gif_refs["AC-AR-04"]], "api": ac["AC-AR-04"]["api"], "db_or_logs": [(db_dir / "ac_ar_04_alpha_state.db.json").as_posix(), probe_refs["ac_ar_04_frozen"]], "code": code_refs_common}
        ac_ev["AC-AR-05"] = {"screenshots": [shot05], "recordings": [], "api": ac["AC-AR-05"]["api"], "db_or_logs": [(db_dir / "ac_ar_05_queue.db.json").as_posix(), probe_refs["ac_ar_05_unfreeze"]], "code": code_refs_common}
        ac_ev["AC-AR-06"] = {"screenshots": [shot06], "recordings": [gif_refs["AC-AR-06"]], "api": ac["AC-AR-06"]["api"], "db_or_logs": [(db_dir / "ac_ar_06_clone_state.db.json").as_posix(), probe_refs["ac_ar_06_clone"]], "code": code_refs_common}
        ac_ev["AC-AR-07"] = {"screenshots": [shot07], "recordings": [], "api": ac["AC-AR-07"]["api"], "db_or_logs": [(db_dir / "ac_ar_07_clone_run.db.json").as_posix(), probe_refs["ac_ar_07_pre_release"]], "code": code_refs_common}
        ac_ev["AC-AR-08"] = {"screenshots": [shot08], "recordings": [gif_refs["AC-AR-08"]], "api": ac["AC-AR-08"]["api"], "db_or_logs": [(db_dir / "ac_ar_08_states.db.json").as_posix(), probe_refs["ac_ar_08_discard"]], "code": code_refs_common}
        ac_ev["AC-AR-09"] = {"screenshots": [shot09], "recordings": [], "api": ac["AC-AR-09"]["api"], "db_or_logs": [(db_dir / "ac_ar_09_release_evaluations.db.json").as_posix(), (db_dir / "ac_ar_09_audit.db.json").as_posix(), probe_refs["ac_ar_09_manual_eval"]], "code": code_refs_common}

        coverage: dict[str, Any] = {}
        for idx in range(1, 10):
            ac_id = f"AC-AR-{idx:02d}"
            ev = ac_ev.get(ac_id, {})
            coverage[ac_id] = {
                "has_screenshot": bool(ev.get("screenshots")),
                "has_api": bool(ev.get("api")),
                "has_db_or_logs": bool(ev.get("db_or_logs")),
                "has_code": bool(ev.get("code")),
            }
        gif_cov = {ac_id: bool(ac_ev.get(ac_id, {}).get("recordings")) and Path(ac_ev[ac_id]["recordings"][0]).exists() for ac_id in REQ_GIF}
        matrix_json = evidence_root / "ac_ar_10_evidence_matrix.json"
        write_json(matrix_json, {"coverage": coverage, "required_gif_coverage": gif_cov, "screenshots": shot_refs, "recordings": gif_refs})

        matrix_html = evidence_root / "ac_ar_10_evidence_matrix.html"
        lines = [
            "<html><head><meta charset='utf-8'><style>",
            "body{font-family:Segoe UI,Arial,sans-serif;padding:16px;background:#f8fafc;color:#1f2937}",
            "h1{font-size:18px;margin:0 0 12px 0}",
            "table{border-collapse:collapse;width:100%;background:#fff}",
            "th,td{border:1px solid #d1d5db;padding:6px 8px;font-size:12px;text-align:left}",
            ".ok{color:#166534;font-weight:600}.bad{color:#b91c1c;font-weight:600}",
            "</style></head><body>",
            "<h1>AC-AR-10 Evidence Completeness</h1>",
            "<table><tr><th>AC</th><th>screenshot</th><th>api</th><th>db/log</th><th>code</th></tr>",
        ]
        for idx in range(1, 10):
            ac_id = f"AC-AR-{idx:02d}"
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

        shot10 = shots_dir / "ac_ar_10_evidence_matrix.png"
        edge_shot(edge, matrix_html.resolve().as_uri(), shot10)

        ac["AC-AR-10"] = {
            "pass": bool(all(v["has_screenshot"] and v["has_api"] and v["has_db_or_logs"] and v["has_code"] for v in coverage.values()) and all(gif_cov.values())),
            "api": [matrix_json.as_posix()],
        }
        ac_ev["AC-AR-10"] = {
            "screenshots": [shot10.as_posix()],
            "recordings": [gif_refs[k] for k in REQ_GIF if k in gif_refs],
            "api": [matrix_json.as_posix()],
            "db_or_logs": [server_stdout.as_posix(), server_stderr.as_posix(), matrix_html.as_posix()],
            "code": [
                (repo_root / "scripts" / "acceptance" / "run_acceptance_agent_release_ar.py").resolve().as_posix(),
                (repo_root / "src" / "workflow_app" / "web_client" / "training_center_and_bootstrap.js").resolve().as_posix(),
            ],
        }

        manifest = evidence_root / "ac_ar_evidence_manifest.json"
        write_json(manifest, ac_ev)

        summary_md = evidence_root / "ac_ar_summary.md"
        lines = [
            f"# AC-AR Acceptance Summary ({ts})",
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
        for ac_id in [f"AC-AR-{i:02d}" for i in range(1, 11)]:
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

        write_json(evidence_root / "ac_ar_summary.json", ac)
        print(summary_md.as_posix())
        return 0 if len(ac) == 10 and all(bool(v.get("pass")) for v in ac.values()) else 1
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())

