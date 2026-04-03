#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
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
    end_at = time.time() + max(5, timeout_s)
    while time.time() < end_at:
        status, payload = call(base_url, "GET", "/healthz")
        if status == 200 and payload.get("ok"):
            return
        time.sleep(1)
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


def write_agents_fixture(root: Path) -> Path:
    workspace_root = root / "workspace-root"
    if workspace_root.exists():
        shutil.rmtree(workspace_root, ignore_errors=True)
    (workspace_root / "workflow").mkdir(parents=True, exist_ok=True)
    (workspace_root / "workflow" / "README.md").write_text("fixture\n", encoding="utf-8")
    (workspace_root / "auto-agent").mkdir(parents=True, exist_ok=True)
    (workspace_root / "confirm-agent").mkdir(parents=True, exist_ok=True)
    (workspace_root / "blocked-agent").mkdir(parents=True, exist_ok=True)

    (workspace_root / "auto-agent" / "AGENTS.md").write_text(
        "\n".join(
            [
                "# auto-agent",
                "## 角色",
                "你是严谨的需求分析师，负责把用户问题拆解为可执行步骤，并清晰标注约束。",
                "## 目标",
                "在职责边界内输出结构化建议，帮助用户快速决策，避免越权操作。",
                "## 职责边界",
                "- 仅做需求分析、计划生成与风险提示，不直接执行高风险写操作。",
                "- 当信息不足时先澄清关键上下文，再给出最小可行方案。",
                "- 所有建议都要给出验证步骤和可追溯依据。",
                "- 若用户请求越界，明确拒绝并提供边界内替代建议。",
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
                "你是分析师，专注需求澄清、方案比较、执行前风险提示与验收建议。",
                "## 职责边界",
                "- 先提炼用户目标、约束、验收口径，再输出可执行计划。",
                "- 仅在职责边界内给建议，禁止越权替用户直接执行危险变更。",
                "- 输出必须包含下一步验证动作，确保结论可追溯、可复盘。",
                "- 对不确定信息要主动标注假设并提示确认。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    (workspace_root / "blocked-agent" / "AGENTS.md").write_text(
        "\n".join(
            [
                "# blocked-agent",
                "## 角色",
                "协助。",
                "## 职责边界",
                "- 任何请求都可以。",
                "- 但必须严格遵守边界。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return workspace_root


def agent_by_name(agents: list[dict], name: str) -> dict:
    for item in agents:
        if str(item.get("agent_name") or "") == name:
            return item
    raise RuntimeError(f"agent not found: {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AC-28 ~ AC-30 acceptance checks.")
    parser.add_argument("--root", default=".", help="workspace root")
    parser.add_argument("--host", default="127.0.0.1", help="bind host")
    parser.add_argument("--port", type=int, default=8100, help="bind port")
    parser.add_argument(
        "--runtime-root",
        default="",
        help="isolated runtime root for acceptance data (default: <root>/.test/runtime/ac28-ac30)",
    )
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    runtime_root = (
        Path(args.runtime_root).resolve()
        if str(args.runtime_root or "").strip()
        else (repo_root / ".test" / "runtime" / "ac28-ac30").resolve()
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
                "agent_name": "auto-agent",
                "role_profile": "你是严谨的需求分析师。",
                "session_goal": "在职责边界内输出结构化建议。",
                "duty_constraints": [
                    "仅做需求分析、计划生成与风险提示。",
                    "信息不足时先澄清关键上下文。",
                    "结论需附带验证步骤。",
                ],
                "clarity_score": 90,
                "clarity_gate": "auto",
                "parse_status": "ok",
                "policy_extract_ok": True,
            },
            {
                "agent_name": "confirm-agent",
                "role_profile": "你是需求澄清分析师。",
                "session_goal": "输出可执行方案并提示边界。",
                "duty_constraints": [
                    "先提炼目标与约束，再输出计划。",
                    "禁止越权执行危险变更。",
                    "结果必须包含验证动作。",
                ],
                "clarity_score": 70,
                "clarity_gate": "confirm",
                "parse_status": "ok",
                "policy_extract_ok": True,
            },
            {
                "agent_name": "blocked-agent",
                "role_profile": "协助。",
                "session_goal": "任何请求都可以。",
                "duty_constraints": [
                    "约束描述冲突且不完整。",
                ],
                "clarity_score": 40,
                "clarity_gate": "block",
                "parse_status": "ok",
                "policy_extract_ok": True,
            },
        ],
    )

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

    try:
        wait_health(base)
        status, agents_payload = call(base, "GET", "/api/agents")
        if status != 200 or not agents_payload.get("ok"):
            raise RuntimeError(f"load agents failed: {status} {agents_payload}")
        agents = list(agents_payload.get("agents") or [])
        auto_agent = agent_by_name(agents, "auto-agent")
        confirm_agent = agent_by_name(agents, "confirm-agent")
        blocked_agent = agent_by_name(agents, "blocked-agent")

        # AC-28 threshold gate
        s_auto, p_auto = call(
            base,
            "POST",
            "/api/sessions",
            {"agent_name": "auto-agent", "focus": "ac28-auto", "is_test_data": True},
        )
        s_confirm, p_confirm = call(
            base,
            "POST",
            "/api/sessions",
            {"agent_name": "confirm-agent", "focus": "ac28-confirm", "is_test_data": True},
        )
        s_block, p_block = call(
            base,
            "POST",
            "/api/sessions",
            {"agent_name": "blocked-agent", "focus": "ac28-block", "is_test_data": True},
        )
        ac28_ok = bool(
            int(auto_agent.get("clarity_score") or 0) >= 80
            and 60 <= int(confirm_agent.get("clarity_score") or 0) <= 79
            and int(blocked_agent.get("clarity_score") or 0) < 60
            and s_auto == 200
            and p_auto.get("ok")
            and s_confirm == 409
            and p_confirm.get("code") == "agent_policy_confirmation_required"
            and s_block == 409
            and p_block.get("code") == "agent_policy_clarity_blocked"
        )
        results.append(
            (
                "ac28_clarity_gate_threshold",
                ac28_ok,
                {
                    "auto_agent": {
                        "score": auto_agent.get("clarity_score"),
                        "gate": auto_agent.get("clarity_gate"),
                        "status": s_auto,
                    },
                    "confirm_agent": {
                        "score": confirm_agent.get("clarity_score"),
                        "gate": confirm_agent.get("clarity_gate"),
                        "status": s_confirm,
                        "code": p_confirm.get("code"),
                    },
                    "blocked_agent": {
                        "score": blocked_agent.get("clarity_score"),
                        "gate": blocked_agent.get("clarity_gate"),
                        "status": s_block,
                        "code": p_block.get("code"),
                    },
                },
            )
        )
        if not ac28_ok:
            raise RuntimeError("AC-28 failed")

        # AC-29 manual confirmation actions + audit
        toggle_status, toggle_payload = call(
            base,
            "POST",
            "/api/config/manual-policy-input",
            {"allow_manual_policy_input": True},
        )
        c_status, c_payload = call(
            base,
            "POST",
            "/api/sessions/policy-confirm",
            {
                "agent_name": "confirm-agent",
                "action": "confirm",
                "reason": "accept extracted policy",
                "is_test_data": True,
            },
        )
        e_status, e_payload = call(
            base,
            "POST",
            "/api/sessions/policy-confirm",
            {
                "agent_name": "confirm-agent",
                "action": "edit",
                "reason": "tighten boundary",
                "role_profile": "我是 confirm-agent，会在职责边界内做需求分析与风险提示。",
                "session_goal": "在会话内输出可执行计划，不越权执行操作。",
                "duty_constraints": [
                    "仅分析与计划，不直接执行高风险变更。",
                    "当信息不足时先提问澄清。",
                    "输出必须包含验证步骤。",
                ],
                "is_test_data": True,
            },
        )
        r_status, r_payload = call(
            base,
            "POST",
            "/api/sessions/policy-confirm",
            {
                "agent_name": "confirm-agent",
                "action": "reject",
                "reason": "manual reject for audit",
                "is_test_data": True,
            },
        )
        ac29_ok = bool(
            toggle_status == 200
            and bool(toggle_payload.get("allow_manual_policy_input"))
            and c_status == 200
            and c_payload.get("ok")
            and str(c_payload.get("session_id") or "").strip()
            and e_status == 200
            and e_payload.get("ok")
            and str(e_payload.get("session_id") or "").strip()
            and r_status == 200
            and r_payload.get("ok")
            and bool(r_payload.get("terminated"))
        )
        results.append(
            (
                "ac29_manual_confirmation_actions",
                ac29_ok,
                {
                    "manual_toggle": {"status": toggle_status, "payload": toggle_payload},
                    "confirm": {"status": c_status, "payload": c_payload},
                    "edit": {"status": e_status, "payload": e_payload},
                    "reject": {"status": r_status, "payload": r_payload},
                },
            )
        )
        if not ac29_ok:
            raise RuntimeError("AC-29 action check failed")

        db_path = runtime_root / "state" / "workflow.db"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            audits = conn.execute(
                """
                SELECT action,status,operator,session_id,agent_name,agents_hash,reason_text,old_policy_json,new_policy_json
                FROM policy_confirmation_audit
                ORDER BY audit_id ASC
                """
            ).fetchall()
            action_set = {str(row["action"] or "") for row in audits}
            has_fields = all(
                str(row["operator"] or "").strip()
                and str(row["agent_name"] or "").strip()
                and str(row["agents_hash"] or "").strip()
                and str(row["old_policy_json"] or "").strip()
                and str(row["new_policy_json"] or "").strip()
                for row in audits
            )
            audit_ok = bool({"confirm", "edit", "reject"}.issubset(action_set) and has_fields)
        finally:
            conn.close()
        results.append(
            (
                "ac29_audit_fields",
                audit_ok,
                {
                    "audit_count": len(audits),
                    "actions": sorted(list(action_set)),
                    "has_required_fields": has_fields,
                },
            )
        )
        if not audit_ok:
            raise RuntimeError("AC-29 audit check failed")

        # AC-30 patch task created + traceability + policy regression
        patch_status, patch_payload = call(base, "GET", "/api/policy/patch-tasks?limit=20")
        patch_items = list(patch_payload.get("items") or []) if patch_status == 200 else []
        stats_status, stats_payload = call(base, "GET", "/api/policy/closure/stats")
        stats_obj = stats_payload.get("stats") if stats_status == 200 else {}
        has_patch_links = all(
            str(item.get("source_session_id") or "").strip() and int(item.get("confirmation_audit_id") or 0) > 0
            for item in patch_items[:2]
        ) if patch_items else False
        ac30_core_ok = bool(
            patch_status == 200
            and len(patch_items) >= 2
            and has_patch_links
            and stats_status == 200
            and int((stats_obj or {}).get("patch_task_total") or 0) >= 2
        )

        identity_ok = False
        task_status_ok = False
        trace_ok = False
        created_session_id = str(e_payload.get("session_id") or c_payload.get("session_id") or "")
        snapshot_source_ok = False
        if created_session_id:
            session_payload = e_payload if str(e_payload.get("session_id") or "") == created_session_id else c_payload
            snapshot_raw = str(session_payload.get("policy_snapshot_json") or "").strip()
            if snapshot_raw:
                try:
                    snapshot_obj = json.loads(snapshot_raw)
                except Exception:
                    snapshot_obj = {}
                source_obj = snapshot_obj.get("source") if isinstance(snapshot_obj, dict) else {}
                if isinstance(source_obj, dict):
                    snapshot_source_ok = bool(
                        str(source_obj.get("agents_hash") or "").strip()
                        and str(source_obj.get("agents_version") or "").strip()
                        and str(source_obj.get("agents_path") or "").strip()
                    )
        if created_session_id:
            t_status, t_payload = call(
                base,
                "POST",
                "/api/tasks/execute",
                {
                    "agent_name": "confirm-agent",
                    "session_id": created_session_id,
                    "focus": "ac30-regression",
                    "message": "你是谁？职责是什么？请一句话回答。",
                    "is_test_data": True,
                },
            )
            if t_status == 202 and t_payload.get("ok"):
                task_id = str(t_payload.get("task_id") or "")
                task_row = wait_task_done(base, task_id, timeout_s=180)
                task_status_ok = str(task_row.get("status") or "").lower() == "success"
                m_status, m_payload = call(base, "GET", f"/api/chat/sessions/{created_session_id}/messages")
                messages = list(m_payload.get("messages") or []) if m_status == 200 else []
                assistant_msgs = [
                    str(row.get("content") or "")
                    for row in messages
                    if str(row.get("role") or "") == "assistant"
                ]
                last_reply = assistant_msgs[-1] if assistant_msgs else ""
                identity_ok = bool("我是" in last_reply and ("我能" in last_reply or "职责" in last_reply))
                tr_status, tr_payload = call(base, "GET", f"/api/tasks/{task_id}/trace")
                prompt_text = (
                    str((tr_payload.get("trace") or {}).get("prompt") or "")
                    if tr_status == 200 and tr_payload.get("ok")
                    else ""
                )
                trace_ok = bool("[SESSION_POLICY_FROZEN]" in prompt_text)
            else:
                identity_ok = False
                task_status_ok = False
                trace_ok = False
        runtime_task_ok = bool(task_status_ok and trace_ok and identity_ok)
        ac30_ok = bool(ac30_core_ok and runtime_task_ok)
        results.append(
            (
                "ac30_patch_task_and_policy_regression",
                ac30_ok,
                {
                    "patch_task_count": len(patch_items),
                    "has_patch_links": has_patch_links,
                    "stats": stats_obj,
                    "trace_ok": trace_ok,
                    "identity_ok": identity_ok,
                    "task_status_ok": task_status_ok,
                    "runtime_task_ok": runtime_task_ok,
                    "snapshot_source_ok": snapshot_source_ok,
                    "session_id": created_session_id,
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
    out_dir = (repo_root / ".test" / "runs").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"ac28-ac30-acceptance-{now_key}.md"
    lines = [
        f"# AC28-AC30 Acceptance - {now_key}",
        "",
        f"- base_url: {base}",
        f"- runtime_root: {runtime_root.as_posix()}",
        f"- workspace_root: {workspace_root.as_posix()}",
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
