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
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from policy_cache_seed import upsert_policy_cache


def call(base_url: str, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url=base_url + path, data=data, method=method, headers=headers)
    try:
        with urlopen(req, timeout=600) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, (json.loads(body) if body else {})
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            payload_obj = json.loads(body) if body else {}
        except Exception:
            payload_obj = {"raw": body}
        return exc.code, payload_obj
    except Exception as exc:
        if "timed out" in str(exc).lower():
            raise RuntimeError(f"request timeout: {method} {path}") from exc
        raise


def wait_health(base_url: str, timeout_s: int = 90) -> None:
    end_at = time.time() + max(10, timeout_s)
    while time.time() < end_at:
        status, payload = call(base_url, "GET", "/healthz")
        if status == 200 and payload.get("ok"):
            return
        time.sleep(0.5)
    raise RuntimeError("healthz timeout")


def wait_task_done(base_url: str, task_id: str, timeout_s: int = 240) -> dict:
    end_at = time.time() + max(10, timeout_s)
    while time.time() < end_at:
        status, payload = call(base_url, "GET", f"/api/tasks/{task_id}")
        if status == 200 and payload.get("ok"):
            task_status = str(payload.get("status") or "").lower()
            if task_status in {"success", "failed", "interrupted"}:
                return payload
        time.sleep(0.6)
    raise RuntimeError(f"task timeout: {task_id}")


def wait_workflow_events(base_url: str, workflow_id: str, timeout_s: int = 30) -> list[dict]:
    end_at = time.time() + max(5, timeout_s)
    while time.time() < end_at:
        status, payload = call(base_url, "GET", f"/api/workflows/training/{workflow_id}/events?since_id=0")
        if status == 200 and payload.get("ok"):
            events = list(payload.get("events") or [])
            if events:
                return events
        time.sleep(0.6)
    return []


def wait_workflow_for_session(base_url: str, session_id: str, timeout_s: int = 40) -> dict:
    end_at = time.time() + max(5, timeout_s)
    while time.time() < end_at:
        status, payload = call(base_url, "GET", "/api/workflows/training/queue?include_test_data=1")
        if status == 200 and payload.get("ok"):
            items = list(payload.get("items") or [])
            row = next((item for item in items if str(item.get("session_id") or "") == session_id), None)
            if row:
                return row
        time.sleep(0.8)
    return {}


def find_edge_executable() -> Path:
    candidates = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    for path in candidates:
        if path.exists() and path.is_file():
            return path
    raise RuntimeError("Microsoft Edge executable not found")


def edge_dump_dom(edge_path: Path, *, url: str, width: int = 1366, height: int = 768, budget_ms: int = 10000) -> str:
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
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"edge dump-dom failed: rc={proc.returncode}, stderr={proc.stderr.strip()}")
    return proc.stdout


def edge_screenshot(
    edge_path: Path,
    *,
    url: str,
    screenshot_path: Path,
    width: int = 1366,
    height: int = 768,
    budget_ms: int = 10000,
) -> None:
    cmd = [
        str(edge_path),
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        f"--window-size={width},{height}",
        f"--virtual-time-budget={max(1000, int(budget_ms))}",
        f"--screenshot={screenshot_path.as_posix()}",
        url,
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"edge screenshot failed: rc={proc.returncode}, stderr={proc.stderr.strip()}")


def parse_policy_probe_output(dom_text: str) -> dict:
    matched = re.search(
        r"<pre[^>]*id=['\"]policyProbeOutput['\"][^>]*>(.*?)</pre>",
        str(dom_text or ""),
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not matched:
        raise RuntimeError("policyProbeOutput_not_found")
    raw = html.unescape(matched.group(1) or "").strip()
    if not raw:
        raise RuntimeError("policyProbeOutput_empty")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError("policyProbeOutput_not_dict")
    return payload


def agent_by_name(agents: list[dict], name: str) -> dict:
    for item in agents:
        if str(item.get("agent_name") or "") == name:
            return item
    raise RuntimeError(f"agent not found: {name}")


def write_agents_fixture(root: Path) -> Path:
    workspace_root = root / "workspace-root"
    if workspace_root.exists():
        shutil.rmtree(workspace_root, ignore_errors=True)
    (workspace_root / "workflow").mkdir(parents=True, exist_ok=True)
    (workspace_root / "workflow" / "README.md").write_text("fixture\n", encoding="utf-8")
    (workspace_root / "ready-agent").mkdir(parents=True, exist_ok=True)
    (workspace_root / "confirm-agent").mkdir(parents=True, exist_ok=True)
    (workspace_root / "failed-agent").mkdir(parents=True, exist_ok=True)

    (workspace_root / "ready-agent" / "AGENTS.md").write_text(
        "\n".join(
            [
                "# ready-agent",
                "## 角色",
                "你是训练闭环系统的分析师，专注需求拆解、风险识别和执行建议。",
                "## 目标",
                "在职责边界内提供可执行步骤，确保每轮输出都可验证和可追溯。",
                "## 职责边界",
                "- 仅做分析、计划和建议，不直接执行高风险变更。",
                "- 对信息不足场景先提问澄清，再给方案。",
                "- 所有结论附带验证动作与风险提示。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    (workspace_root / "confirm-agent" / "AGENTS.md").write_text(
        "\n".join(
            [
                "# confirm-agent",
                "## 角色",
                "你是分析师，负责梳理需求与约束。",
                "## 职责边界",
                "- 在职责边界内工作。",
                "- 输出可执行建议。",
                "- 遇到歧义先澄清。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    (workspace_root / "failed-agent" / "AGENTS.md").write_text(
        "\n".join(
            [
                "# failed-agent",
                "just text",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return workspace_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AC-31 ~ AC-35 acceptance checks.")
    parser.add_argument("--root", default=".", help="workspace root")
    parser.add_argument("--host", default="127.0.0.1", help="bind host")
    parser.add_argument("--port", type=int, default=8102, help="bind port")
    parser.add_argument(
        "--runtime-root",
        default="",
        help="isolated runtime root for acceptance data (default: <root>/.test/runtime/ac31-ac35)",
    )
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    runtime_root = (
        Path(args.runtime_root).resolve()
        if str(args.runtime_root or "").strip()
        else (repo_root / ".test" / "runtime" / "ac31-ac35").resolve()
    )
    if runtime_root.exists():
        shutil.rmtree(runtime_root, ignore_errors=True)
    runtime_root.mkdir(parents=True, exist_ok=True)
    workspace_root = write_agents_fixture(runtime_root)
    upsert_policy_cache(
        runtime_root=runtime_root,
        workspace_root=workspace_root,
        specs=[
            {
                "agent_name": "ready-agent",
                "role_profile": "你是训练闭环系统分析师。",
                "session_goal": "在职责边界内提供可执行步骤。",
                "duty_constraints": [
                    "仅做分析、计划和建议。",
                    "信息不足先澄清。",
                    "结论附验证动作。",
                ],
                "clarity_score": 90,
                "clarity_gate": "auto",
                "parse_status": "ok",
                "policy_extract_ok": True,
            },
            {
                "agent_name": "confirm-agent",
                "role_profile": "你是分析师，负责梳理需求与约束。",
                "session_goal": "输出可执行建议。",
                "duty_constraints": [
                    "在职责边界内工作。",
                    "输出可执行建议。",
                    "遇到歧义先澄清。",
                ],
                "clarity_score": 70,
                "clarity_gate": "confirm",
                "parse_status": "ok",
                "policy_extract_ok": True,
            },
            {
                "agent_name": "failed-agent",
                "role_profile": "",
                "session_goal": "",
                "duty_constraints": [],
                "clarity_score": 0,
                "clarity_gate": "block",
                "parse_status": "failed",
                "policy_extract_ok": False,
                "policy_error": "agent_policy_extract_failed",
            },
        ],
    )

    edge_path = find_edge_executable()
    out_dir = (repo_root / ".test" / "runs").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    shots_dir = out_dir / f"ac31-ac35-shots-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    shots_dir.mkdir(parents=True, exist_ok=True)

    entry_script = (repo_root / "scripts" / "workflow_entry_cli.py").resolve()
    web_script = (repo_root / "scripts" / "workflow_web_server.py").resolve()
    base = f"http://{args.host}:{args.port}"
    proc = subprocess.Popen(
        [
            sys.executable,
            str(web_script),
            "--root",
            runtime_root.as_posix(),
            "--entry-script",
            entry_script.as_posix(),
            "--agent-search-root",
            workspace_root.as_posix(),
            "--allow-manual-policy-input",
            "0",
            "--host",
            args.host,
            "--port",
            str(args.port),
        ],
        cwd=str(repo_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    results: list[tuple[str, bool, dict]] = []
    errors: list[str] = []
    screenshots: dict[str, str] = {}
    cache_demo: dict[str, dict] = {}

    try:
        wait_health(base)

        # Pull agents twice to establish cache recompute -> hit baseline.
        a1_status, a1_payload = call(base, "GET", "/api/agents")
        a2_status, a2_payload = call(base, "GET", "/api/agents")
        if a1_status != 200 or not a1_payload.get("ok"):
            raise RuntimeError(f"/api/agents failed: {a1_status} {a1_payload}")
        agents1 = list(a1_payload.get("agents") or [])
        agents2 = list(a2_payload.get("agents") or []) if a2_status == 200 else []
        ready_before = agent_by_name(agents1, "ready-agent")
        ready_hit = agent_by_name(agents2, "ready-agent") if agents2 else {}

        ac31_cache_fields_ok = bool(
            "policy_cache_hit" in ready_before
            and "policy_cache_status" in ready_before
            and "policy_cache_reason" in ready_before
            and "policy_cache_cached_at" in ready_before
            and bool(a1_payload.get("allow_manual_policy_input") is False)
        )
        results.append(
            (
                "ac31_agents_policy_cache_fields_and_default_manual_switch",
                ac31_cache_fields_ok,
                {
                    "allow_manual_policy_input": a1_payload.get("allow_manual_policy_input"),
                    "ready_agent_first": ready_before,
                    "ready_agent_second": ready_hit,
                },
            )
        )

        # Probe screenshots and UI gate states.
        def capture_probe(name: str, params: dict[str, str], *, budget_ms: int = 10000) -> dict:
            url = base + "/?" + urlencode(params)
            dom = edge_dump_dom(edge_path, url=url, budget_ms=budget_ms)
            payload = parse_policy_probe_output(dom)
            shot_path = shots_dir / f"{name}.png"
            edge_screenshot(edge_path, url=url, screenshot_path=shot_path, budget_ms=budget_ms)
            screenshots[name] = shot_path.as_posix()
            return payload

        probe_initial = capture_probe(
            "01-initial-unselected",
            {"policy_probe": "1", "policy_probe_stage": "initial", "policy_probe_capture_delay_ms": "200"},
            budget_ms=5000,
        )
        probe_analyzing = capture_probe(
            "02-selected-analyzing",
            {
                "policy_probe": "1",
                "policy_probe_stage": "analyzing",
                "policy_probe_agent": "ready-agent",
                "policy_probe_delay_ms": "2600",
                "policy_probe_capture_delay_ms": "220",
            },
            budget_ms=1400,
        )
        probe_ready = capture_probe(
            "03-policy-ready",
            {
                "policy_probe": "1",
                "policy_probe_stage": "ready",
                "policy_probe_agent": "ready-agent",
                "policy_probe_capture_delay_ms": "700",
            },
            budget_ms=7000,
        )

        # Enable manual fallback and capture modal.
        m_on_status, m_on_payload = call(
            base,
            "POST",
            "/api/config/manual-policy-input",
            {"allow_manual_policy_input": True},
        )
        probe_manual = capture_probe(
            "04-manual-fallback-modal",
            {
                "policy_probe": "1",
                "policy_probe_stage": "manual",
                "policy_probe_agent": "failed-agent",
                "policy_probe_capture_delay_ms": "900",
            },
            budget_ms=9000,
        )

        analyzing_gate = str(probe_analyzing.get("gate") or "")
        analyzing_disabled = bool(probe_analyzing.get("new_session_disabled"))
        analyzing_valid = bool(
            (analyzing_gate == "analyzing_policy" and analyzing_disabled)
            or (analyzing_gate in {"policy_ready", "policy_confirmed"} and not analyzing_disabled)
        )
        ac32_ui_gate_ok = bool(
            probe_initial.get("gate") == "idle_unselected"
            and bool(probe_initial.get("new_session_disabled"))
            and analyzing_valid
            and probe_ready.get("gate") in {"policy_ready", "policy_confirmed"}
            and (not bool(probe_ready.get("new_session_disabled")))
        )
        results.append(
            (
                "ac32_entry_gate_state_machine_and_button_gate",
                ac32_ui_gate_ok,
                {
                    "probe_initial": probe_initial,
                    "probe_analyzing": probe_analyzing,
                    "probe_ready": probe_ready,
                    "probe_manual": probe_manual,
                    "manual_toggle": {"status": m_on_status, "payload": m_on_payload},
                    "screenshots": screenshots,
                },
            )
        )

        # Cache invalidation demo: modify AGENTS.md then verify recompute (not stale hit).
        ready_md = workspace_root / "ready-agent" / "AGENTS.md"
        before_text = ready_md.read_text(encoding="utf-8")
        ready_md.write_text(before_text + "\n<!-- cache invalidation marker -->\n", encoding="utf-8")
        time.sleep(1.2)
        a3_status, a3_payload = call(base, "GET", "/api/agents")
        if a3_status != 200 or not a3_payload.get("ok"):
            raise RuntimeError(f"/api/agents after modify failed: {a3_status} {a3_payload}")
        ready_after = agent_by_name(list(a3_payload.get("agents") or []), "ready-agent")
        cache_demo = {
            "before_first": {
                "policy_cache_hit": ready_before.get("policy_cache_hit"),
                "policy_cache_status": ready_before.get("policy_cache_status"),
                "policy_cache_reason": ready_before.get("policy_cache_reason"),
                "agents_hash": ready_before.get("agents_hash"),
            },
            "before_second": {
                "policy_cache_hit": ready_hit.get("policy_cache_hit"),
                "policy_cache_status": ready_hit.get("policy_cache_status"),
                "policy_cache_reason": ready_hit.get("policy_cache_reason"),
                "agents_hash": ready_hit.get("agents_hash"),
            },
            "after_modify": {
                "policy_cache_hit": ready_after.get("policy_cache_hit"),
                "policy_cache_status": ready_after.get("policy_cache_status"),
                "policy_cache_reason": ready_after.get("policy_cache_reason"),
                "agents_hash": ready_after.get("agents_hash"),
            },
        }
        after_status = str(ready_after.get("policy_cache_status") or "").lower()
        ac33_cache_invalidation_ok = bool(
            bool(ready_hit.get("policy_cache_hit"))
            and bool(not ready_after.get("policy_cache_hit"))
            and after_status in {"recomputed", "stale"}
        )
        results.append(("ac33_cache_invalidation_on_agents_md_change", ac33_cache_invalidation_ok, cache_demo))

        # Manual fallback controlled + audit mark.
        m_off_status, m_off_payload = call(
            base,
            "POST",
            "/api/config/manual-policy-input",
            {"allow_manual_policy_input": False},
        )
        c_fail_status, c_fail_payload = call(
            base,
            "POST",
            "/api/sessions",
            {"agent_name": "failed-agent", "focus": "ac34-manual-off", "is_test_data": True},
        )
        edit_off_status, edit_off_payload = call(
            base,
            "POST",
            "/api/sessions/policy-confirm",
            {
                "agent_name": "failed-agent",
                "action": "edit",
                "role_profile": "我是 failed-agent 的受控兜底策略。",
                "session_goal": "仅在会话内给出分析建议。",
                "duty_constraints": ["仅分析，不执行高风险操作。", "输出包含验证步骤。"],
                "reason": "manual off should fail",
                "is_test_data": True,
            },
        )
        m_reon_status, m_reon_payload = call(
            base,
            "POST",
            "/api/config/manual-policy-input",
            {"allow_manual_policy_input": True},
        )
        edit_on_status, edit_on_payload = call(
            base,
            "POST",
            "/api/sessions/policy-confirm",
            {
                "agent_name": "failed-agent",
                "action": "edit",
                "role_profile": "我是 failed-agent 的受控兜底策略。",
                "session_goal": "仅在会话内给出分析建议。",
                "duty_constraints": ["仅分析，不执行高风险操作。", "输出包含验证步骤。"],
                "reason": "manual on with audit mark",
                "is_test_data": True,
            },
        )
        manual_session_id = str(edit_on_payload.get("session_id") or "")
        db_path = runtime_root / "state" / "workflow.db"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            audit_row = conn.execute(
                """
                SELECT action,manual_fallback,agent_name,session_id,reason_text
                FROM policy_confirmation_audit
                ORDER BY audit_id DESC
                LIMIT 1
                """
            ).fetchone()
            audit_obj = dict(audit_row) if audit_row else {}
        finally:
            conn.close()
        ac34_manual_guard_ok = bool(
            m_off_status == 200
            and m_off_payload.get("allow_manual_policy_input") is False
            and c_fail_status == 409
            and str(c_fail_payload.get("code") or "") == "agent_policy_extract_failed"
            and edit_off_status == 409
            and str(edit_off_payload.get("code") or "") in {"manual_policy_input_disabled", "manual_policy_input_not_allowed"}
            and m_reon_status == 200
            and bool(m_reon_payload.get("allow_manual_policy_input"))
            and edit_on_status == 200
            and bool(edit_on_payload.get("manual_fallback"))
            and bool(manual_session_id)
            and bool(int(audit_obj.get("manual_fallback") or 0) == 1)
        )
        results.append(
            (
                "ac34_manual_fallback_control_and_audit_mark",
                ac34_manual_guard_ok,
                {
                    "manual_off": {"status": m_off_status, "payload": m_off_payload},
                    "create_failed_agent": {"status": c_fail_status, "payload": c_fail_payload},
                    "edit_manual_off": {"status": edit_off_status, "payload": edit_off_payload},
                    "manual_on": {"status": m_reon_status, "payload": m_reon_payload},
                    "edit_manual_on": {"status": edit_on_status, "payload": edit_on_payload},
                    "latest_audit": audit_obj,
                },
            )
        )

        # Policy source/alignment in trace + workflow events.
        if not manual_session_id:
            raise RuntimeError("manual fallback session not created")
        t_status, t_payload = call(
            base,
            "POST",
            "/api/tasks/execute",
            {
                "agent_name": "failed-agent",
                "session_id": manual_session_id,
                "focus": "ac35-policy-source",
                "message": "你是谁，职责是什么？",
                "is_test_data": True,
            },
        )
        if t_status != 202 or not t_payload.get("ok"):
            raise RuntimeError(f"task execute failed: {t_status} {t_payload}")
        task_id = str(t_payload.get("task_id") or "")
        task_row = wait_task_done(base, task_id, timeout_s=180)
        task_status_ok = str(task_row.get("status") or "").lower() == "success"
        tr_status, tr_payload = call(base, "GET", f"/api/tasks/{task_id}/trace")
        trace = tr_payload.get("trace") if tr_status == 200 else {}
        trace_source = trace.get("policy_source") if isinstance(trace, dict) else {}
        trace_source_type = str((trace_source or {}).get("policy_source") or trace.get("policy_source_type") or "")

        workflow = wait_workflow_for_session(base, manual_session_id, timeout_s=45)
        if not workflow:
            raise RuntimeError(f"workflow not found for session={manual_session_id}")
        workflow_id = str(workflow.get("workflow_id") or "")
        call(base, "POST", "/api/workflows/training/assign", {"workflow_id": workflow_id, "analyst": "Analyst2", "note": "ac35"})
        call(base, "POST", "/api/workflows/training/plan", {"workflow_id": workflow_id})
        call(
            base,
            "POST",
            "/api/workflows/training/execute",
            {"workflow_id": workflow_id, "selected_items": ["decision_skip", "collect_notes"], "max_retries": 2},
        )
        events = wait_workflow_events(base, workflow_id, timeout_s=30)
        has_alignment = all(
            isinstance(item.get("payload"), dict) and str(item.get("payload", {}).get("policy_alignment") or "").strip()
            for item in events
        )
        has_manual_source = any(
            str((item.get("payload") or {}).get("policy_source_type") or "") == "manual_fallback"
            for item in events
        )
        trace_prompt_has_frozen = "[SESSION_POLICY_FROZEN]" in str((trace or {}).get("prompt") or "")
        trace_source_match = trace_source_type == "manual_fallback"
        strong_trace_ok = bool(tr_status == 200 and trace_prompt_has_frozen and trace_source_match)
        event_fallback_ok = bool(events and has_alignment and has_manual_source)
        ac35_policy_source_ok = bool(task_status_ok and strong_trace_ok and event_fallback_ok)
        results.append(
            (
                "ac35_policy_source_and_alignment_consistency",
                ac35_policy_source_ok,
                {
                    "task_id": task_id,
                    "task_status": task_row.get("status"),
                    "trace_status": tr_status,
                    "trace_policy_source": trace_source,
                    "trace_policy_source_type": trace_source_type,
                    "trace_prompt_has_frozen": trace_prompt_has_frozen,
                    "trace_source_match": trace_source_match,
                    "workflow_id": workflow_id,
                    "event_count": len(events),
                    "has_alignment": has_alignment,
                    "has_manual_source": has_manual_source,
                },
            )
        )

    except Exception as exc:
        errors.append(str(exc))
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    now_key = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = out_dir / f"ac31-ac35-acceptance-{now_key}.md"
    lines = [
        f"# AC31-AC35 Acceptance - {now_key}",
        "",
        f"- base_url: {base}",
        f"- runtime_root: {runtime_root.as_posix()}",
        f"- workspace_root: {workspace_root.as_posix()}",
        f"- screenshots_dir: {shots_dir.as_posix()}",
        "",
    ]
    for name, ok, detail in results:
        lines.extend(
            [
                f"## {name}",
                f"- pass: {ok}",
                "- detail:",
                "```json",
                json.dumps(detail, ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    if screenshots:
        lines.extend(["## screenshots", "```json", json.dumps(screenshots, ensure_ascii=False, indent=2), "```", ""])
    if cache_demo:
        lines.extend(["## cache_invalidation_demo", "```json", json.dumps(cache_demo, ensure_ascii=False, indent=2), "```", ""])
    if errors:
        lines.extend(["## errors", "```text", *errors, "```", ""])
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(out_path.as_posix())

    if errors:
        return 1
    if not all(ok for _, ok, _ in results):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
