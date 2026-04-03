#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
BIN_ROOT = SCRIPTS_ROOT / "bin"
SRC_ROOT = SCRIPTS_ROOT.parent / "src"
if str(BIN_ROOT) not in sys.path:
    sys.path.insert(0, str(BIN_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import workflow_web_server as wf
from workflow_app.server.services import training_workflow_execution_service as tw_exec

BEIJING_TZ = timezone(timedelta(hours=8))


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def now_key() -> str:
    return datetime.now(BEIJING_TZ).strftime("%Y%m%d-%H%M%S")


def init_sandbox(repo_root: Path, key: str) -> Path:
    root = repo_root / ".test" / "evidence" / f"ac16-ac22-{key}"
    wf.ensure_dirs(root)
    wf.ensure_tables(root)
    return root


def make_cfg(root: Path) -> wf.AppConfig:
    return wf.AppConfig(
        root=root,
        entry_script=(SCRIPTS_ROOT / "workflow_entry_cli.py").resolve(),
        agent_search_root=root,
        show_test_data=True,
        host="127.0.0.1",
        port=0,
        focus="ac16-ac22",
        reconcile_interval_s=60,
        allow_manual_policy_input=True,
    )


def create_session(root: Path, session_id: str) -> None:
    ts = wf.iso_ts(wf.now_local())
    snapshot = wf.build_session_policy_snapshot(
        agent_name="AnalystAlpha",
        agents_path=(root / "agents" / "AnalystAlpha" / "AGENTS.md").as_posix(),
        agents_hash="a" * 64,
        agents_version="a" * 12,
        role_profile="需求分析师",
        session_goal="围绕用户需求澄清并形成可执行文档",
        duty_constraints="仅做需求分析与文档输出，不执行跨职责工程改造",
    )
    wf.create_session_record(
        root,
        session_id=session_id,
        agent_name="AnalystAlpha",
        agents_hash="a" * 64,
        agents_loaded_at=ts,
        agents_path=(root / "agents" / "AnalystAlpha" / "AGENTS.md").as_posix(),
        agents_version="a" * 12,
        agent_search_root=root.as_posix(),
        target_path=root.as_posix(),
        role_profile=str(snapshot.get("role_profile") or ""),
        session_goal=str(snapshot.get("session_goal") or ""),
        duty_constraints=str(snapshot.get("duty_constraints") or ""),
        policy_snapshot_json=json.dumps(snapshot, ensure_ascii=False),
    )


def seed_workflow(root: Path, session_id: str, messages: list[tuple[str, str]]) -> str:
    create_session(root, session_id)
    for role, content in messages:
        wf.add_message(root, session_id, role, content)
    wf.persist_event(
        root,
        {
            "event_id": wf.event_id(),
            "timestamp": wf.iso_ts(wf.now_local()),
            "session_id": session_id,
            "actor": "user",
            "stage": "chat",
            "action": "send_message",
            "status": "success",
            "latency_ms": 1,
            "task_id": "",
            "reason_tags": ["acceptance_seed"],
            "ref": "acceptance",
        },
    )
    wf.sync_analysis_tasks(root)
    wf.sync_training_workflows(root)
    row = next(
        (item for item in wf.list_training_workflows(root, limit=2000) if str(item.get("session_id")) == session_id),
        None,
    )
    assert_true(row is not None, f"workflow not found for session={session_id}")
    return str(row["workflow_id"])


def dialogue_rows(root: Path, session_id: str) -> list[dict[str, Any]]:
    return wf.list_session_dialogue_messages(root, session_id, limit=0)


def workflow_for_session(root: Path, session_id: str) -> dict[str, Any]:
    row = next(
        (item for item in wf.list_training_workflows(root, limit=2000) if str(item.get("session_id")) == session_id),
        None,
    )
    assert_true(row is not None, f"workflow missing for session={session_id}")
    return row or {}


def latest_delete_audit(root: Path, session_id: str, message_id: int) -> dict[str, Any]:
    conn = wf.connect_db(root)
    try:
        row = conn.execute(
            """
            SELECT audit_id,audit_ts,operator,session_id,message_id,status,reason_code,reason_text,impact_scope,workflow_id,analysis_run_id,training_plan_items,ref
            FROM message_delete_audit
            WHERE session_id=? AND message_id=?
            ORDER BY audit_id DESC
            LIMIT 1
            """,
            (session_id, int(message_id)),
        ).fetchone()
    finally:
        conn.close()
    assert_true(row is not None, "delete audit row missing")
    return {k: row[k] for k in row.keys()} if row else {}


def run_ac16(root: Path, cfg: wf.AppConfig, state: wf.RuntimeState) -> dict[str, Any]:
    sid1 = f"ac16-s1-{uuid.uuid4().hex[:6]}"
    sid2 = f"ac16-s2-{uuid.uuid4().hex[:6]}"
    wid1 = seed_workflow(root, sid1, [("user", "请总结今天会议"), ("assistant", "今天讨论了交付节奏。")])
    wid2 = seed_workflow(root, sid2, [("user", "请给出上线清单"), ("assistant", "需要补齐回滚预案。")])

    s1_ids = [int(item["message_id"]) for item in dialogue_rows(root, sid1)]
    wf.set_message_analysis_state(
        root,
        sid1,
        s1_ids,
        state_text=wf.ANALYSIS_STATE_DONE,
        reason="",
        run_id="ac16-manual",
    )

    gate1 = wf.session_analysis_gate(root, sid1)
    gate2 = wf.session_analysis_gate(root, sid2)
    assert_true(not bool(gate1.get("analysis_selectable")), "S1 should be non-selectable")
    assert_true(str(gate1.get("analysis_block_reason_code")) == "all_messages_analyzed", "S1 reason code mismatch")
    assert_true(bool(gate2.get("analysis_selectable")), "S2 should be selectable")

    blocked_code = ""
    try:
        wf.assign_training_workflow(cfg, state, wid1, "AnalystAlpha", "ac16")
    except wf.WorkflowGateError as exc:
        blocked_code = str(exc.code)
    assert_true(blocked_code == "all_messages_analyzed", "assign should be blocked for all-analyzed session")

    queue_s1 = workflow_for_session(root, sid1)
    queue_s2 = workflow_for_session(root, sid2)
    return {
        "s1_workflow_id": wid1,
        "s2_workflow_id": wid2,
        "s1_gate": gate1,
        "s2_gate": gate2,
        "assign_blocked_code": blocked_code,
        "queue_s1_analysis_selectable": queue_s1.get("analysis_selectable"),
        "queue_s1_block_reason": queue_s1.get("analysis_block_reason"),
        "queue_s2_analysis_selectable": queue_s2.get("analysis_selectable"),
    }


def run_ac17(root: Path, cfg: wf.AppConfig, state: wf.RuntimeState) -> dict[str, Any]:
    sid = f"ac17-s-{uuid.uuid4().hex[:6]}"
    wid = seed_workflow(
        root,
        sid,
        [
            ("user", "历史消息：先整理需求"),
            ("assistant", "已记录需求约束。"),
            ("user", "新增消息：请补齐验收脚本"),
            ("assistant", "会补齐 AC 对照与证据。"),
        ],
    )
    all_rows = dialogue_rows(root, sid)
    all_ids = [int(item["message_id"]) for item in all_rows]
    wf.run_analysis_worker(cfg, state, wid)
    run = wf.latest_analysis_run(root, wid)
    assert_true(run is not None, "analysis_run should be created")
    ctx_ids = [int(v) for v in (run or {}).get("context_message_ids", [])]
    assert_true(ctx_ids == all_ids, "analysis context ids must equal full dialogue ids")
    summary = str((wf.get_training_workflow(root, wid) or {}).get("analysis_summary") or "")
    assert_true("context_mode=full_session" in summary, "analysis summary must contain full_session marker")
    return {
        "workflow_id": wid,
        "analysis_run_id": str((run or {}).get("analysis_run_id") or ""),
        "context_message_ids": ctx_ids,
        "all_message_ids": all_ids,
        "analysis_summary": summary,
    }


def run_ac18(root: Path, cfg: wf.AppConfig, state: wf.RuntimeState) -> dict[str, Any]:
    sid_train = f"ac18-train-{uuid.uuid4().hex[:6]}"
    wid_train = seed_workflow(
        root,
        sid_train,
        [
            ("user", "请整理训练样本并给出标签"),
            ("assistant", "已整理样本来源。"),
        ],
    )
    wf.run_analysis_worker(cfg, state, wid_train)
    plan_data = wf.generate_training_workflow_plan(cfg, wid_train)
    run_id = str(plan_data.get("analysis_run_id") or "")
    plan = plan_data.get("plan") or []
    assert_true(bool(run_id), "analysis_run_id should not be empty")
    assert_true(len(plan) > 0, "trainable session should have plan items")
    for item in plan:
        assert_true(str(item.get("analysis_run_id") or "") == run_id, "plan item run_id mismatch")
        assert_true(isinstance(item.get("message_ids"), list), "plan item message_ids must be list")

    conn = wf.connect_db(root)
    try:
        rows = conn.execute(
            "SELECT item_key,message_ids_json FROM analysis_run_plan_items WHERE workflow_id=? AND analysis_run_id=? ORDER BY item_key ASC",
            (wid_train, run_id),
        ).fetchall()
    finally:
        conn.close()
    assert_true(len(rows) == len(plan), "analysis_run_plan_items row count mismatch")

    sid_skip = f"ac18-skip-{uuid.uuid4().hex[:6]}"
    wid_skip = seed_workflow(
        root,
        sid_skip,
        [
            ("user", "好"),
            ("assistant", "收到"),
        ],
    )
    wf.run_analysis_worker(cfg, state, wid_skip)
    skip_plan = wf.generate_training_workflow_plan(cfg, wid_skip)
    assert_true(len(skip_plan.get("plan") or []) == 0, "no-value session should allow zero plan items")
    assert_true(str(skip_plan.get("no_value_reason") or "") == "no_training_value", "no_value_reason mismatch")
    return {
        "train_workflow_id": wid_train,
        "analysis_run_id": run_id,
        "plan_count": len(plan),
        "db_plan_count": len(rows),
        "skip_workflow_id": wid_skip,
        "skip_plan_count": len(skip_plan.get("plan") or []),
        "skip_no_value_reason": skip_plan.get("no_value_reason"),
    }


def run_ac19(root: Path, cfg: wf.AppConfig, state: wf.RuntimeState) -> dict[str, Any]:
    sid_fail = f"ac19-fail-{uuid.uuid4().hex[:6]}"
    wid_fail = seed_workflow(
        root,
        sid_fail,
        [("user", "请输出可训练要点"), ("assistant", "可以先看错误回滚。")],
    )
    original_snapshot_wf = wf.build_analysis_snapshot_with_context
    original_snapshot_exec = tw_exec.build_analysis_snapshot_with_context
    forced_failure = lambda _root, _sid: (_ for _ in ()).throw(  # type: ignore[assignment]
        RuntimeError("forced_failure_for_ac19")
    )
    try:
        wf.build_analysis_snapshot_with_context = forced_failure  # type: ignore[assignment]
        tw_exec.build_analysis_snapshot_with_context = forced_failure  # type: ignore[assignment]
        wf.run_analysis_worker(cfg, state, wid_fail)
    finally:
        wf.build_analysis_snapshot_with_context = original_snapshot_wf  # type: ignore[assignment]
        tw_exec.build_analysis_snapshot_with_context = original_snapshot_exec  # type: ignore[assignment]
    fail_rows = dialogue_rows(root, sid_fail)
    assert_true(
        all(str(item.get("analysis_state")) == wf.ANALYSIS_STATE_PENDING for item in fail_rows),
        "normal failure must rollback messages to pending",
    )

    sid_prev = f"ac19-prev-{uuid.uuid4().hex[:6]}"
    wid_prev = seed_workflow(
        root,
        sid_prev,
        [("assistant", "这是截断对话的后半段"), ("user", "我补充背景信息")],
    )
    wf.run_analysis_worker(cfg, state, wid_prev)
    prev_rows = dialogue_rows(root, sid_prev)
    assert_true(
        all(str(item.get("analysis_state")) == wf.ANALYSIS_STATE_DONE for item in prev_rows),
        "missing_previous_context should mark done",
    )
    assert_true(
        all(str(item.get("analysis_reason")) == "missing_previous_context" for item in prev_rows),
        "missing_previous_context reason should be written",
    )

    sid_next = f"ac19-next-{uuid.uuid4().hex[:6]}"
    wid_next = seed_workflow(root, sid_next, [("user", "请继续，但还没收到回复")])
    wf.run_analysis_worker(cfg, state, wid_next)
    next_rows = dialogue_rows(root, sid_next)
    assert_true(
        all(str(item.get("analysis_state")) == wf.ANALYSIS_STATE_PENDING for item in next_rows),
        "missing_next_context should keep pending",
    )
    next_run = wf.latest_analysis_run(root, wid_next) or {}
    assert_true(
        str(next_run.get("no_value_reason") or "") == "missing_next_context",
        "missing_next_context run reason mismatch",
    )

    return {
        "normal_failure_workflow_id": wid_fail,
        "normal_failure_states": [item.get("analysis_state") for item in fail_rows],
        "missing_previous_workflow_id": wid_prev,
        "missing_previous_reasons": [item.get("analysis_reason") for item in prev_rows],
        "missing_next_workflow_id": wid_next,
        "missing_next_states": [item.get("analysis_state") for item in next_rows],
        "missing_next_run_status": next_run.get("status"),
        "missing_next_no_value_reason": next_run.get("no_value_reason"),
    }


def run_ac20(root: Path) -> dict[str, Any]:
    sid = f"ac20-s-{uuid.uuid4().hex[:6]}"
    wid = seed_workflow(root, sid, [("user", "删除测试消息1"), ("assistant", "删除测试消息2")])
    rows_before = dialogue_rows(root, sid)
    msg_id = int(rows_before[0]["message_id"])
    result = wf.delete_session_message_with_gate(root, sid, msg_id, operator="ac-tester")
    rows_after = dialogue_rows(root, sid)
    audit = latest_delete_audit(root, sid, msg_id)
    assert_true(len(rows_after) == len(rows_before) - 1, "message should be removed from dialogue")
    assert_true(str(audit.get("status") or "") == "success", "audit status should be success")
    assert_true(str(audit.get("reason_code") or "") == "message_deleted", "audit reason code mismatch")
    return {
        "workflow_id": wid,
        "deleted_message_id": msg_id,
        "before_count": len(rows_before),
        "after_count": len(rows_after),
        "delete_result": result,
        "audit": audit,
    }


def run_ac21(root: Path, cfg: wf.AppConfig, state: wf.RuntimeState) -> dict[str, Any]:
    sid = f"ac21-s-{uuid.uuid4().hex[:6]}"
    wid = seed_workflow(root, sid, [("user", "请生成可训练计划"), ("assistant", "已分析输入内容")])
    wf.run_analysis_worker(cfg, state, wid)
    plan_data = wf.generate_training_workflow_plan(cfg, wid)
    plan_count = len(plan_data.get("plan") or [])
    assert_true(plan_count > 0, "ac21 requires session with plan items > 0")
    target_msg = int(dialogue_rows(root, sid)[0]["message_id"])

    blocked_code = ""
    try:
        wf.delete_session_message_with_gate(root, sid, target_msg, operator="ac-tester")
    except wf.WorkflowGateError as exc:
        blocked_code = str(exc.code)
    assert_true(blocked_code == "conversation_locked_by_training_plan", "delete should be blocked by plan lock")

    remains = dialogue_rows(root, sid)
    assert_true(any(int(item["message_id"]) == target_msg for item in remains), "message must remain unchanged")
    audit = latest_delete_audit(root, sid, target_msg)
    assert_true(str(audit.get("status") or "") == "rejected", "blocked delete audit status mismatch")
    assert_true(
        str(audit.get("reason_code") or "") == "conversation_locked_by_training_plan",
        "blocked delete audit reason mismatch",
    )
    return {
        "workflow_id": wid,
        "plan_count": plan_count,
        "blocked_code": blocked_code,
        "target_message_id": target_msg,
        "audit": audit,
    }


def run_ac22(repo_root: Path, sandbox_root: Path) -> dict[str, Any]:
    checker = repo_root / "scripts" / "quality" / "check_crud_gate.py"
    valid_file = sandbox_root / "crud-valid.json"
    valid_file.write_text(
        json.dumps(
            {
                "features": [
                    {
                        "id": "FR-VALID-01",
                        "name": "valid sample",
                        "crud": {
                            "create": {"mode": "required"},
                            "read": {"mode": "required"},
                            "update": {"mode": "optional"},
                            "delete": {
                                "mode": "disabled",
                                "reason": "audited_only",
                                "trigger": "manual_approval",
                                "error_code": "delete_disabled",
                                "user_message": "删除受限，请走审批流程",
                            },
                        },
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    valid_proc = subprocess.run(
        [sys.executable, str(checker), "--file", str(valid_file)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert_true(valid_proc.returncode == 0, "valid CRUD declaration must pass")

    invalid_file = sandbox_root / "crud-invalid.json"
    invalid_file.write_text(
        json.dumps(
            {
                "features": [
                    {
                        "id": "FR-X",
                        "name": "invalid sample",
                        "crud": {
                            "create": {"mode": "required"}
                        },
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    invalid_proc = subprocess.run(
        [sys.executable, str(checker), "--file", str(invalid_file)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert_true(invalid_proc.returncode != 0, "missing CRUD declaration should fail gate")
    return {
        "valid_file": valid_file.as_posix(),
        "valid_return_code": valid_proc.returncode,
        "valid_stdout": valid_proc.stdout.strip(),
        "invalid_file": invalid_file.as_posix(),
        "invalid_return_code": invalid_proc.returncode,
        "invalid_stdout": invalid_proc.stdout.strip(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AC-16 ~ AC-22 acceptance checks.")
    parser.add_argument("--root", default=".", help="repository root")
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    run_id = now_key()
    sandbox_root = init_sandbox(repo_root, run_id)
    cfg = make_cfg(sandbox_root)
    state = wf.RuntimeState()

    checks: list[tuple[str, Any]] = [
        ("AC-16", lambda: run_ac16(sandbox_root, cfg, state)),
        ("AC-17", lambda: run_ac17(sandbox_root, cfg, state)),
        ("AC-18", lambda: run_ac18(sandbox_root, cfg, state)),
        ("AC-19", lambda: run_ac19(sandbox_root, cfg, state)),
        ("AC-20", lambda: run_ac20(sandbox_root)),
        ("AC-21", lambda: run_ac21(sandbox_root, cfg, state)),
        ("AC-22", lambda: run_ac22(repo_root, sandbox_root)),
    ]

    results: list[dict[str, Any]] = []
    for ac_id, runner in checks:
        try:
            detail = runner()
            results.append({"ac_id": ac_id, "pass": True, "detail": detail})
        except Exception as exc:
            results.append({"ac_id": ac_id, "pass": False, "detail": {"error": str(exc)}})

    all_pass = all(bool(item.get("pass")) for item in results)
    out_dir = (repo_root / ".test" / "runs").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"ac16-ac22-acceptance-{run_id}.json"
    out_md = out_dir / f"ac16-ac22-acceptance-{run_id}.md"
    payload = {
        "ok": all_pass,
        "run_id": run_id,
        "generated_at": datetime.now(BEIJING_TZ).isoformat(),
        "sandbox_root": sandbox_root.as_posix(),
        "db_path": (sandbox_root / "state" / "workflow.db").as_posix(),
        "results": results,
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# AC-16 ~ AC-22 Acceptance - {run_id}",
        "",
        f"- ok: {all_pass}",
        f"- sandbox_root: {sandbox_root.as_posix()}",
        f"- db_path: {(sandbox_root / 'state' / 'workflow.db').as_posix()}",
        f"- json_report: {out_json.as_posix()}",
        "",
        "| AC | Result | Detail |",
        "|---|---|---|",
    ]
    for item in results:
        ac_id = str(item.get("ac_id") or "")
        status = "pass" if item.get("pass") else "fail"
        detail = json.dumps(item.get("detail") or {}, ensure_ascii=False)
        lines.append(f"| {ac_id} | {status} | `{detail[:240]}` |")
    lines.append("")
    out_md.write_text("\n".join(lines), encoding="utf-8")

    print(out_json.as_posix())
    print(out_md.as_posix())
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
