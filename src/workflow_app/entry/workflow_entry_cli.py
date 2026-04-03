#!/usr/bin/env python3
"""Workflow chat entrypoint backed by the external work-record store."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from . import workflow_entry_summary_ops as _summary_ops
from . import workflow_entry_training_ops as _training_ops
from ..server.infra.db.migrations import ensure_tables as ensure_runtime_tables
from ..server.services.work_record_store import (
    analysis_record_path,
    append_session_message_record,
    create_or_load_session_record,
    ensure_store,
    get_training_task_record,
    list_analysis_records,
    sync_analysis_records_from_sessions,
    upsert_analysis_record,
    upsert_training_task_record,
)
from ..server.services.work_record_store_migration import migrate_legacy_local_work_records
from ..server.services.work_record_store_system import unique_system_run_path, workflow_events_path


DEFAULT_FOCUS = "Workflow baseline: minimal web chat page + closed loop ops"
DEFAULT_TRAINER_ROOT = Path(
    os.getenv("WORKFLOW_TRAINER_ROOT") or "C:/work/agents/trainer/trainer"
)


@dataclass
class Metrics:
    new_sessions: int
    pending_analysis: int
    pending_training: int
    ab_switch_count: int
    critical_failures: int
    top_failure_tags: list[tuple[str, int]]
    total_events: int
    latest_switch_at: str
    latest_decision: str
    latest_training: str


def now_local() -> datetime:
    return datetime.now().astimezone()


def ensure_layout(root: Path) -> None:
    required_dirs = ["state", "incidents", "metrics"]
    for rel in required_dirs:
        (root / rel).mkdir(parents=True, exist_ok=True)
    ensure_store(root)


def db_file(root: Path) -> Path:
    return root / "state" / "workflow.db"


def _ensure_columns(
    conn: sqlite3.Connection, table: str, required: list[tuple[str, str]]
) -> None:
    existing = {
        row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    for col_name, col_def in required:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")


def init_db(root: Path) -> None:
    ensure_runtime_tables(root)


def date_key(ts: datetime) -> str:
    return ts.strftime("%Y%m%d")


def timestamp_key(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%d %H:%M:%S%z")


def event_file(root: Path, ts: datetime) -> Path:
    return workflow_events_path(root)


def run_file(root: Path, ts: datetime) -> Path:
    return unique_system_run_path(root, f"cli-run-{date_key(ts)}-{ts.strftime('%H%M%S')}")


def relative_to_root(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def generate_event_id(ts: datetime) -> str:
    return f"evt-{date_key(ts)}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"


def generate_task_id(ts: datetime) -> str:
    return f"REQ-{date_key(ts)}-{uuid.uuid4().hex[:6]}"


def append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def persist_event_to_db(root: Path, event: dict[str, Any]) -> None:
    _ = (root, event)


def _event_reason_tags(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(item) for item in raw]
    return []


def _normalize_event(raw: dict[str, Any], fallback_ref: str = "") -> dict[str, Any]:
    ts = str(raw.get("timestamp") or now_local().isoformat(timespec="seconds"))
    session_id = str(raw.get("session_id") or "")
    event_id = str(raw.get("event_id") or "")
    if not event_id:
        event_id = generate_event_id(now_local())
    return {
        "event_id": event_id,
        "timestamp": ts,
        "session_id": session_id,
        "actor": str(raw.get("actor") or "workflow"),
        "stage": str(raw.get("stage") or "chat"),
        "action": str(raw.get("action") or "send_message"),
        "status": str(raw.get("status") or "success"),
        "latency_ms": int(raw.get("latency_ms") or 0),
        "task_id": str(raw.get("task_id") or ""),
        "reason_tags": _event_reason_tags(raw.get("reason_tags")),
        "ref": str(raw.get("ref") or fallback_ref or ""),
    }


def _insert_event_row(conn: sqlite3.Connection, event: dict[str, Any]) -> int:
    _ = (conn, event)
    return 0


def backfill_events_from_jsonl(root: Path) -> tuple[int, int, int, int]:
    migration = migrate_legacy_local_work_records(root)
    created_analysis = sync_analysis_tasks(root)
    scanned = int(migration.get("migrated_sessions", 0)) + int(migration.get("migrated_runs", 0))
    inserted = int(migration.get("migrated_analyses", 0))
    malformed = 0
    return scanned, inserted, malformed, created_analysis


def persist_event(root: Path, path: Path, event: dict[str, Any]) -> None:
    append_event(path, event)
    persist_event_to_db(root, event)


def sync_analysis_tasks(root: Path) -> int:
    return sync_analysis_records_from_sessions(root)


def get_pending_counts(root: Path) -> tuple[int, int]:
    pending_analysis = 0
    pending_training = 0
    for analysis in list_analysis_records(root):
        if str(analysis.get("status") or "") == "pending":
            pending_analysis += 1
        training = get_training_task_record(root, str(analysis.get("analysis_id") or "")) or {}
        if str(training.get("status") or "") == "pending":
            pending_training += 1
    return pending_analysis, pending_training


def get_latest_results(root: Path) -> tuple[str, str]:
    analyses = sorted(
        list_analysis_records(root),
        key=lambda item: str(item.get("updated_at") or ""),
        reverse=True,
    )
    latest_decision_row = next(
        (item for item in analyses if str(item.get("decision") or "").strip()),
        None,
    )
    training_rows: list[dict[str, Any]] = []
    for analysis in analyses:
        training = get_training_task_record(root, str(analysis.get("analysis_id") or ""))
        if training and str(training.get("status") or "") in {"done", "failed"}:
            training_rows.append(dict(training))
    training_rows.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    latest_training_row = training_rows[0] if training_rows else None
    latest_decision = (
        f"{latest_decision_row.get('analysis_id')}:{latest_decision_row.get('decision')}({latest_decision_row.get('status')})"
        if latest_decision_row
        else "none"
    )
    latest_training = (
        f"{latest_training_row.get('training_id')}:{latest_training_row.get('status')}"
        if latest_training_row
        else "none"
    )
    return latest_decision, latest_training


def latest_session_id_from_events(events: list[dict[str, Any]]) -> str:
    for item in reversed(events):
        sid = str(item.get("session_id", "")).strip()
        if sid:
            return sid
    return ""


def refresh_outputs(root: Path, focus: str, preferred_session_id: str = "") -> None:
    ts = now_local()
    events_path = event_file(root, ts)
    all_today_events = [
        item
        for item in load_events(events_path)
        if str(item.get("timestamp") or "").startswith(ts.strftime("%Y-%m-%d"))
    ]
    pending_analysis, pending_training = get_pending_counts(root)
    latest_decision, latest_training = get_latest_results(root)
    metrics = compute_metrics(
        all_today_events,
        pending_analysis=pending_analysis,
        pending_training=pending_training,
        latest_decision=latest_decision,
        latest_training=latest_training,
    )
    latest_session_id = preferred_session_id or latest_session_id_from_events(
        all_today_events
    )
    write_daily_summary(root, ts, metrics, latest_session_id=latest_session_id)
    write_session_snapshot(
        root, ts, metrics, focus=focus, latest_session_id=latest_session_id
    )


def append_decision_markdown(
    root: Path,
    ts: datetime,
    analysis_id: str,
    session_id: str,
    decision: str,
    reason: str,
) -> str:
    _ = (ts, session_id, decision, reason)
    return analysis_record_path(root, analysis_id).as_posix()


def decision_to_status(decision: str) -> str:
    mapping = {
        "train": "decided_train",
        "skip": "decided_skip",
        "need_info": "blocked",
    }
    return mapping[decision]


def create_training_id(analysis_id: str) -> str:
    return f"trn-{analysis_id}"


def run_decision_batch(
    root: Path,
    decision: str,
    reason: str,
    limit: int,
    focus: str,
    actor: str = "workflow",
) -> tuple[int, int]:
    processed = 0
    created_training = 0
    pending_rows = [
        item
        for item in sorted(list_analysis_records(root), key=lambda row: str(row.get("created_at") or ""))
        if str(item.get("status") or "") == "pending"
    ][: max(1, limit)]
    for analysis in pending_rows:
        analysis_id = str(analysis.get("analysis_id") or "")
        session_id = str(analysis.get("session_id") or "")
        ts = now_local()
        status = decision_to_status(decision)
        upsert_analysis_record(
            root,
            analysis_id,
            {
                **analysis,
                "analysis_id": analysis_id,
                "session_id": session_id,
                "status": status,
                "decision": decision,
                "decision_reason": reason,
                "updated_at": ts.isoformat(timespec="seconds"),
            },
        )
        if decision == "train":
            training = get_training_task_record(root, analysis_id) or {}
            if not training:
                created_training += 1
            upsert_training_task_record(
                root,
                analysis_id,
                {
                    **training,
                    "training_id": str(training.get("training_id") or create_training_id(analysis_id)),
                    "analysis_id": analysis_id,
                    "status": "pending",
                    "attempts": int(training.get("attempts") or 0),
                    "created_at": str(training.get("created_at") or ts.isoformat(timespec="seconds")),
                    "updated_at": ts.isoformat(timespec="seconds"),
                },
            )
        ref = append_decision_markdown(
            root,
            ts,
            analysis_id=analysis_id,
            session_id=session_id,
            decision=decision,
            reason=reason,
        )
        event = {
            "event_id": generate_event_id(ts),
            "timestamp": ts.isoformat(timespec="seconds"),
            "session_id": session_id,
            "actor": actor,
            "stage": "analyze",
            "action": "decision",
            "status": "success",
            "latency_ms": 0,
            "task_id": analysis_id,
            "reason_tags": [decision],
            "ref": ref,
        }
        persist_event(root, event_file(root, ts), event)
        processed += 1

    refresh_outputs(root, focus=focus)
    return processed, created_training


# Delegated to extracted modules to keep this entrypoint thin.
_safe_trainer_token = _training_ops._safe_trainer_token
resolve_trainer_root = _training_ops.resolve_trainer_root
trainer_task_card_path = _training_ops.trainer_task_card_path
trainer_report_candidates = _training_ops.trainer_report_candidates
find_existing_trainer_report = _training_ops.find_existing_trainer_report
write_trainer_task_card = _training_ops.write_trainer_task_card
write_training_dispatch_log = _training_ops.write_training_dispatch_log
run_trainer_once = _training_ops.run_trainer_once
run_training_batch = _training_ops.run_training_batch

load_events = _summary_ops.load_events
compute_metrics = _summary_ops.compute_metrics
write_daily_summary = _summary_ops.write_daily_summary
write_session_snapshot = _summary_ops.write_session_snapshot


def mock_agent_reply(agent: str, message: str) -> str:
    return f"[{agent}] received: {message}"


def append_run_round(
    run_path: Path,
    ts: datetime,
    round_index: int,
    user_message: str,
    agent_reply: str,
) -> None:
    with run_path.open("a", encoding="utf-8") as fh:
        fh.write(f"\n## Round {round_index} - {timestamp_key(ts)}\n")
        fh.write(f"- user: {user_message}\n")
        fh.write(f"- agent: {agent_reply}\n")


def process_round(
    root: Path,
    agent: str,
    session_id: str,
    user_message: str,
    focus: str,
    run_path: Path,
    round_index: int,
) -> None:
    round_ts = now_local()
    start = time.perf_counter()
    events_path = event_file(root, round_ts)
    ref_path = run_path.as_posix()
    task_id = generate_task_id(round_ts)
    create_or_load_session_record(
        root,
        {
            "session_id": session_id,
            "agent_name": agent,
            "agents_hash": agent[:12],
            "agents_loaded_at": round_ts.isoformat(timespec="seconds"),
            "agents_path": "",
            "agents_version": agent[:12],
            "agent_search_root": root.as_posix(),
            "target_path": root.as_posix(),
            "status": "active",
            "created_at": round_ts.isoformat(timespec="seconds"),
        },
    )
    append_session_message_record(
        root,
        session_id,
        {
            "role": "user",
            "content": user_message,
            "created_at": round_ts.isoformat(timespec="seconds"),
            "analysis_state": "pending",
            "analysis_reason": "",
            "analysis_run_id": "",
            "analysis_updated_at": round_ts.isoformat(timespec="seconds"),
        },
    )

    user_event = {
        "event_id": generate_event_id(round_ts),
        "timestamp": round_ts.isoformat(timespec="seconds"),
        "session_id": session_id,
        "actor": "user",
        "stage": "chat",
        "action": "send_message",
        "status": "success",
        "latency_ms": 0,
        "task_id": task_id,
        "reason_tags": [],
        "ref": ref_path,
    }
    persist_event(root, events_path, user_event)

    try:
        reply = mock_agent_reply(agent, user_message)
        latency_ms = int((time.perf_counter() - start) * 1000)
        append_session_message_record(
            root,
            session_id,
            {
                "role": "assistant",
                "content": reply,
                "created_at": now_local().isoformat(timespec="seconds"),
                "analysis_state": "pending",
                "analysis_reason": "",
                "analysis_run_id": "",
                "analysis_updated_at": now_local().isoformat(timespec="seconds"),
            },
        )
        agent_event = {
            "event_id": generate_event_id(now_local()),
            "timestamp": now_local().isoformat(timespec="seconds"),
            "session_id": session_id,
            "actor": "agent",
            "stage": "chat",
            "action": "send_message",
            "status": "success",
            "latency_ms": latency_ms,
            "task_id": task_id,
            "reason_tags": [],
            "ref": ref_path,
        }
        persist_event(root, events_path, agent_event)
        append_run_round(run_path, round_ts, round_index, user_message, reply)
        print(f"{agent}> {reply}")
    except Exception as exc:  # pragma: no cover - defensive logging path
        latency_ms = int((time.perf_counter() - start) * 1000)
        failed_event = {
            "event_id": generate_event_id(now_local()),
            "timestamp": now_local().isoformat(timespec="seconds"),
            "session_id": session_id,
            "actor": "workflow",
            "stage": "chat",
            "action": "send_message",
            "status": "failed",
            "latency_ms": latency_ms,
            "task_id": task_id,
            "reason_tags": [exc.__class__.__name__],
            "ref": ref_path,
        }
        persist_event(root, events_path, failed_event)
        print(f"{agent}> failed to generate reply ({exc.__class__.__name__})")

    sync_analysis_tasks(root)
    refresh_outputs(root, focus=focus, preferred_session_id=session_id)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Workflow chat entrypoint with event logging, auto queueing, and summary/snapshot updates."
        )
    )
    parser.add_argument("--root", default=".runtime", help="Runtime root path.")
    parser.add_argument(
        "--mode",
        choices=["chat", "decide", "train", "status", "backfill"],
        default="chat",
        help="Execution mode.",
    )
    parser.add_argument(
        "--agent", default="agent", help="Target agent name for chat mode."
    )
    parser.add_argument(
        "--session-id", default="", help="Reuse an existing session id in chat mode."
    )
    parser.add_argument(
        "--focus",
        default=DEFAULT_FOCUS,
        help="Current focus written into the external work-record snapshot.",
    )
    parser.add_argument(
        "--message",
        default="",
        help="Run one non-interactive chat round then exit.",
    )
    parser.add_argument(
        "--decision",
        choices=["train", "skip", "need_info"],
        default="",
        help="Decision to apply for pending analysis tasks in decide mode.",
    )
    parser.add_argument(
        "--reason",
        default="batch decision",
        help="Decision reason used in decide mode.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum tasks processed in decide/train mode.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Maximum retries per training task in train mode.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(args.root).resolve()
    ensure_layout(root)
    init_db(root)

    if args.mode == "status":
        sync_analysis_tasks(root)
        refresh_outputs(root, focus=args.focus)
        pending_analysis, pending_training = get_pending_counts(root)
        print(
            f"status> pending_analysis={pending_analysis} pending_training={pending_training}"
        )
        return

    if args.mode == "backfill":
        scanned, inserted, malformed, created_analysis = backfill_events_from_jsonl(
            root
        )
        refresh_outputs(root, focus=args.focus)
        pending_analysis, pending_training = get_pending_counts(root)
        print(
            "backfill> "
            f"scanned={scanned} inserted={inserted} malformed={malformed} "
            f"created_analysis={created_analysis} "
            f"pending_analysis={pending_analysis} pending_training={pending_training}"
        )
        return

    if args.mode == "decide":
        if not args.decision:
            raise SystemExit("--decision is required when --mode=decide")
        sync_analysis_tasks(root)
        processed, created_training = run_decision_batch(
            root=root,
            decision=args.decision,
            reason=args.reason,
            limit=args.limit,
            focus=args.focus,
        )
        print(
            "decide> "
            f"processed={processed} decision={args.decision} "
            f"created_training={created_training}"
        )
        return

    if args.mode == "train":
        processed, done = run_training_batch(
            root=root,
            limit=args.limit,
            max_retries=max(1, args.max_retries),
            focus=args.focus,
        )
        print(f"train> processed={processed} done={done}")
        return

    current_ts = now_local()
    session_id = (
        args.session_id.strip() or f"sess-{date_key(current_ts)}-{uuid.uuid4().hex[:6]}"
    )
    run_path = run_file(root, current_ts)
    run_path.write_text(
        "\n".join(
            [
                f"# Run Log - {current_ts.strftime('%Y-%m-%d %H:%M:%S%z')}",
                "",
                f"- session_id: {session_id}",
                f"- agent: {args.agent}",
                f"- focus: {args.focus}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    if args.message:
        process_round(
            root=root,
            agent=args.agent,
            session_id=session_id,
            user_message=args.message,
            focus=args.focus,
            run_path=run_path,
            round_index=1,
        )
        return

    print(f"session_id={session_id}")
    print("Type /exit to end the session.")
    round_index = 0
    while True:
        try:
            message = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSession ended.")
            break

        if not message:
            continue
        if message.lower() in {"/exit", "exit", "quit"}:
            print("Session ended.")
            break

        round_index += 1
        process_round(
            root=root,
            agent=args.agent,
            session_id=session_id,
            user_message=message,
            focus=args.focus,
            run_path=run_path,
            round_index=round_index,
        )


def _bind_entry_helper_symbols() -> None:
    _training_ops.bind_runtime_symbols(globals())
    _summary_ops.bind_runtime_symbols(globals())


_bind_entry_helper_symbols()


if __name__ == "__main__":
    main()
