#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from agent_release_review_acceptance_support import fixture_agents, write_codex_stub


REQ_GIF = ("AC-AR-10", "AC-AR-12", "AC-AR-14")


def call(base_url: str, method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url=base_url + path, data=data, method=method, headers=headers)
    try:
        with urlopen(req, timeout=60) as resp:
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
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status, payload = call(base_url, "GET", "/healthz")
        if status == 200 and bool(payload.get("ok")):
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


def ui_rel(root: Path, path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(root.resolve(strict=False)).as_posix()
    except Exception:
        return path.resolve(strict=False).as_posix()


def seed_release_report_assets(root: Path, agent_name: str, version_label: str) -> dict[str, str]:
    seed_dir = root / "logs" / "release-review" / "seeded-history" / agent_name / version_label
    report_path = seed_dir / "parsed-result.json"
    capability_snapshot_path = seed_dir / "capability-snapshot.json"
    public_profile_path = seed_dir / "public-profile.md"
    report_payload = {
        "target_version": version_label,
        "current_workspace_ref": f"{agent_name}-{version_label}-baseline",
        "previous_release_version": "",
        "first_person_summary": f"我是 {agent_name} {version_label}，我当前负责该正式版本的发布治理基线与能力说明。",
        "full_capability_inventory": [
            f"我当前可以围绕 {version_label} 输出完整的第一人称角色能力介绍。",
            "我当前可以对外说明本版本的发布治理职责、风险边界与验证依据。",
            "我当前可以为历史正式版本提供可追溯的发布报告展示来源。",
        ],
        "knowledge_scope": "我当前覆盖发布治理基线、角色画像整理、验证证据归档与正式版本说明。",
        "agent_skills": ["release-governance", "historical-report-binding"],
        "applicable_scenarios": ["历史发布报告查看", "角色详情回溯", "正式版本差异说明"],
        "change_summary": f"我在 {version_label} 中沉淀了历史正式版本可读的发布报告与角色能力说明。",
        "capability_delta": [
            f"我在 {version_label} 中补齐了历史发布报告的第一人称全量能力描述。",
            "我补充了历史版本可回溯的风险与验证证据说明。",
        ],
        "risk_list": ["我当前识别到的风险是：若历史报告文件缺失，将无法按版本查看历史评审内容。"],
        "validation_evidence": [
            f"我当前已确认的验证证据是：{version_label} 的结构化发布报告、能力快照与公开介绍文件均已落盘。"
        ],
        "release_recommendation": "approve",
        "next_action_suggestion": f"我建议在查看 {version_label} 历史版本时直接复用这份发布报告。",
        "warnings": [],
    }
    capability_snapshot_payload = {
        "target_version": version_label,
        "first_person_summary": report_payload["first_person_summary"],
        "full_capability_inventory": report_payload["full_capability_inventory"],
        "knowledge_scope": report_payload["knowledge_scope"],
        "agent_skills": report_payload["agent_skills"],
        "applicable_scenarios": report_payload["applicable_scenarios"],
    }
    write_json(report_path, report_payload)
    write_json(capability_snapshot_path, capability_snapshot_payload)
    public_profile_path.parent.mkdir(parents=True, exist_ok=True)
    public_profile_path.write_text(
        "\n".join(
            [
                f"# {agent_name} {version_label}",
                "",
                report_payload["first_person_summary"],
                "",
                "## 我能做什么",
                *[f"- {item}" for item in report_payload["full_capability_inventory"]],
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "release_source_ref": ui_rel(root, report_path),
        "public_profile_ref": ui_rel(root, public_profile_path),
        "capability_snapshot_ref": ui_rel(root, capability_snapshot_path),
    }


def seed_release_history_refs(
    db_path: Path,
    agent_id: str,
    version_label: str,
    refs: dict[str, str],
) -> None:
    conn = sqlite3.connect(db_path.as_posix())
    try:
        cur = conn.execute(
            """
            UPDATE agent_release_history
            SET release_source_ref=?,
                public_profile_ref=?,
                capability_snapshot_ref=?
            WHERE agent_id=?
              AND version_label=?
              AND COALESCE(classification,'normal_commit')='release'
            """,
            (
                str(refs.get("release_source_ref") or ""),
                str(refs.get("public_profile_ref") or ""),
                str(refs.get("capability_snapshot_ref") or ""),
                str(agent_id or ""),
                str(version_label or ""),
            ),
        )
        if int(cur.rowcount or 0) < 1:
            raise RuntimeError(f"seed release refs failed: {agent_id} {version_label}")
        conn.commit()
    finally:
        conn.close()


def run_cmd(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    proc = subprocess.run(args, cwd=cwd.as_posix(), capture_output=True, text=True, encoding="utf-8", env=env)
    if proc.returncode != 0:
        raise RuntimeError("cmd failed: " + " ".join(args) + "\n" + str(proc.stdout) + "\n" + str(proc.stderr))


def find_agent(items: list[dict[str, Any]], name: str) -> dict[str, Any]:
    key = name.strip().lower()
    for row in items:
        if str(row.get("agent_name") or "").strip().lower() == key:
            return row
    raise RuntimeError(f"agent not found: {name}")


def find_browser() -> Path:
    candidates = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ]
    for path in candidates:
        if path.exists() and path.is_file():
            return path
    raise RuntimeError("headless browser not found")


def edge_shot(browser_path: Path, url: str, shot_path: Path, width: int = 1440, height: int = 1500, budget_ms: int = 15000) -> None:
    shot_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="workflow-edge-shot-") as user_data_dir:
        cmd = [
            str(browser_path),
            "--headless=new",
            "--disable-gpu",
            "--disable-background-networking",
            "--disable-extensions",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={Path(user_data_dir).as_posix()}",
            f"--window-size={width},{height}",
            f"--virtual-time-budget={max(1000, int(budget_ms))}",
            f"--screenshot={shot_path.as_posix()}",
            url,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=180)
    if proc.returncode != 0:
        raise RuntimeError(f"browser screenshot failed: {proc.stderr}")


def edge_dom(browser_path: Path, url: str, width: int = 1440, height: int = 1500, budget_ms: int = 15000) -> str:
    with tempfile.TemporaryDirectory(prefix="workflow-edge-dom-") as user_data_dir:
        cmd = [
            str(browser_path),
            "--headless=new",
            "--disable-gpu",
            "--disable-background-networking",
            "--disable-extensions",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={Path(user_data_dir).as_posix()}",
            f"--window-size={width},{height}",
            f"--virtual-time-budget={max(1000, int(budget_ms))}",
            "--dump-dom",
            url,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=180)
    if proc.returncode != 0:
        raise RuntimeError(f"browser dump-dom failed: {proc.stderr}")
    return proc.stdout


def parse_probe(dom_text: str) -> dict[str, Any]:
    if "trainingCenterProbeOutput" not in dom_text:
        raise RuntimeError("trainingCenterProbeOutput_not_found")
    start = dom_text.find("trainingCenterProbeOutput")
    pre_start = dom_text.rfind("<pre", 0, start)
    pre_end = dom_text.find("</pre>", start)
    if pre_start < 0 or pre_end < 0:
        raise RuntimeError("trainingCenterProbeOutput_not_found")
    pre_html = dom_text[pre_start:pre_end]
    tag_end = pre_html.find(">")
    if tag_end < 0:
        raise RuntimeError("trainingCenterProbeOutput_invalid")
    raw = html.unescape(pre_html[tag_end + 1 :]).strip()
    if not raw:
        raise RuntimeError("trainingCenterProbeOutput_empty")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError("trainingCenterProbeOutput_not_dict")
    return payload


def ps_quote(text: str) -> str:
    return "'" + str(text or "").replace("'", "''") + "'"


def make_gif(gif_path: Path, frames: list[Path]) -> None:
    use_frames = [frame.resolve(strict=False) for frame in frames if frame and frame.exists()]
    if not use_frames:
        raise RuntimeError(f"gif frames missing: {gif_path.as_posix()}")
    frames_literal = ",".join([ps_quote(path.as_posix()) for path in use_frames])
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
    query: dict[str, str] = {"tc_probe": "1", "tc_probe_case": str(case_id), "_ts": str(int(time.time() * 1000))}
    if extra:
        for key, value in extra.items():
            query[str(key)] = str(value)
    return base_url.rstrip("/") + "/?" + urlencode(query)


def capture_probe(
    browser_path: Path,
    base_url: str,
    evidence_root: Path,
    name: str,
    case_id: str,
    extra: dict[str, str] | None = None,
    *,
    budget_ms: int = 15000,
) -> tuple[str, str, dict[str, Any]]:
    url = tc_probe_url(base_url, case_id, extra)
    shot = evidence_root / "screenshots" / f"{name}.png"
    probe_file = evidence_root / "screenshots" / f"{name}.probe.json"
    edge_shot(browser_path, url, shot, budget_ms=budget_ms)
    probe = parse_probe(edge_dom(browser_path, url, budget_ms=budget_ms))
    write_json(probe_file, probe)
    return shot.as_posix(), probe_file.as_posix(), probe


def wait_review_state(base_url: str, agent_id: str, expected: str, timeout_s: int = 20) -> tuple[int, dict[str, Any]]:
    deadline = time.time() + timeout_s
    last_status = 0
    last_payload: dict[str, Any] = {}
    while time.time() < deadline:
        last_status, last_payload = call(base_url, "GET", f"/api/training/agents/{agent_id}/release-review")
        review = last_payload.get("review") if isinstance(last_payload, dict) else {}
        if last_status == 200 and str((review or {}).get("release_review_state") or "").strip().lower() == expected:
            return last_status, last_payload
        time.sleep(0.3)
    raise RuntimeError(f"wait review state timeout: {agent_id} -> {expected} last={last_status} {last_payload}")


def api_file(api_dir: Path, name: str, method: str, path: str, payload: dict[str, Any] | None, status: int, body: dict[str, Any]) -> str:
    out = api_dir / f"{name}.api.json"
    write_json(out, {"request": {"method": method, "path": path, "payload": payload}, "response": {"status": status, "body": body}})
    return out.as_posix()


def ensure(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    parser = argparse.ArgumentParser(description="AC-AR-09~15 acceptance with UI evidence")
    parser.add_argument("--root", default=".", help="repo root")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8133)
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    runtime_root = (repo_root / ".test" / "runtime" / "agent-release-review-ar09-ar15").resolve()
    evidence_root = (repo_root / ".test" / "evidence" / f"agent-release-review-ar09-ar15-{ts}").resolve()
    api_dir = evidence_root / "api"
    db_dir = evidence_root / "db"
    shots_dir = evidence_root / "screenshots"
    rec_dir = evidence_root / "recordings"
    for directory in [evidence_root, api_dir, db_dir, shots_dir, rec_dir]:
        directory.mkdir(parents=True, exist_ok=True)

    if runtime_root.exists():
        shutil.rmtree(runtime_root, ignore_errors=True)
    runtime_root.mkdir(parents=True, exist_ok=True)

    workspace_root = runtime_root / "workspace-root"
    fixture_agents(workspace_root)
    db_path = runtime_root / "state" / "workflow.db"
    stub_bin = runtime_root / "bin"
    write_codex_stub(stub_bin)

    base_url = f"http://{args.host}:{args.port}"
    server_stdout = evidence_root / "server.stdout.log"
    server_stderr = evidence_root / "server.stderr.log"
    server_env = os.environ.copy()
    server_env["PATH"] = stub_bin.as_posix() + os.pathsep + server_env.get("PATH", "")
    server_env["WORKFLOW_RELEASE_REVIEW_CODEX_TIMEOUT_S"] = "30"
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
        env=server_env,
    )

    ac: dict[str, dict[str, Any]] = {}
    ac_ev: dict[str, dict[str, list[str]]] = {}
    code_refs_common = [
        (repo_root / "src" / "workflow_app" / "server" / "services" / "release_management_service.py").resolve().as_posix(),
        (repo_root / "src" / "workflow_app" / "server" / "services" / "training_registry_service.py").resolve().as_posix(),
        (repo_root / "src" / "workflow_app" / "server" / "infra" / "db" / "migrations.py").resolve().as_posix(),
        (repo_root / "src" / "workflow_app" / "web_client" / "training_center_and_bootstrap.js").resolve().as_posix(),
        (repo_root / "scripts" / "acceptance" / "run_acceptance_agent_release_review_ar09_ar15.py").resolve().as_posix(),
    ]

    try:
        wait_health(base_url)
        browser = find_browser()

        setup_payload = {"agent_search_root": workspace_root.as_posix()}
        st_sw, body_sw = call(base_url, "POST", "/api/config/agent-search-root", setup_payload)
        api_file(api_dir, "setup_switch_root", "POST", "/api/config/agent-search-root", setup_payload, st_sw, body_sw)
        ensure(st_sw == 200 and bool(body_sw.get("ok")), f"switch root failed: {st_sw} {body_sw}")

        st_agents, body_agents = call(base_url, "GET", "/api/training/agents")
        api_agents = api_file(api_dir, "agents_initial", "GET", "/api/training/agents", None, st_agents, body_agents)
        ensure(st_agents == 200, f"list agents failed: {st_agents} {body_agents}")
        items = list(body_agents.get("items") or [])
        success_id = str(find_agent(items, "success-agent").get("agent_id") or "")
        reject_id = str(find_agent(items, "reject-agent").get("agent_id") or "")
        publish_fail_id = str(find_agent(items, "publish-fail-agent").get("agent_id") or "")
        report_fail_id = str(find_agent(items, "report-fail-agent").get("agent_id") or "")
        no_git_id = str(find_agent(items, "no-git-agent").get("agent_id") or "")
        legacy_analyst2_id = str(find_agent(items, "legacy-analyst2-agent").get("agent_id") or "")
        seed_release_history_refs(
            db_path,
            success_id,
            "v1.0.0",
            seed_release_report_assets(runtime_root, "success-agent", "v1.0.0"),
        )

        enter_results: dict[str, tuple[int, dict[str, Any]]] = {}

        def do_success_enter() -> None:
            enter_results["success"] = call(base_url, "POST", f"/api/training/agents/{success_id}/release-review/enter", {"operator": "ar-reviewer"})

        enter_thread = threading.Thread(target=do_success_enter, daemon=True)
        enter_thread.start()
        st09r, body09r = wait_review_state(base_url, success_id, "report_generating", timeout_s=10)
        api09_get = api_file(api_dir, "ac_ar_09_review_running", "GET", f"/api/training/agents/{success_id}/release-review", None, st09r, body09r)
        shot09, probe09, probe09_payload = capture_probe(
            browser,
            base_url,
            evidence_root,
            "ac_ar_09_enter_release_review",
            "ac_ar_rr_09",
            {"tc_probe_agent": "success-agent"},
            budget_ms=900,
        )
        enter_thread.join(timeout=40)
        ensure(not enter_thread.is_alive(), "success-agent enter thread timeout")
        st10_enter, body10_enter = enter_results["success"]
        api10_enter = api_file(api_dir, "ac_ar_10_enter_success_agent", "POST", f"/api/training/agents/{success_id}/release-review/enter", {"operator": "ar-reviewer"}, st10_enter, body10_enter)
        st10r, body10r = wait_review_state(base_url, success_id, "report_ready", timeout_s=10)
        api10_get = api_file(api_dir, "ac_ar_10_review_ready", "GET", f"/api/training/agents/{success_id}/release-review", None, st10r, body10r)
        dump_sql(db_path, "SELECT review_id,agent_id,target_version,current_workspace_ref,release_review_state,prompt_version,public_profile_markdown_path,capability_snapshot_json_path,report_error,created_at,updated_at FROM agent_release_review WHERE agent_id=? ORDER BY created_at DESC", (success_id,), db_dir / "ac_ar_10_success_review.db.json")
        shot10, probe10, probe10_payload = capture_probe(browser, base_url, evidence_root, "ac_ar_10_report_ready", "ac_ar_rr_10", {"tc_probe_agent": "success-agent"})

        review10 = body10r.get("review", {}) if isinstance(body10r, dict) else {}
        report10 = review10.get("report", {}) if isinstance(review10, dict) else {}
        chain10 = review10.get("analysis_chain", {}) if isinstance(review10, dict) else {}
        ac["AC-AR-09"] = {"pass": bool(st09r == 200 and str(body09r.get("review", {}).get("release_review_state") or "") == "report_generating"), "api": [api09_get, api_agents]}
        ac_ev["AC-AR-09"] = {"screenshots": [shot09], "recordings": [], "api": [api09_get], "db_or_logs": [(db_dir / "ac_ar_10_success_review.db.json").as_posix(), probe09, server_stdout.as_posix(), server_stderr.as_posix()], "code": code_refs_common}
        ac["AC-AR-10"] = {"pass": bool(st10_enter == 200 and st10r == 200 and probe10_payload.get("pass") and str(review10.get("release_review_state") or "") == "report_ready" and str(report10.get("first_person_summary") or "").startswith("我") and bool(report10.get("full_capability_inventory")) and bool(report10.get("capability_delta")) and all(str(chain10.get(key) or "").strip() for key in ("prompt_path", "stdout_path", "stderr_path", "report_path"))), "api": [api10_enter, api10_get]}
        ac_ev["AC-AR-10"] = {"screenshots": [shot10], "recordings": [], "api": [api10_enter, api10_get], "db_or_logs": [probe10, str(chain10.get("prompt_path") or ""), str(chain10.get("stdout_path") or ""), str(chain10.get("stderr_path") or ""), str(chain10.get("report_path") or ""), str(review10.get("public_profile_markdown_path") or ""), str(review10.get("capability_snapshot_json_path") or "")], "code": code_refs_common}

        st10l_e, body10l_e = call(base_url, "POST", f"/api/training/agents/{legacy_analyst2_id}/release-review/enter", {"operator": "ar-reviewer"})
        api10l_e = api_file(api_dir, "reg_a2_01_enter_legacy_analyst2", "POST", f"/api/training/agents/{legacy_analyst2_id}/release-review/enter", {"operator": "ar-reviewer"}, st10l_e, body10l_e)
        st10l_r, body10l_r = wait_review_state(base_url, legacy_analyst2_id, "report_ready", timeout_s=10)
        api10l_r = api_file(api_dir, "reg_a2_01_review_ready_legacy_analyst2", "GET", f"/api/training/agents/{legacy_analyst2_id}/release-review", None, st10l_r, body10l_r)
        shot10l, probe10l, probe10l_payload = capture_probe(browser, base_url, evidence_root, "reg_a2_01_legacy_analyst2_report_ready", "ac_ar_rr_10", {"tc_probe_agent": "legacy-analyst2-agent"})
        dump_sql(db_path, "SELECT review_id,agent_id,target_version,current_workspace_ref,release_review_state,report_json,report_error,analysis_chain_json FROM agent_release_review WHERE agent_id=? ORDER BY created_at DESC", (legacy_analyst2_id,), db_dir / "reg_a2_01_legacy_analyst2_review.db.json")
        legacy_review = body10l_r.get("review", {}) if isinstance(body10l_r, dict) else {}
        legacy_report = legacy_review.get("report", {}) if isinstance(legacy_review, dict) else {}
        legacy_warnings = list(legacy_report.get("warnings") or []) if isinstance(legacy_report, dict) else []
        legacy_raw_result = legacy_report.get("raw_result") if isinstance(legacy_report, dict) else {}
        legacy_raw_risks_text = json.dumps((legacy_raw_result or {}).get("risk_list") or [], ensure_ascii=False)
        ac["REG-A2-01"] = {
            "pass": bool(
                st10l_e == 200
                and st10l_r == 200
                and probe10l_payload.get("pass")
                and str(legacy_review.get("release_review_state") or "").strip() == "report_ready"
                and not str(legacy_report.get("previous_release_version") or "").strip()
                and str(legacy_report.get("release_recommendation") or "").strip() == "needs_more_validation"
                and bool(legacy_report.get("first_person_summary"))
                and bool(legacy_report.get("full_capability_inventory"))
                and bool(legacy_report.get("knowledge_scope"))
                and bool(legacy_report.get("agent_skills"))
                and bool(legacy_report.get("applicable_scenarios"))
                and any("首发基线评审" in str(item) for item in legacy_warnings)
                and any("README" in str(item) or "release note" in str(item) for item in legacy_warnings)
                and ("../workflow" in legacy_raw_risks_text or "兄弟目录" in legacy_raw_risks_text)
            ),
            "api": [api10l_e, api10l_r],
        }
        ac_ev["REG-A2-01"] = {
            "screenshots": [shot10l],
            "recordings": [],
            "api": [api10l_e, api10l_r],
            "db_or_logs": [(db_dir / "reg_a2_01_legacy_analyst2_review.db.json").as_posix(), probe10l],
            "code": code_refs_common,
        }

        approve_payload = {"decision": "approve_publish", "reviewer": "release-owner", "review_comment": "我确认当前报告可以进入正式发布。", "operator": "release-owner"}
        st11a, body11a = call(base_url, "POST", f"/api/training/agents/{success_id}/release-review/manual", approve_payload)
        api11a = api_file(api_dir, "ac_ar_11_manual_approve_success", "POST", f"/api/training/agents/{success_id}/release-review/manual", approve_payload, st11a, body11a)
        st11r, body11r = wait_review_state(base_url, success_id, "review_approved", timeout_s=10)
        api11r = api_file(api_dir, "ac_ar_11_review_approved", "GET", f"/api/training/agents/{success_id}/release-review", None, st11r, body11r)
        shot11, probe11, probe11_payload = capture_probe(browser, base_url, evidence_root, "ac_ar_11_review_approved", "ac_ar_rr_11", {"tc_probe_agent": "success-agent"})
        st11e, body11e = call(base_url, "POST", f"/api/training/agents/{reject_id}/release-review/enter", {"operator": "ar-reviewer"})
        api11e = api_file(api_dir, "ac_ar_11_enter_reject_agent", "POST", f"/api/training/agents/{reject_id}/release-review/enter", {"operator": "ar-reviewer"}, st11e, body11e)
        reject_payload = {"decision": "reject_continue_training", "reviewer": "release-owner", "review_comment": "我要求继续训练后再发版。", "operator": "release-owner"}
        st11b, body11b = call(base_url, "POST", f"/api/training/agents/{reject_id}/release-review/manual", reject_payload)
        api11b = api_file(api_dir, "ac_ar_11_manual_reject", "POST", f"/api/training/agents/{reject_id}/release-review/manual", reject_payload, st11b, body11b)
        st11c, body11c = wait_review_state(base_url, reject_id, "review_rejected", timeout_s=10)
        api11c = api_file(api_dir, "ac_ar_11_review_rejected", "GET", f"/api/training/agents/{reject_id}/release-review", None, st11c, body11c)
        dump_sql(db_path, "SELECT review_id,agent_id,release_review_state,review_decision,reviewer,review_comment,reviewed_at FROM agent_release_review WHERE agent_id IN (?,?) ORDER BY created_at DESC", (success_id, reject_id), db_dir / "ac_ar_11_manual_review.db.json")
        approved_review = body11r.get("review", {}) if isinstance(body11r, dict) else {}
        rejected_review = body11c.get("review", {}) if isinstance(body11c, dict) else {}
        ac["AC-AR-11"] = {"pass": bool(st11a == 200 and st11r == 200 and probe11_payload.get("pass") and str(approved_review.get("reviewer") or "").strip() == "release-owner" and str(approved_review.get("review_decision") or "").strip() == "approve_publish" and bool(str(approved_review.get("reviewed_at") or "").strip()) and st11e == 200 and st11b == 200 and str(rejected_review.get("release_review_state") or "").strip() == "review_rejected" and not bool(rejected_review.get("can_confirm"))), "api": [api11a, api11r, api11e, api11b, api11c]}
        ac_ev["AC-AR-11"] = {"screenshots": [shot11], "recordings": [], "api": [api11a, api11r, api11e, api11b, api11c], "db_or_logs": [(db_dir / "ac_ar_11_manual_review.db.json").as_posix(), probe11], "code": code_refs_common}

        discard_payload = {"operator": "release-owner", "reason": "当前评审批次作废，重新进入评审。"}
        st16d, body16d = call(base_url, "POST", f"/api/training/agents/{success_id}/release-review/discard", discard_payload)
        api16d = api_file(api_dir, "ac_ar_16_discard_review", "POST", f"/api/training/agents/{success_id}/release-review/discard", discard_payload, st16d, body16d)
        st16r, body16r = wait_review_state(base_url, success_id, "review_discarded", timeout_s=10)
        api16r = api_file(api_dir, "ac_ar_16_review_discarded", "GET", f"/api/training/agents/{success_id}/release-review", None, st16r, body16r)
        shot16, probe16, probe16_payload = capture_probe(browser, base_url, evidence_root, "ac_ar_16_review_discarded", "ac_ar_rr_16", {"tc_probe_agent": "success-agent"})
        st16e, body16e = call(base_url, "POST", f"/api/training/agents/{success_id}/release-review/enter", {"operator": "release-owner"})
        api16e = api_file(api_dir, "ac_ar_16_reenter_review", "POST", f"/api/training/agents/{success_id}/release-review/enter", {"operator": "release-owner"}, st16e, body16e)
        st16rr, body16rr = wait_review_state(base_url, success_id, "report_ready", timeout_s=10)
        api16rr = api_file(api_dir, "ac_ar_16_review_ready_after_reenter", "GET", f"/api/training/agents/{success_id}/release-review", None, st16rr, body16rr)
        st16m, body16m = call(base_url, "POST", f"/api/training/agents/{success_id}/release-review/manual", approve_payload)
        api16m = api_file(api_dir, "ac_ar_16_reapprove_review", "POST", f"/api/training/agents/{success_id}/release-review/manual", approve_payload, st16m, body16m)
        st16a, body16a = wait_review_state(base_url, success_id, "review_approved", timeout_s=10)
        api16a = api_file(api_dir, "ac_ar_16_review_approved_after_reenter", "GET", f"/api/training/agents/{success_id}/release-review", None, st16a, body16a)
        dump_sql(db_path, "SELECT review_id,agent_id,release_review_state,review_decision,reviewer,review_comment,reviewed_at,execution_log_json FROM agent_release_review WHERE agent_id=? ORDER BY created_at DESC", (success_id,), db_dir / "ac_ar_16_review_discard_and_reenter.db.json")
        discarded_review = body16r.get("review", {}) if isinstance(body16r, dict) else {}
        reentered_review = body16rr.get("review", {}) if isinstance(body16rr, dict) else {}
        approved_after_discard = body16a.get("review", {}) if isinstance(body16a, dict) else {}
        discard_logs = discarded_review.get("execution_logs") if isinstance(discarded_review, dict) else []
        discard_phases = {str(item.get("phase") or "").strip() for item in discard_logs if isinstance(item, dict)}
        ac["AC-AR-17"] = {
            "pass": bool(
                st16d == 200
                and st16r == 200
                and probe16_payload.get("pass")
                and str(discarded_review.get("release_review_state") or "").strip() == "review_discarded"
                and bool(discarded_review.get("can_enter"))
                and not bool(discarded_review.get("can_confirm"))
                and "review_discard" in discard_phases
                and st16e == 200
                and st16rr == 200
                and str(reentered_review.get("release_review_state") or "").strip() == "report_ready"
                and st16m == 200
                and st16a == 200
                and str(approved_after_discard.get("release_review_state") or "").strip() == "review_approved"
            ),
            "api": [api16d, api16r, api16e, api16rr, api16m, api16a],
        }
        ac_ev["AC-AR-17"] = {
            "screenshots": [shot16],
            "recordings": [],
            "api": [api16d, api16r, api16e, api16rr, api16m, api16a],
            "db_or_logs": [(db_dir / "ac_ar_16_review_discard_and_reenter.db.json").as_posix(), probe16],
            "code": code_refs_common,
        }

        st12c, body12c = call(base_url, "POST", f"/api/training/agents/{success_id}/release-review/confirm", {"operator": "release-owner"})
        api12c = api_file(api_dir, "ac_ar_12_confirm_publish_success", "POST", f"/api/training/agents/{success_id}/release-review/confirm", {"operator": "release-owner"}, st12c, body12c)
        st12a, body12a = call(base_url, "GET", "/api/training/agents")
        api12a = api_file(api_dir, "ac_ar_12_agents_after_publish", "GET", "/api/training/agents", None, st12a, body12a)
        st12r, body12r = call(base_url, "GET", f"/api/training/agents/{success_id}/releases?page=1&page_size=20")
        api12r = api_file(api_dir, "ac_ar_12_releases_after_publish", "GET", f"/api/training/agents/{success_id}/releases?page=1&page_size=20", None, st12r, body12r)
        shot12, probe12, probe12_payload = capture_probe(browser, base_url, evidence_root, "ac_ar_12_publish_success_and_role_profile", "ac_ar_rr_12", {"tc_probe_agent": "success-agent"})
        dump_sql(db_path, "SELECT agent_id,current_version,latest_release_version,bound_release_version,lifecycle_state,training_gate_state,active_role_profile_release_id,active_role_profile_ref FROM agent_registry WHERE agent_id=?", (success_id,), db_dir / "ac_ar_12_agent_registry.db.json")
        dump_sql(db_path, "SELECT release_id,agent_id,version_label,classification,release_source_ref,public_profile_ref,capability_snapshot_ref FROM agent_release_history WHERE agent_id=? ORDER BY created_at DESC", (success_id,), db_dir / "ac_ar_12_release_history.db.json")
        success_after = find_agent(list(body12a.get("items") or []), "success-agent")
        releases12 = list(body12r.get("releases") or []) if isinstance(body12r, dict) else []
        latest_release12 = releases12[0] if releases12 else {}
        ac["AC-AR-12"] = {
            "pass": bool(
                st12c == 200
                and st12a == 200
                and st12r == 200
                and probe12_payload.get("pass")
                and str(success_after.get("lifecycle_state") or "").strip() == "released"
                and str(probe12_payload.get("role_profile_source") or "").strip() == "latest_release_report"
                and bool(str(success_after.get("active_role_profile_ref") or "").strip())
                and bool(str(latest_release12.get("public_profile_ref") or "").strip())
            ),
            "api": [api12c, api12a, api12r],
        }
        ac_ev["AC-AR-12"] = {"screenshots": [shot12], "recordings": [], "api": [api12c, api12a, api12r], "db_or_logs": [probe12, (db_dir / "ac_ar_12_agent_registry.db.json").as_posix(), (db_dir / "ac_ar_12_release_history.db.json").as_posix()], "code": code_refs_common}

        report_bound_versions12 = [
            str(row.get("version_label") or "").strip()
            for row in releases12
            if str((row.get("release_source_ref") or row.get("capability_snapshot_ref") or "")).strip()
        ]
        latest_report_version12 = report_bound_versions12[0] if len(report_bound_versions12) >= 1 else ""
        previous_report_version12 = report_bound_versions12[1] if len(report_bound_versions12) >= 2 else ""
        shot19_latest = ""
        probe19_latest = ""
        probe19_latest_payload: dict[str, Any] = {}
        shot19_previous = ""
        probe19_previous = ""
        probe19_previous_payload: dict[str, Any] = {}
        if latest_report_version12:
            shot19_latest, probe19_latest, probe19_latest_payload = capture_probe(
                browser,
                base_url,
                evidence_root,
                "ac_ar_19_latest_release_report_dialog",
                "ac_ar_rr_19",
                {"tc_probe_agent": "success-agent", "tc_probe_release_version": latest_report_version12},
            )
        if previous_report_version12:
            shot19_previous, probe19_previous, probe19_previous_payload = capture_probe(
                browser,
                base_url,
                evidence_root,
                "ac_ar_19_previous_release_report_dialog",
                "ac_ar_rr_19",
                {"tc_probe_agent": "success-agent", "tc_probe_release_version": previous_report_version12},
            )
        ac["AC-AR-19"] = {
            "pass": bool(
                st12r == 200
                and len(report_bound_versions12) >= 2
                and probe19_latest_payload.get("pass")
                and probe19_previous_payload.get("pass")
                and latest_report_version12 != previous_report_version12
                and str(probe19_latest_payload.get("release_report_dialog_version") or "").strip() == latest_report_version12
                and str(probe19_previous_payload.get("release_report_dialog_version") or "").strip() == previous_report_version12
                and str(probe19_latest_payload.get("release_report_dialog_text") or "").strip()
                != str(probe19_previous_payload.get("release_report_dialog_text") or "").strip()
            ),
            "api": [api12r],
        }
        ac_ev["AC-AR-19"] = {
            "screenshots": [item for item in (shot19_latest, shot19_previous) if item],
            "recordings": [],
            "api": [api12r],
            "db_or_logs": [item for item in (probe19_latest, probe19_previous, (db_dir / "ac_ar_12_release_history.db.json").as_posix()) if item],
            "code": code_refs_common,
        }

        st20r, body20r = call(base_url, "GET", f"/api/training/agents/{reject_id}/releases?page=1&page_size=20")
        api20r = api_file(api_dir, "ac_ar_20_reject_releases_without_report", "GET", f"/api/training/agents/{reject_id}/releases?page=1&page_size=20", None, st20r, body20r)
        reject_releases20 = list(body20r.get("releases") or []) if isinstance(body20r, dict) else []
        unavailable_release20 = next(
            (
                str(row.get("version_label") or "").strip()
                for row in reject_releases20
                if not str((row.get("release_source_ref") or row.get("capability_snapshot_ref") or "")).strip()
            ),
            "",
        )
        shot20 = ""
        probe20 = ""
        probe20_payload: dict[str, Any] = {}
        if unavailable_release20:
            shot20, probe20, probe20_payload = capture_probe(
                browser,
                base_url,
                evidence_root,
                "ac_ar_20_release_without_report_hint",
                "ac_ar_rr_20",
                {"tc_probe_agent": "reject-agent", "tc_probe_release_version": unavailable_release20},
            )
        dump_sql(
            db_path,
            "SELECT release_id,agent_id,version_label,classification,release_source_ref,public_profile_ref,capability_snapshot_ref FROM agent_release_history WHERE agent_id=? ORDER BY created_at DESC",
            (reject_id,),
            db_dir / "ac_ar_20_reject_release_history.db.json",
        )
        ac["AC-AR-20"] = {
            "pass": bool(
                st20r == 200
                and bool(unavailable_release20)
                and probe20_payload.get("pass")
                and int(probe20_payload.get("release_report_button_count") or 0) == 0
            ),
            "api": [api20r],
        }
        ac_ev["AC-AR-20"] = {
            "screenshots": [item for item in (shot20,) if item],
            "recordings": [],
            "api": [api20r],
            "db_or_logs": [item for item in (probe20, (db_dir / "ac_ar_20_reject_release_history.db.json").as_posix()) if item],
            "code": code_refs_common,
        }

        st12g_e, body12g_e = call(base_url, "POST", f"/api/training/agents/{no_git_id}/release-review/enter", {"operator": "ar-reviewer"})
        api12g_e = api_file(api_dir, "reg_git_01_enter_no_git_agent", "POST", f"/api/training/agents/{no_git_id}/release-review/enter", {"operator": "ar-reviewer"}, st12g_e, body12g_e)
        st12g_m, body12g_m = call(base_url, "POST", f"/api/training/agents/{no_git_id}/release-review/manual", approve_payload)
        api12g_m = api_file(api_dir, "reg_git_01_manual_approve_no_git_agent", "POST", f"/api/training/agents/{no_git_id}/release-review/manual", approve_payload, st12g_m, body12g_m)
        st12g_c, body12g_c = call(base_url, "POST", f"/api/training/agents/{no_git_id}/release-review/confirm", {"operator": "release-owner"})
        api12g_c = api_file(api_dir, "reg_git_01_confirm_no_git_agent", "POST", f"/api/training/agents/{no_git_id}/release-review/confirm", {"operator": "release-owner"}, st12g_c, body12g_c)
        st12g_a, body12g_a = call(base_url, "GET", "/api/training/agents")
        api12g_a = api_file(api_dir, "reg_git_01_agents_after_publish", "GET", "/api/training/agents", None, st12g_a, body12g_a)
        st12g_r, body12g_r = call(base_url, "GET", f"/api/training/agents/{no_git_id}/releases?page=1&page_size=20")
        api12g_r = api_file(api_dir, "reg_git_01_releases_after_publish", "GET", f"/api/training/agents/{no_git_id}/releases?page=1&page_size=20", None, st12g_r, body12g_r)
        shot12g, probe12g, probe12g_payload = capture_probe(browser, base_url, evidence_root, "reg_git_01_no_git_publish_success", "ac_ar_rr_12", {"tc_probe_agent": "no-git-agent"})
        dump_sql(db_path, "SELECT agent_id,current_version,latest_release_version,bound_release_version,lifecycle_state,training_gate_state,git_available,active_role_profile_release_id,active_role_profile_ref FROM agent_registry WHERE agent_id=?", (no_git_id,), db_dir / "reg_git_01_no_git_agent_registry.db.json")
        dump_sql(db_path, "SELECT review_id,agent_id,release_review_state,publish_status,publish_error,execution_log_json FROM agent_release_review WHERE agent_id=? ORDER BY created_at DESC", (no_git_id,), db_dir / "reg_git_01_no_git_review.db.json")
        no_git_after = find_agent(list(body12g_a.get("items") or []), "no-git-agent")
        no_git_releases = list(body12g_r.get("releases") or []) if isinstance(body12g_r, dict) else []
        no_git_latest_release = no_git_releases[0] if no_git_releases else {}
        no_git_review = body12g_c.get("review", {}) if isinstance(body12g_c, dict) else {}
        no_git_logs = no_git_review.get("execution_logs") if isinstance(no_git_review, dict) else []
        no_git_messages = [str(item.get("message") or "").strip() for item in no_git_logs if isinstance(item, dict)]
        ac["REG-GIT-01"] = {
            "pass": bool(
                st12g_e == 200
                and st12g_m == 200
                and st12g_c == 200
                and st12g_a == 200
                and st12g_r == 200
                and probe12g_payload.get("pass")
                and str((body12g_c.get("review") or {}).get("publish_status") or "").strip() == "success"
                and str(no_git_after.get("lifecycle_state") or "").strip() == "released"
                and bool(str(no_git_after.get("active_role_profile_ref") or "").strip())
                and bool(str(no_git_latest_release.get("public_profile_ref") or "").strip())
                and any("自动执行 git init" in message for message in no_git_messages)
            ),
            "api": [api12g_e, api12g_m, api12g_c, api12g_a, api12g_r],
        }
        ac_ev["REG-GIT-01"] = {
            "screenshots": [shot12g],
            "recordings": [],
            "api": [api12g_e, api12g_m, api12g_c, api12g_a, api12g_r],
            "db_or_logs": [
                probe12g,
                (db_dir / "reg_git_01_no_git_agent_registry.db.json").as_posix(),
                (db_dir / "reg_git_01_no_git_review.db.json").as_posix(),
            ],
            "code": code_refs_common,
        }

        st14e, body14e = call(base_url, "POST", f"/api/training/agents/{publish_fail_id}/release-review/enter", {"operator": "ar-reviewer"})
        api14e = api_file(api_dir, "ac_ar_14_enter_publish_fail", "POST", f"/api/training/agents/{publish_fail_id}/release-review/enter", {"operator": "ar-reviewer"}, st14e, body14e)
        st14m, body14m = call(base_url, "POST", f"/api/training/agents/{publish_fail_id}/release-review/manual", approve_payload)
        api14m = api_file(api_dir, "ac_ar_14_manual_approve_publish_fail", "POST", f"/api/training/agents/{publish_fail_id}/release-review/manual", approve_payload, st14m, body14m)
        shot14_pre, probe14_pre, _ = capture_probe(browser, base_url, evidence_root, "ac_ar_14_before_confirm_publish_fail", "ac_ar_rr_11", {"tc_probe_agent": "publish-fail-agent"})
        st14c, body14c = call(base_url, "POST", f"/api/training/agents/{publish_fail_id}/release-review/confirm", {"operator": "release-owner"})
        api14c = api_file(api_dir, "ac_ar_14_confirm_publish_fail", "POST", f"/api/training/agents/{publish_fail_id}/release-review/confirm", {"operator": "release-owner"}, st14c, body14c)
        st14r, body14r = wait_review_state(base_url, publish_fail_id, "publish_failed", timeout_s=15)
        api14r = api_file(api_dir, "ac_ar_14_review_publish_failed", "GET", f"/api/training/agents/{publish_fail_id}/release-review", None, st14r, body14r)
        shot14, probe14, probe14_payload = capture_probe(browser, base_url, evidence_root, "ac_ar_14_publish_failed_with_fallback", "ac_ar_rr_14", {"tc_probe_agent": "publish-fail-agent"})
        dump_sql(db_path, "SELECT review_id,agent_id,release_review_state,publish_status,publish_error,execution_log_json,fallback_json FROM agent_release_review WHERE agent_id=? ORDER BY created_at DESC", (publish_fail_id,), db_dir / "ac_ar_14_publish_failed_review.db.json")
        fail_review = body14r.get("review", {}) if isinstance(body14r, dict) else {}
        fail_logs = fail_review.get("execution_logs") if isinstance(fail_review, dict) else []
        fail_phases = {str(item.get("phase") or "").strip() for item in fail_logs if isinstance(item, dict)}
        fallback_payload = fail_review.get("fallback") if isinstance(fail_review, dict) else {}
        ac["AC-AR-14"] = {"pass": bool(st14e == 200 and st14m == 200 and st14c == 200 and st14r == 200 and probe14_payload.get("pass") and str(fail_review.get("publish_status") or "").strip() == "failed" and str(fail_review.get("release_review_state") or "").strip() == "publish_failed" and bool(fail_review.get("can_confirm")) and "fallback_trigger" in fail_phases and "fallback_result" in fail_phases and bool(str((fallback_payload or {}).get("failure_reason") or "").strip()) and bool(str((fallback_payload or {}).get("repair_summary") or "").strip()) and isinstance((fallback_payload or {}).get("repair_actions"), list) and isinstance((fallback_payload or {}).get("retry_result"), dict)), "api": [api14e, api14m, api14c, api14r]}
        ac_ev["AC-AR-14"] = {"screenshots": [shot14], "recordings": [], "api": [api14e, api14m, api14c, api14r], "db_or_logs": [(db_dir / "ac_ar_14_publish_failed_review.db.json").as_posix(), probe14_pre, probe14], "code": code_refs_common}

        st13r, body13r = call(base_url, "GET", f"/api/training/agents/{publish_fail_id}/release-review")
        api13r = api_file(api_dir, "ac_ar_13_review_logs", "GET", f"/api/training/agents/{publish_fail_id}/release-review", None, st13r, body13r)
        shot13, probe13, probe13_payload = capture_probe(browser, base_url, evidence_root, "ac_ar_13_publish_logs", "ac_ar_rr_13", {"tc_probe_agent": "success-agent"})
        success_logs = (body12c.get("review") or {}).get("execution_logs") if isinstance(body12c, dict) else []
        success_phases = {str(item.get("phase") or "").strip() for item in success_logs if isinstance(item, dict)}
        failure_logs = (body13r.get("review") or {}).get("execution_logs") if isinstance(body13r, dict) else []
        failure_phases = {str(item.get("phase") or "").strip() for item in failure_logs if isinstance(item, dict)}
        ac["AC-AR-13"] = {"pass": bool(st13r == 200 and probe13_payload.get("pass") and {"prepare", "git_execute", "release_note", "verify"} <= success_phases and {"fallback_trigger", "fallback_result"} <= failure_phases), "api": [api13r, api12c]}
        ac_ev["AC-AR-13"] = {"screenshots": [shot13], "recordings": [], "api": [api13r, api12c], "db_or_logs": [probe13, (db_dir / "ac_ar_14_publish_failed_review.db.json").as_posix()], "code": code_refs_common}

        retry_hook = workspace_root / "publish-fail-agent" / ".git" / "hooks" / "pre-commit"
        if retry_hook.exists():
            retry_hook.unlink()
        retry_workspace = workspace_root / "publish-fail-agent"
        run_cmd(["git", "config", "user.email", "publish-fail-agent@example.com"], retry_workspace)
        run_cmd(["git", "config", "user.name", "publish-fail-agent"], retry_workspace)
        st14x_c, body14x_c = call(base_url, "POST", f"/api/training/agents/{publish_fail_id}/release-review/confirm", {"operator": "release-owner"})
        api14x_c = api_file(api_dir, "reg_retry_01_confirm_publish_retry", "POST", f"/api/training/agents/{publish_fail_id}/release-review/confirm", {"operator": "release-owner"}, st14x_c, body14x_c)
        st14x_a, body14x_a = call(base_url, "GET", "/api/training/agents")
        api14x_a = api_file(api_dir, "reg_retry_01_agents_after_retry_publish", "GET", "/api/training/agents", None, st14x_a, body14x_a)
        st14x_r, body14x_r = call(base_url, "GET", f"/api/training/agents/{publish_fail_id}/releases?page=1&page_size=20")
        api14x_r = api_file(api_dir, "reg_retry_01_releases_after_retry_publish", "GET", f"/api/training/agents/{publish_fail_id}/releases?page=1&page_size=20", None, st14x_r, body14x_r)
        shot14x, probe14x, probe14x_payload = capture_probe(browser, base_url, evidence_root, "reg_retry_01_publish_retry_success", "ac_ar_rr_12", {"tc_probe_agent": "publish-fail-agent"})
        dump_sql(db_path, "SELECT review_id,agent_id,release_review_state,publish_status,publish_error,execution_log_json,fallback_json FROM agent_release_review WHERE agent_id=? ORDER BY created_at DESC", (publish_fail_id,), db_dir / "reg_retry_01_publish_retry_review.db.json")
        retry_review = body14x_c.get("review", {}) if isinstance(body14x_c, dict) else {}
        retry_logs = retry_review.get("execution_logs") if isinstance(retry_review, dict) else []
        retry_messages = [str(item.get("message") or "").strip() for item in retry_logs if isinstance(item, dict)]
        retry_after = find_agent(list(body14x_a.get("items") or []), "publish-fail-agent")
        retry_releases = list(body14x_r.get("releases") or []) if isinstance(body14x_r, dict) else []
        retry_latest_release = retry_releases[0] if retry_releases else {}
        ac["REG-RETRY-01"] = {
            "pass": bool(
                st14x_c == 200
                and st14x_a == 200
                and st14x_r == 200
                and probe14x_payload.get("pass")
                and str(retry_review.get("publish_status") or "").strip() == "success"
                and str(retry_review.get("release_review_state") or "").strip() == "idle"
                and str(retry_review.get("review_id") or "").strip() == str(fail_review.get("review_id") or "").strip()
                and any("开始基于当前评审记录手动重试发布" in message for message in retry_messages)
                and str(retry_after.get("lifecycle_state") or "").strip() == "released"
                and bool(str(retry_latest_release.get("public_profile_ref") or "").strip())
            ),
            "api": [api14x_c, api14x_a, api14x_r],
        }
        ac_ev["REG-RETRY-01"] = {
            "screenshots": [shot14x],
            "recordings": [],
            "api": [api14x_c, api14x_a, api14x_r],
            "db_or_logs": [
                probe14x,
                (db_dir / "reg_retry_01_publish_retry_review.db.json").as_posix(),
            ],
            "code": code_refs_common,
        }

        st15e, body15e = call(base_url, "POST", f"/api/training/agents/{report_fail_id}/release-review/enter", {"operator": "ar-reviewer"})
        api15e = api_file(api_dir, "ac_ar_15_enter_report_fail", "POST", f"/api/training/agents/{report_fail_id}/release-review/enter", {"operator": "ar-reviewer"}, st15e, body15e)
        st15r, body15r = wait_review_state(base_url, report_fail_id, "report_failed", timeout_s=10)
        api15r = api_file(api_dir, "ac_ar_15_review_report_failed", "GET", f"/api/training/agents/{report_fail_id}/release-review", None, st15r, body15r)
        shot15, probe15, probe15_payload = capture_probe(browser, base_url, evidence_root, "ac_ar_15_report_failed_blocked", "ac_ar_rr_15", {"tc_probe_agent": "report-fail-agent"})
        dump_sql(db_path, "SELECT review_id,agent_id,release_review_state,report_error,report_json,analysis_chain_json FROM agent_release_review WHERE agent_id=? ORDER BY created_at DESC", (report_fail_id,), db_dir / "ac_ar_15_report_failed_review.db.json")
        report_fail_review = body15r.get("review", {}) if isinstance(body15r, dict) else {}
        report_fail_report = report_fail_review.get("report", {}) if isinstance(report_fail_review, dict) else {}
        ac["AC-AR-15"] = {"pass": bool(st15e == 200 and st15r == 200 and probe15_payload.get("pass") and str(report_fail_review.get("release_review_state") or "").strip() == "report_failed" and "重新进入发布评审" in str(report_fail_review.get("report_error") or "") and str(report_fail_review.get("report_error_code") or "").strip() == "release_review_report_failed" and all(str(report_fail_report.get(field) or "").strip() for field in ("target_version", "current_workspace_ref", "change_summary", "release_recommendation", "next_action_suggestion")) and not bool(report_fail_review.get("can_confirm"))), "api": [api15e, api15r]}
        ac_ev["AC-AR-15"] = {"screenshots": [shot15], "recordings": [], "api": [api15e, api15r], "db_or_logs": [(db_dir / "ac_ar_15_report_failed_review.db.json").as_posix(), probe15], "code": code_refs_common}

        gif10 = rec_dir / "ac_ar_10_release_review.gif"
        gif12 = rec_dir / "ac_ar_12_confirm_publish.gif"
        gif14 = rec_dir / "ac_ar_14_publish_failed_fallback.gif"
        make_gif(gif10, [Path(shot09), Path(shot10)])
        make_gif(gif12, [Path(shot10), Path(shot11), Path(shot12)])
        make_gif(gif14, [Path(shot14_pre), Path(shot14)])
        ac_ev["AC-AR-10"]["recordings"] = [gif10.as_posix()]
        ac_ev["AC-AR-12"]["recordings"] = [gif12.as_posix()]
        ac_ev["AC-AR-14"]["recordings"] = [gif14.as_posix()]

        manifest = evidence_root / "ac_ar_09_15_evidence_manifest.json"
        write_json(manifest, ac_ev)
        summary_md = evidence_root / "ac_ar_09_15_summary.md"
        summary_lines = [
            f"# AC-AR-09~15 + AC-AR-17 + AC-AR-19/20 + REG-A2-01 Acceptance Summary ({ts})",
            "",
            f"- runtime_root: {runtime_root.as_posix()}",
            f"- workspace_root: {workspace_root.as_posix()}",
            f"- db_path: {db_path.as_posix()}",
            f"- server_stdout: {server_stdout.as_posix()}",
            f"- server_stderr: {server_stderr.as_posix()}",
            f"- screenshots_dir: {shots_dir.as_posix()}",
            f"- recordings_dir: {rec_dir.as_posix()}",
            f"- api_dir: {api_dir.as_posix()}",
            f"- db_dir: {db_dir.as_posix()}",
            f"- evidence_manifest: {manifest.as_posix()}",
            "",
            "| AC | pass | evidence |",
            "|---|---|---|",
        ]
        for ac_id in [*(f"AC-AR-{i:02d}" for i in range(9, 16)), "AC-AR-17", "AC-AR-19", "AC-AR-20", "REG-A2-01", "REG-GIT-01", "REG-RETRY-01"]:
            row = ac.get(ac_id, {"pass": False})
            evidence = ac_ev.get(ac_id, {})
            refs: list[str] = []
            if evidence.get("screenshots"):
                refs.append("screenshot=" + "<br>".join(evidence["screenshots"]))
            if evidence.get("recordings"):
                refs.append("recording=" + "<br>".join(evidence["recordings"]))
            if evidence.get("api"):
                refs.append("api=" + "<br>".join(evidence["api"]))
            if evidence.get("db_or_logs"):
                refs.append("db/log=" + "<br>".join([item for item in evidence["db_or_logs"] if item]))
            if evidence.get("code"):
                refs.append("code=" + "<br>".join(evidence["code"]))
            summary_lines.append(f"| {ac_id} | {'pass' if row.get('pass') else 'fail'} | {'<br><br>'.join(refs)} |")
        summary_md.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
        write_json(evidence_root / "ac_ar_09_15_summary.json", ac)
        print(summary_md.as_posix())
        required_ids = [*(f"AC-AR-{i:02d}" for i in range(9, 16)), "AC-AR-17", "AC-AR-19", "AC-AR-20", "REG-A2-01", "REG-GIT-01", "REG-RETRY-01"]
        return 0 if all(bool(ac.get(ac_id, {}).get("pass")) for ac_id in required_ids) else 1
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
