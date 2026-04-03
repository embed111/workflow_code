#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


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


def release_note_text(
    version: str,
    *,
    capability_summary: str,
    knowledge_scope: str,
    skills: list[str],
    applicable_scenarios: str,
    version_notes: str,
) -> str:
    return "\n".join(
        [
            f"发布版本: {version}",
            f"角色能力摘要: {capability_summary}",
            f"角色知识范围: {knowledge_scope}",
            "技能: " + ", ".join(skills),
            f"适用场景: {applicable_scenarios}",
            f"版本说明: {version_notes}",
            "",
        ]
    )


def write_agent_workspace(
    root: Path,
    agent_name: str,
    *,
    persist_git_identity: bool,
    pre_release_note: str,
    fail_commit_hook: bool = False,
    create_release_tag: bool = True,
    initialize_git_repo: bool = True,
) -> Path:
    workspace = root / agent_name
    workspace.mkdir(parents=True, exist_ok=True)
    agents_md = "\n".join(
        [
            "# AGENT",
            "",
            "角色能力摘要: 我负责角色发布评审、发布执行校验与角色画像整理。",
            "角色知识范围: 我覆盖发布治理、Git 发布校验、角色画像快照绑定与验收证据组织。",
            "技能: release-governance, evidence-packaging",
            "适用场景: 角色发布评审；确认发布；发布失败兜底；角色详情展示来源绑定",
            "版本说明: 我当前维护发布评审流与角色画像展示口径。",
            "",
        ]
    )
    (workspace / "AGENTS.md").write_text(agents_md + "\n", encoding="utf-8")
    skill_dir = workspace / ".codex" / "skills" / "release-governance"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                "name: release-governance",
                "description: Handle release review, publish evidence, and profile binding.",
                "---",
                "",
                "# Release Governance",
                "",
                "Keep release review evidence structured and traceable.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    if not initialize_git_repo:
        (workspace / "WIP.md").write_text(pre_release_note + "\n", encoding="utf-8")
        return workspace

    run_cmd(["git", "init"], workspace)
    identity_env = os.environ.copy()
    if persist_git_identity:
        run_cmd(["git", "config", "user.email", f"{agent_name}@example.com"], workspace)
        run_cmd(["git", "config", "user.name", agent_name], workspace)
        cmd_env = None
    else:
        identity_env["GIT_AUTHOR_NAME"] = agent_name
        identity_env["GIT_AUTHOR_EMAIL"] = f"{agent_name}@example.com"
        identity_env["GIT_COMMITTER_NAME"] = agent_name
        identity_env["GIT_COMMITTER_EMAIL"] = f"{agent_name}@example.com"
        cmd_env = identity_env

    run_cmd(["git", "add", "AGENTS.md", ".codex/skills/release-governance/SKILL.md"], workspace, env=cmd_env)
    run_cmd(["git", "commit", "-m", "init"], workspace, env=cmd_env)
    if create_release_tag:
        note_v100 = release_note_text(
            "v1.0.0",
            capability_summary="我负责角色发布评审与正式版本维护。",
            knowledge_scope="我覆盖基础发布治理与角色能力说明。",
            skills=["release-governance", "evidence-packaging"],
            applicable_scenarios="正式发布基线维护；角色详情初始化",
            version_notes="首个正式发布基线。",
        )
        note_path = workspace / ".release-note-v1.0.0.md"
        note_path.write_text(note_v100, encoding="utf-8")
        run_cmd(["git", "tag", "-a", "v1.0.0", "-F", note_path.as_posix()], workspace, env=cmd_env)
    if fail_commit_hook:
        hook_path = workspace / ".git" / "hooks" / "pre-commit"
        hook_path.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    (workspace / "WIP.md").write_text(pre_release_note + "\n", encoding="utf-8")
    return workspace


def fixture_agents(workspace_root: Path) -> dict[str, Path]:
    (workspace_root / "workflow").mkdir(parents=True, exist_ok=True)
    (workspace_root / "workflow" / "README.md").write_text("fixture\n", encoding="utf-8")
    return {
        "success-agent": write_agent_workspace(workspace_root, "success-agent", persist_git_identity=True, pre_release_note="success agent pre-release change"),
        "reject-agent": write_agent_workspace(workspace_root, "reject-agent", persist_git_identity=True, pre_release_note="reject agent pre-release change"),
        "publish-fail-agent": write_agent_workspace(
            workspace_root,
            "publish-fail-agent",
            persist_git_identity=False,
            pre_release_note="publish fail agent pre-release change",
            fail_commit_hook=True,
        ),
        "report-fail-agent": write_agent_workspace(workspace_root, "report-fail-agent", persist_git_identity=True, pre_release_note="report fail agent pre-release change"),
        "no-git-agent": write_agent_workspace(
            workspace_root,
            "no-git-agent",
            persist_git_identity=True,
            pre_release_note="no git agent pre-release change",
            create_release_tag=False,
            initialize_git_repo=False,
        ),
        "legacy-analyst2-agent": write_agent_workspace(
            workspace_root,
            "legacy-analyst2-agent",
            persist_git_identity=True,
            pre_release_note="legacy analyst2 first release baseline change",
            create_release_tag=False,
        ),
    }


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


def write_codex_stub(bin_dir: Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    script_path = bin_dir / "codex_stub.py"
    cmd_path = bin_dir / "codex.cmd"
    script_path.write_text(
        "\n".join(
            [
                "import json",
                "import re",
                "import sys",
                "import time",
                "prompt = sys.stdin.read()",
                "is_fallback = '角色发布失败兜底助手' in prompt",
                "def extract(label, default=''):",
                "    matched = re.search(r'^\\s*[-]?\\s*' + re.escape(label) + r'\\s*:\\s*(.+)$', prompt, flags=re.M)",
                "    if matched:",
                "        return matched.group(1).strip()",
                "    matched = re.search(r'\\\"' + re.escape(label) + r'\\\"\\s*:\\s*\\\"([^\\\"]+)\\\"', prompt)",
                "    if matched:",
                "        return matched.group(1).strip()",
                "    return default",
                "agent_name = extract('agent_name') or extract('agent_id')",
                "target_version = extract('target_version', 'v1.0.1')",
                "current_workspace_ref = extract('current_workspace_ref', 'workspace-ref')",
                "def emit(payload):",
                "    print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(payload, ensure_ascii=False)}}, ensure_ascii=False))",
                "if is_fallback:",
                "    emit({'failure_reason': '我识别到当前工作区缺少 Git 用户身份配置，导致提交或打标签失败。', 'repair_summary': '我已定位到失败主因是 Git 身份或工作区提交钩子拦截，需要先修复后再重试。', 'repair_actions': ['我已检查当前发布失败日志并锁定 Git 身份/提交钩子问题。', '我建议先移除阻断提交的工作区钩子或补齐本地 Git 身份，然后再执行自动重试。'], 'retry_target_version': target_version, 'retry_release_notes': '', 'next_action_suggestion': '我建议先补齐 Git 用户身份或修复工作区提交钩子后，再直接重试发布。', 'warnings': []})",
                "    raise SystemExit(0)",
                "if agent_name == 'report-fail-agent':",
                "    raise SystemExit(2)",
                "if agent_name == 'legacy-analyst2-agent':",
                "    emit({'target_version': target_version, 'current_workspace_ref': current_workspace_ref, 'change_summary': '我本次正在整理首发基线所需的角色发布评审报告。', 'capability_delta': ['我本次补充了首发基线的角色能力梳理。'], 'risk_list': ['README.md / CHANGELOG / release note 暂未补齐。', '../workflow 存在兄弟目录脏文件。'], 'validation_evidence': ['我当前已确认工作区存在预发布改动，并已产出结构化 trace。'], 'release_recommendation': 'reject_continue_training', 'next_action_suggestion': '我建议先补齐发布说明并继续验证。', 'warnings': []})",
                "    raise SystemExit(0)",
                "if agent_name == 'success-agent':",
                "    time.sleep(2.5)",
                "summary_name = agent_name or 'release-agent'",
                "emit({'target_version': target_version, 'current_workspace_ref': current_workspace_ref, 'previous_release_version': 'v1.0.0', 'first_person_summary': f'我是 {summary_name}，我当前负责角色发布评审、功能差异梳理与正式版本画像绑定。', 'full_capability_inventory': ['我当前可以输出第一人称全量能力介绍并生成公开展示快照。', '我当前可以梳理相对上一正式版本的功能差异、风险与验证证据。', '我当前可以在正式发布成功后把报告绑定为角色详情页的展示来源。'], 'knowledge_scope': '我当前覆盖角色发布治理、Git 发布校验、角色画像绑定与验收证据组织。', 'agent_skills': ['release-governance', 'evidence-packaging'], 'applicable_scenarios': ['角色发布评审', '确认发布前差异审阅', '正式发布后的角色详情展示'], 'change_summary': '我本次相对上一正式版本补充了第一人称全量能力介绍输出，以及功能差异、风险与证据的结构化报告。', 'capability_delta': ['我本次新增了正式发布后可直接复用的第一人称全量能力介绍。', '我本次补充了相对上一正式版本的功能差异、风险和证据说明。'], 'risk_list': ['我当前识别到的风险是：如果 Git 用户身份未配置，确认发布会失败。'], 'validation_evidence': ['我当前已确认的验证证据是：结构化报告、stdout、stderr 和快照文件都已落盘。'], 'release_recommendation': 'approve', 'next_action_suggestion': '我建议进入人工审核，并在审核通过后执行确认发布。', 'warnings': []})",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    cmd_path.write_text("@echo off\r\n" + f"\"{sys.executable}\" \"{script_path.as_posix()}\" %*\r\n", encoding="utf-8")


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
