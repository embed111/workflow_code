from __future__ import annotations

from ..server.services.work_record_store import (
    get_training_task_record,
    list_analysis_records,
    upsert_training_task_record,
)
from ..server.services.work_record_store_system import unique_system_run_path


def bind_runtime_symbols(symbols: dict[str, object]) -> None:
    globals().update(symbols)


def _safe_trainer_token(value: str, limit: int = 80) -> str:
    text = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in str(value))
    text = text.strip("-")
    return text[:limit] or f"task-{uuid.uuid4().hex[:8]}"

def resolve_trainer_root() -> Path:
    env_path = (os.getenv("WORKFLOW_TRAINER_ROOT") or "").strip()
    base = Path(env_path) if env_path else DEFAULT_TRAINER_ROOT
    return base.resolve()

def trainer_task_card_path(trainer_root: Path, training_id: str, attempt: int) -> Path:
    task_key = _safe_trainer_token(f"{training_id}-a{attempt}", 120)
    return trainer_root / "queue" / "inbox" / f"{task_key}.yaml"

def trainer_report_candidates(trainer_root: Path, training_id: str, attempt: int) -> list[Path]:
    reports_dir = trainer_root / "reports"
    safe_tid = _safe_trainer_token(training_id, 120)
    names = [
        reports_dir / f"{safe_tid}-report.md",
        reports_dir / f"{safe_tid}-a{attempt}-report.md",
    ]
    if reports_dir.exists():
        names.extend(sorted(reports_dir.glob(f"*{safe_tid}*report*.md")))
    dedup: list[Path] = []
    seen: set[str] = set()
    for item in names:
        key = str(item.resolve()) if item.exists() else str(item)
        if key in seen:
            continue
        seen.add(key)
        dedup.append(item)
    return dedup

def find_existing_trainer_report(trainer_root: Path, training_id: str, attempt: int) -> Path | None:
    for candidate in trainer_report_candidates(trainer_root, training_id, attempt):
        if candidate.exists():
            return candidate
    return None

def write_trainer_task_card(
    trainer_root: Path,
    training_id: str,
    analysis_id: str,
    session_id: str,
    attempt: int,
    created_at: datetime,
) -> Path:
    queue_inbox = trainer_root / "queue" / "inbox"
    queue_inbox.mkdir(parents=True, exist_ok=True)
    task_file = trainer_task_card_path(trainer_root, training_id, attempt)
    if task_file.exists():
        return task_file
    task_id_text = _safe_trainer_token(f"{training_id}-a{attempt}", 120)
    content = "\n".join(
        [
            f'task_id: "{task_id_text}"',
            f'title: "workflow training task {training_id}"',
            'source: "workflow_runtime"',
            f'created_at: "{created_at.isoformat(timespec="seconds")}"',
            'priority: "P2"',
            'risk_level: "medium"',
            'risk_type: "workflow_training"',
            'target_role: "analyst"',
            'dispatch_mode: "manual"',
            'execution_route: "auto_by_risk"',
            "acceptance:",
            f'  - "trace to training_id={training_id}"',
            f'  - "trace to analysis_id={analysis_id}"',
            f'notes: "session_id={session_id}; attempt={attempt}"',
        ]
    )
    task_file.write_text(content + "\n", encoding="utf-8")
    return task_file

def write_training_dispatch_log(
    root: Path,
    ts: datetime,
    training_id: str,
    analysis_id: str,
    session_id: str,
    attempt: int,
    trainer_root: Path,
    task_card: Path,
    report_path: Path | None,
    status: str,
    note: str,
) -> str:
    path = unique_system_run_path(
        root,
        f"train-dispatch-{_safe_trainer_token(training_id, 80)}-a{attempt}",
    )
    content = "\n".join(
        [
            f"# Training Dispatch - {training_id}",
            "",
            f"- timestamp: {timestamp_key(ts)}",
            f"- training_id: {training_id}",
            f"- analysis_id: {analysis_id}",
            f"- session_id: {session_id}",
            f"- attempt: {attempt}",
            f"- trainer_root: {trainer_root.as_posix()}",
            f"- task_card: {task_card.as_posix()}",
            f"- report_path: {report_path.as_posix() if report_path else 'none'}",
            f"- status: {status}",
            f"- note: {note}",
        ]
    )
    path.write_text(content + "\n", encoding="utf-8")
    return relative_to_root(root, path)

def run_trainer_once(
    root: Path,
    ts: datetime,
    training_id: str,
    analysis_id: str,
    session_id: str,
    attempt: int,
) -> tuple[str, str, str]:
    trainer_root = resolve_trainer_root()
    if not trainer_root.exists():
        raise RuntimeError(f"trainer_root_not_found: {trainer_root}")
    if not (trainer_root / "queue").exists():
        raise RuntimeError(f"trainer_queue_missing: {trainer_root / 'queue'}")
    if not (trainer_root / "reports").exists():
        raise RuntimeError(f"trainer_reports_missing: {trainer_root / 'reports'}")

    task_card = write_trainer_task_card(
        trainer_root=trainer_root,
        training_id=training_id,
        analysis_id=analysis_id,
        session_id=session_id,
        attempt=attempt,
        created_at=ts,
    )
    poll_s = max(0, int(os.getenv("WORKFLOW_TRAINER_POLL_SECONDS") or "2"))
    deadline = time.time() + poll_s
    report_path = find_existing_trainer_report(trainer_root, training_id, attempt)
    while report_path is None and time.time() < deadline:
        time.sleep(1)
        report_path = find_existing_trainer_report(trainer_root, training_id, attempt)

    if report_path is not None:
        report_ref = report_path.as_posix()
        summary = (
            f"training_id={training_id} done at attempt={attempt}; "
            f"trainer_report={report_ref}"
        )
        dispatch_ref = write_training_dispatch_log(
            root=root,
            ts=ts,
            training_id=training_id,
            analysis_id=analysis_id,
            session_id=session_id,
            attempt=attempt,
            trainer_root=trainer_root,
            task_card=task_card,
            report_path=report_path,
            status="done",
            note="report found in trainer workspace",
        )
        summary = f"{summary}; dispatch_log={dispatch_ref}"
        return "done", report_ref, summary

    dispatch_ref = write_training_dispatch_log(
        root=root,
        ts=ts,
        training_id=training_id,
        analysis_id=analysis_id,
        session_id=session_id,
        attempt=attempt,
        trainer_root=trainer_root,
        task_card=task_card,
        report_path=None,
        status="pending",
        note="task queued; trainer report not ready",
    )
    summary = (
        f"training_id={training_id} queued at attempt={attempt}; "
        "waiting for trainer report"
    )
    return "pending", dispatch_ref, summary

def run_training_batch(
    root: Path,
    limit: int,
    max_retries: int,
    focus: str,
    actor: str = "trainer",
) -> tuple[int, int]:
    processed = 0
    done = 0
    analyses = sorted(
        list_analysis_records(root),
        key=lambda item: str(item.get("created_at") or ""),
    )
    eligible: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for analysis in analyses:
        analysis_id = str(analysis.get("analysis_id") or "")
        if not analysis_id:
            continue
        training = get_training_task_record(root, analysis_id) or {}
        status = str(training.get("status") or "")
        attempts = int(training.get("attempts") or 0)
        if status not in {"pending", "failed"} or attempts >= max(1, max_retries):
            continue
        eligible.append((analysis, training))
    for analysis, training in eligible[: max(1, limit)]:
        analysis_id = str(analysis.get("analysis_id") or "")
        session_id = str(analysis.get("session_id") or "")
        training_id = str(training.get("training_id") or f"trn-{analysis_id}")
        ts = now_local()
        current_attempts = int(training.get("attempts") or 0) + 1
        upsert_training_task_record(
            root,
            analysis_id,
            {
                **training,
                "training_id": training_id,
                "analysis_id": analysis_id,
                "status": "running",
                "attempts": current_attempts,
                "created_at": str(training.get("created_at") or ts.isoformat(timespec="seconds")),
                "updated_at": ts.isoformat(timespec="seconds"),
            },
        )
        try:
            status, trainer_ref, summary = run_trainer_once(
                root=root,
                ts=ts,
                training_id=training_id,
                analysis_id=analysis_id,
                session_id=session_id,
                attempt=current_attempts,
            )
            if status == "done":
                upsert_training_task_record(
                    root,
                    analysis_id,
                    {
                        **(get_training_task_record(root, analysis_id) or {}),
                        "training_id": training_id,
                        "analysis_id": analysis_id,
                        "status": "done",
                        "result_summary": summary,
                        "trainer_run_ref": trainer_ref,
                        "last_error": "",
                        "updated_at": ts.isoformat(timespec="seconds"),
                    },
                )
                persist_event(
                    root,
                    event_file(root, ts),
                    {
                        "event_id": generate_event_id(ts),
                        "timestamp": ts.isoformat(timespec="seconds"),
                        "session_id": session_id,
                        "actor": actor,
                        "stage": "train",
                        "action": "run_training",
                        "status": "success",
                        "latency_ms": 0,
                        "task_id": training_id,
                        "reason_tags": [],
                        "ref": trainer_ref,
                    },
                )
                done += 1
            else:
                next_status = "pending" if current_attempts < max(1, max_retries) else "failed"
                upsert_training_task_record(
                    root,
                    analysis_id,
                    {
                        **(get_training_task_record(root, analysis_id) or {}),
                        "training_id": training_id,
                        "analysis_id": analysis_id,
                        "status": next_status,
                        "result_summary": summary,
                        "trainer_run_ref": trainer_ref,
                        "last_error": "TrainerPending: waiting for trainer report",
                        "updated_at": ts.isoformat(timespec="seconds"),
                    },
                )
                persist_event(
                    root,
                    event_file(root, ts),
                    {
                        "event_id": generate_event_id(ts),
                        "timestamp": ts.isoformat(timespec="seconds"),
                        "session_id": session_id,
                        "actor": actor,
                        "stage": "train",
                        "action": "run_training",
                        "status": "failed",
                        "latency_ms": 0,
                        "task_id": training_id,
                        "reason_tags": ["trainer_pending"],
                        "ref": trainer_ref,
                    },
                )
        except Exception as exc:
            next_status = "pending" if current_attempts < max(1, max_retries) else "failed"
            err = f"{exc.__class__.__name__}: {exc}"
            upsert_training_task_record(
                root,
                analysis_id,
                {
                    **(get_training_task_record(root, analysis_id) or {}),
                    "training_id": training_id,
                    "analysis_id": analysis_id,
                    "status": next_status,
                    "last_error": err,
                    "updated_at": ts.isoformat(timespec="seconds"),
                },
            )
            persist_event(
                root,
                event_file(root, ts),
                {
                    "event_id": generate_event_id(ts),
                    "timestamp": ts.isoformat(timespec="seconds"),
                    "session_id": session_id,
                    "actor": actor,
                    "stage": "train",
                    "action": "run_training",
                    "status": "failed",
                    "latency_ms": 0,
                    "task_id": training_id,
                    "reason_tags": [exc.__class__.__name__],
                    "ref": "",
                },
            )
        processed += 1

    refresh_outputs(root, focus=focus)
    return processed, done
