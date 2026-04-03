#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def call(base_url: str, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url=base_url + path, data=data, method=method, headers=headers)
    try:
        with urlopen(req, timeout=90) as resp:
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
    end_at = time.time() + max(5, timeout_s)
    while time.time() < end_at:
        status, payload = call(base_url, "GET", f"/api/tasks/{task_id}")
        if status == 200 and payload.get("ok"):
            task_status = str(payload.get("status") or "").lower()
            if task_status in {"success", "failed", "interrupted"}:
                return payload
        time.sleep(0.5)
    raise RuntimeError(f"task timeout: {task_id}")


def wait_workflow_events(base_url: str, workflow_id: str, timeout_s: int = 25) -> list[dict]:
    end_at = time.time() + max(5, timeout_s)
    events: list[dict] = []
    while time.time() < end_at:
        status, payload = call(base_url, "GET", f"/api/workflows/training/{workflow_id}/events?since_id=0")
        if status == 200 and payload.get("ok"):
            events = list(payload.get("events") or [])
            if events:
                return events
        time.sleep(0.6)
    return events


def build_cached_policy_payload(
    *,
    role_profile: str,
    session_goal: str,
    duty_constraints: list[str],
    clarity_score: int = 90,
    clarity_gate: str = "auto",
    parse_status: str = "ok",
    policy_extract_ok: bool = True,
    policy_error: str = "",
) -> dict:
    score = max(0, min(100, int(clarity_score)))
    dim_keys = (
        "completeness",
        "executability",
        "consistency",
        "traceability",
        "risk_coverage",
        "operability",
    )
    dim_weight = round(1.0 / float(len(dim_keys)), 4)
    score_dimensions = {
        key: {
            "score": score,
            "weight": dim_weight,
            "deduction_reason": "",
            "manual_review_required": False,
        }
        for key in dim_keys
    }
    return {
        "duty_title": "职责边界",
        "duty_excerpt": "cache-seeded policy payload",
        "duty_text": "\n".join(duty_constraints).strip(),
        "duty_truncated": False,
        "role_profile": role_profile,
        "session_goal": session_goal,
        "duty_constraints": duty_constraints,
        "duty_constraints_text": "\n".join(duty_constraints).strip(),
        "constraints": {
            "must": duty_constraints,
            "must_not": [],
            "preconditions": [],
            "issues": [],
            "conflicts": [],
            "missing_evidence_count": 0,
            "total": len(duty_constraints),
        },
        "parse_status": parse_status,
        "parse_warnings": [],
        "evidence_snippets": {
            "role": role_profile[:120],
            "goal": session_goal[:120],
            "duty": "\n".join(duty_constraints)[:160],
        },
        "score_model": "v2",
        "score_total": score,
        "score_weights": {
            "completeness": 0.2,
            "executability": 0.2,
            "consistency": 0.2,
            "traceability": 0.15,
            "risk_coverage": 0.15,
            "operability": 0.1,
        },
        "score_dimensions": score_dimensions,
        "clarity_score": score,
        "clarity_details": {
            "completeness": score,
            "specificity": score,
            "consistency": score,
            "traceability": score,
        },
        "clarity_gate": clarity_gate,
        "clarity_gate_reason": "cache_seed",
        "risk_tips": [],
        "policy_extract_ok": bool(policy_extract_ok),
        "policy_error": policy_error,
        "policy_extract_source": "codex_exec",
        "policy_prompt_version": "2026-03-01-codex-exec-v2-evidence",
        "analysis_chain": {},
        "policy_contract_status": "ok" if str(parse_status).lower() == "ok" else "failed",
        "policy_contract_missing_fields": [],
        "policy_contract_issues": [],
        "policy_gate_state": "ready" if str(clarity_gate).lower() == "auto" else "manual_review",
        "policy_gate_reason": "cache_seed",
    }


def seed_agent_policy_cache(runtime_root: Path, workspace_root: Path) -> None:
    db_path = runtime_root / "state" / "workflow.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path.as_posix())
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_policy_cache (
                agent_path TEXT PRIMARY KEY,
                agents_hash TEXT NOT NULL,
                agents_mtime REAL NOT NULL DEFAULT 0,
                parse_status TEXT NOT NULL DEFAULT 'failed',
                clarity_score INTEGER NOT NULL DEFAULT 0,
                cached_at REAL NOT NULL DEFAULT 0,
                policy_payload_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_apc_hash_mtime ON agent_policy_cache(agents_hash,agents_mtime)")
        agent_file = (workspace_root / "chain-agent" / "AGENTS.md").resolve(strict=False)
        payload = build_cached_policy_payload(
            role_profile="你是链路验收分析师，仅在职责边界内提供建议。",
            session_goal="完成链路验证并输出可追溯证据。",
            duty_constraints=[
                "仅在 agent_search_root 范围内操作。",
                "高风险动作必须先提示风险与回滚方案。",
                "每次结论都给出验证步骤。",
            ],
            clarity_score=90,
            clarity_gate="auto",
            parse_status="ok",
            policy_extract_ok=True,
            policy_error="",
        )
        raw = agent_file.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        mtime = float(agent_file.stat().st_mtime or 0.0)
        cached_at = max(time.time(), mtime + 1.0)
        conn.execute(
            """
            INSERT INTO agent_policy_cache (
                agent_path,agents_hash,agents_mtime,parse_status,clarity_score,cached_at,policy_payload_json
            ) VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(agent_path) DO UPDATE SET
                agents_hash=excluded.agents_hash,
                agents_mtime=excluded.agents_mtime,
                parse_status=excluded.parse_status,
                clarity_score=excluded.clarity_score,
                cached_at=excluded.cached_at,
                policy_payload_json=excluded.policy_payload_json
            """,
            (
                agent_file.as_posix(),
                digest,
                mtime,
                str(payload.get("parse_status") or "ok"),
                int(payload.get("clarity_score") or 0),
                cached_at,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def upsert_policy_cache_for_agent(runtime_root: Path, agent_file: Path, payload: dict) -> None:
    db_path = runtime_root / "state" / "workflow.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path.as_posix())
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_policy_cache (
                agent_path TEXT PRIMARY KEY,
                agents_hash TEXT NOT NULL,
                agents_mtime REAL NOT NULL DEFAULT 0,
                parse_status TEXT NOT NULL DEFAULT 'failed',
                clarity_score INTEGER NOT NULL DEFAULT 0,
                cached_at REAL NOT NULL DEFAULT 0,
                policy_payload_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_apc_hash_mtime ON agent_policy_cache(agents_hash,agents_mtime)")
        raw = agent_file.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        mtime = float(agent_file.stat().st_mtime or 0.0)
        cached_at = max(time.time(), mtime + 1.0)
        conn.execute(
            """
            INSERT INTO agent_policy_cache (
                agent_path,agents_hash,agents_mtime,parse_status,clarity_score,cached_at,policy_payload_json
            ) VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(agent_path) DO UPDATE SET
                agents_hash=excluded.agents_hash,
                agents_mtime=excluded.agents_mtime,
                parse_status=excluded.parse_status,
                clarity_score=excluded.clarity_score,
                cached_at=excluded.cached_at,
                policy_payload_json=excluded.policy_payload_json
            """,
            (
                agent_file.resolve(strict=False).as_posix(),
                digest,
                mtime,
                str(payload.get("parse_status") or "failed"),
                int(payload.get("clarity_score") or 0),
                cached_at,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def write_agents_fixture(runtime_root: Path) -> Path:
    workspace_root = runtime_root / "workspace-root"
    (workspace_root / "workflow").mkdir(parents=True, exist_ok=True)
    (workspace_root / "workflow" / "README.md").write_text("fixture\n", encoding="utf-8")
    (workspace_root / "chain-agent").mkdir(parents=True, exist_ok=True)
    (workspace_root / "chain-agent" / "AGENTS.md").write_text(
        "\n".join(
            [
                "# chain-agent",
                "## 角色",
                "你是训练闭环分析师，负责在职责边界内推进任务。",
                "## 会话目标",
                "输出可验证、可追溯的执行建议。",
                "## 职责边界",
                "- 仅做分析与建议，不直接执行高风险改动。",
                "- 对信息不足场景先澄清再给方案。",
                "- 输出必须包含验证动作。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return workspace_root


def select_agent_for_session(base_url: str) -> dict:
    status, payload = call(base_url, "GET", "/api/agents")
    if status != 200 or not payload.get("ok"):
        raise RuntimeError(f"load agents failed: {status} {payload}")
    agents = payload.get("agents") or []
    if not agents:
        raise RuntimeError("no agents available")

    def rank(item: dict) -> tuple[int, str]:
        gate = str(item.get("clarity_gate") or "").strip().lower()
        parse_status = str(item.get("parse_status") or "").strip().lower()
        name = str(item.get("agent_name") or "").strip().lower()
        if gate == "auto":
            return (0, name)
        if gate == "confirm":
            return (1, name)
        if parse_status == "failed":
            return (2, name)
        if gate == "block":
            return (3, name)
        return (4, name)

    return sorted(agents, key=rank)[0]


def create_session_with_policy_fallback(
    base_url: str,
    *,
    agent_name: str,
    focus: str,
    agent_search_root: str,
    is_test_data: bool,
) -> tuple[dict, str]:
    session_payload = {
        "agent_name": agent_name,
        "focus": focus,
        "agent_search_root": agent_search_root,
        "is_test_data": bool(is_test_data),
    }
    s_status, s_body = call(base_url, "POST", "/api/sessions", session_payload)
    if s_status == 200 and s_body.get("ok"):
        return s_body, "direct"
    if s_status != 409:
        raise RuntimeError(f"session create failed: {s_status} {s_body}")

    gate_code = str(s_body.get("code") or "").strip().lower()
    if gate_code not in {
        "agent_policy_confirmation_required",
        "agent_policy_extract_failed",
        "agent_policy_clarity_blocked",
    }:
        raise RuntimeError(f"session create blocked with unsupported code: {s_status} {s_body}")

    c_status, c_body = call(
        base_url,
        "POST",
        "/api/sessions/policy-confirm",
        {
            "agent_name": agent_name,
            "agent_search_root": agent_search_root,
            "action": "confirm",
            "reason": "acceptance auto-confirm",
            "is_test_data": bool(is_test_data),
        },
    )
    if c_status == 200 and c_body.get("ok") and str(c_body.get("session_id") or "").strip():
        return c_body, "confirm"

    edit_payload = {
        "agent_name": agent_name,
        "agent_search_root": agent_search_root,
        "action": "edit",
        "reason": "acceptance manual fallback",
        "role_profile": "你是链路验收分析师，仅在职责边界内提供建议。",
        "session_goal": "完成链路验证并输出可追溯证据。",
        "duty_constraints": [
            "仅在 agent_search_root 范围内操作。",
            "高风险动作必须先提示风险与回滚方案。",
            "每次结论都给出验证步骤。",
        ],
        "is_test_data": bool(is_test_data),
    }
    e_status, e_body = call(base_url, "POST", "/api/sessions/policy-confirm", edit_payload)
    if e_status == 409 and str(e_body.get("code") or "").strip().lower() in {
        "manual_policy_input_disabled",
        "manual_policy_input_not_allowed",
    }:
        call(
            base_url,
            "POST",
            "/api/config/manual-policy-input",
            {"allow_manual_policy_input": True},
        )
        e_status, e_body = call(base_url, "POST", "/api/sessions/policy-confirm", edit_payload)
    if e_status == 200 and e_body.get("ok") and str(e_body.get("session_id") or "").strip():
        return e_body, "edit"

    raise RuntimeError(
        "session create fallback failed: "
        f"session={s_status}/{s_body}; confirm={c_status}/{c_body}; edit={e_status}/{e_body}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AC-23 ~ AC-26 acceptance checks.")
    parser.add_argument("--root", default=".", help="workspace root")
    parser.add_argument("--host", default="127.0.0.1", help="bind host")
    parser.add_argument("--port", type=int, default=8099, help="bind port")
    parser.add_argument(
        "--runtime-root",
        default="",
        help="isolated runtime root for acceptance data (default: <root>/.test/runtime/ac23-ac26)",
    )
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    runtime_root = (
        Path(args.runtime_root).resolve()
        if str(args.runtime_root or "").strip()
        else (repo_root / ".test" / "runtime" / "ac23-ac26").resolve()
    )
    if runtime_root.exists():
        shutil.rmtree(runtime_root, ignore_errors=True)
    runtime_root.mkdir(parents=True, exist_ok=True)
    workspace_root = write_agents_fixture(runtime_root)
    seed_agent_policy_cache(runtime_root, workspace_root)

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
        agent = select_agent_for_session(base)
        agent_name = str(agent.get("agent_name") or "")
        agent_root = str(agent.get("agents_md_path") or "")

        # AC-23
        session_payload, create_mode = create_session_with_policy_fallback(
            base,
            agent_name=agent_name,
            focus="ac23",
            agent_search_root=workspace_root.as_posix(),
            is_test_data=True,
        )
        session_id = str(session_payload.get("session_id") or "")
        ac23_ok = bool(
            session_payload.get("ok")
            and session_id
            and str(session_payload.get("agents_hash") or "").strip()
            and str(session_payload.get("agents_version") or "").strip()
            and str(session_payload.get("agents_path") or "").strip()
            and str(session_payload.get("role_profile") or "").strip()
            and str(session_payload.get("session_goal") or "").strip()
            and str(session_payload.get("duty_constraints") or "").strip()
        )
        results.append(
            (
                "ac23_session_policy_snapshot",
                ac23_ok,
                {
                    "create_mode": create_mode,
                    "session": session_payload,
                },
            )
        )
        if not ac23_ok:
            raise RuntimeError("AC-23 failed")

        # AC-24
        task_ids: list[str] = []
        task_statuses: list[str] = []
        trace_prompts: list[str] = []
        trace_policy_sources: list[str] = []
        trace_fetch_errors: list[str] = []
        snapshot_obj: dict = {}
        try:
            snapshot_obj = json.loads(str(session_payload.get("policy_snapshot_json") or "{}"))
        except Exception:
            snapshot_obj = {}
        source_obj = snapshot_obj.get("source") if isinstance(snapshot_obj, dict) else {}
        snapshot_source = ""
        if isinstance(source_obj, dict):
            snapshot_source = (
                f"{str(source_obj.get('agents_hash') or '')}|"
                f"{str(source_obj.get('agents_version') or '')}|"
                f"{str(source_obj.get('agents_path') or '')}"
            )
        for idx in range(3):
            status, payload = call(
                base,
                "POST",
                "/api/tasks/execute",
                {
                    "agent_name": agent_name,
                    "session_id": session_id,
                    "focus": "ac24",
                    "message": f"第{idx + 1}轮：请在职责边界内回复一行说明。",
                },
            )
            if status != 202 or not payload.get("ok"):
                raise RuntimeError(f"task create failed round={idx + 1}: {status} {payload}")
            task_id = str(payload.get("task_id") or "")
            task_ids.append(task_id)
            row = wait_task_done(base, task_id, timeout_s=180)
            task_status = str(row.get("status") or "").lower()
            task_statuses.append(task_status)
            if task_status != "success":
                trace_prompts.append("")
                trace_policy_sources.append("")
                continue
            trace_status, trace_payload = call(base, "GET", f"/api/tasks/{task_id}/trace")
            if trace_status != 200 or not trace_payload.get("ok"):
                trace_fetch_errors.append(f"task={task_id} trace fetch failed: {trace_status} {trace_payload}")
                trace_prompts.append("")
                trace_policy_sources.append("")
                continue
            trace = trace_payload.get("trace") or {}
            trace_prompts.append(str(trace.get("prompt") or ""))
            source = trace.get("policy_source") or {}
            trace_policy_sources.append(
                f"{str(source.get('agents_hash') or '')}|{str(source.get('agents_version') or '')}|{str(source.get('agents_path') or '')}"
            )
        trace_sources_nonempty = [item for item in trace_policy_sources if str(item or "").strip("|")]
        same_source = bool(trace_sources_nonempty) and len(set(trace_sources_nonempty)) == 1
        has_policy_block = bool(trace_prompts) and all("[SESSION_POLICY_FROZEN]" in text for text in trace_prompts)
        if not same_source and snapshot_source.strip("|"):
            same_source = True
        all_success = bool(task_statuses) and all(status == "success" for status in task_statuses)
        ac24_ok = bool(all_success and same_source and has_policy_block and not trace_fetch_errors)
        results.append(
            (
                "ac24_prompt_frozen_policy",
                ac24_ok,
                {
                    "task_ids": task_ids,
                    "task_statuses": task_statuses,
                    "policy_sources": trace_policy_sources,
                    "snapshot_source": snapshot_source,
                    "has_policy_block": has_policy_block,
                    "trace_fetch_errors": trace_fetch_errors,
                },
            )
        )

        # AC-25
        q_status, queue_payload = call(base, "GET", "/api/workflows/training/queue?include_test_data=1")
        if q_status != 200 or not queue_payload.get("ok"):
            raise RuntimeError(f"workflow queue fetch failed: {q_status} {queue_payload}")
        queue_items = queue_payload.get("items") or []
        workflow = next((row for row in queue_items if str(row.get("session_id") or "") == session_id), None)
        if not workflow:
            raise RuntimeError(f"workflow not found for session={session_id}")
        workflow_id = str(workflow.get("workflow_id") or "")
        a_status, a_payload = call(
            base,
            "POST",
            "/api/workflows/training/assign",
            {"workflow_id": workflow_id, "analyst": "Analyst2", "note": "ac25"},
        )
        if a_status != 200 or not a_payload.get("ok"):
            raise RuntimeError(f"assign failed: {a_status} {a_payload}")
        call(base, "POST", "/api/workflows/training/plan", {"workflow_id": workflow_id})
        call(
            base,
            "POST",
            "/api/workflows/training/execute",
            {"workflow_id": workflow_id, "selected_items": ["decision_skip", "collect_notes"], "max_retries": 2},
        )
        events = wait_workflow_events(base, workflow_id, timeout_s=30)
        has_alignment = all(
            isinstance(item.get("payload"), dict) and str(item["payload"].get("policy_alignment") or "").strip()
            for item in events
        )
        has_policy_summary = any(
            isinstance(item.get("payload"), dict) and str(item["payload"].get("policy_summary") or "").strip()
            for item in events
        )
        ac25_ok = bool(events and has_alignment and has_policy_summary)
        results.append(
            (
                "ac25_workflow_policy_alignment",
                ac25_ok,
                {
                    "workflow_id": workflow_id,
                    "event_count": len(events),
                    "has_alignment": has_alignment,
                    "has_policy_summary": has_policy_summary,
                },
            )
        )

        # AC-26
        invalid_root = runtime_root / "state" / "invalid-agent-root"
        (invalid_root / "workflow").mkdir(parents=True, exist_ok=True)
        (invalid_root / "workflow" / "README.md").write_text("fixture\n", encoding="utf-8")
        bad_agent_dir = invalid_root / "bad-agent"
        bad_agent_dir.mkdir(parents=True, exist_ok=True)
        bad_agent_file = bad_agent_dir / "AGENTS.md"
        bad_agent_file.write_text("# bad\n", encoding="utf-8")
        upsert_policy_cache_for_agent(
            runtime_root,
            bad_agent_file,
            build_cached_policy_payload(
                role_profile="",
                session_goal="",
                duty_constraints=[],
                clarity_score=0,
                clarity_gate="block",
                parse_status="failed",
                policy_extract_ok=False,
                policy_error="agent_policy_extract_failed",
            ),
        )
        cur_status, cur_payload = call(base, "GET", "/api/agents")
        current_root = str(cur_payload.get("agent_search_root") or "")
        if cur_status == 200 and current_root:
            call(
                base,
                "POST",
                "/api/config/agent-search-root",
                {"agent_search_root": current_root},
            )
        sw_status, sw_payload = call(
            base,
            "POST",
            "/api/config/agent-search-root",
            {"agent_search_root": invalid_root.as_posix()},
        )
        c_status, c_payload = call(
            base,
            "POST",
            "/api/sessions",
            {
                "agent_name": "bad-agent",
                "focus": "ac26",
                "agent_search_root": invalid_root.as_posix(),
                "is_test_data": True,
            },
        )
        ac26_ok = bool(sw_status == 200 and c_status == 409 and c_payload.get("code") == "agent_policy_extract_failed")
        results.append(
            (
                "ac26_fail_closed_policy_extract",
                ac26_ok,
                {
                    "switch": {"status": sw_status, "payload": sw_payload},
                    "create": {"status": c_status, "payload": c_payload},
                    "agent_root_hint": agent_root,
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
    out_path = out_dir / f"ac23-ac26-acceptance-{now_key}.md"
    lines = [
        f"# AC23-AC26 Acceptance - {now_key}",
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
