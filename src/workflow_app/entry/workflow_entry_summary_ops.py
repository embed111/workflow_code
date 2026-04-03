from __future__ import annotations

from ..server.services.work_record_store import daily_summary_path, session_snapshot_path


def bind_runtime_symbols(symbols: dict[str, object]) -> None:
    globals().update(symbols)


def load_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            text = line.strip()
            if not text:
                continue
            try:
                events.append(json.loads(text))
            except json.JSONDecodeError:
                # Skip malformed rows without failing the chat entrypoint.
                continue
    return events

def compute_metrics(
    events: list[dict[str, Any]],
    pending_analysis: int,
    pending_training: int,
    latest_decision: str,
    latest_training: str,
) -> Metrics:
    sessions = {str(item.get("session_id")) for item in events if item.get("session_id")}
    failures = [item for item in events if item.get("status") == "failed"]
    reason_counter: Counter[str] = Counter()
    for item in failures:
        tags = item.get("reason_tags") or ["unknown"]
        for tag in tags:
            reason_counter[str(tag)] += 1

    latest_switch = ""
    for item in reversed(events):
        if (
            item.get("stage") == "switch"
            and item.get("action") == "ab_switch"
            and item.get("status") == "success"
        ):
            latest_switch = str(item.get("timestamp", ""))
            break

    return Metrics(
        new_sessions=len(sessions),
        pending_analysis=pending_analysis,
        pending_training=pending_training,
        ab_switch_count=sum(
            1
            for item in events
            if item.get("stage") == "switch"
            and item.get("action") == "ab_switch"
            and item.get("status") == "success"
        ),
        critical_failures=len(failures),
        top_failure_tags=reason_counter.most_common(3),
        total_events=len(events),
        latest_switch_at=latest_switch,
        latest_decision=latest_decision,
        latest_training=latest_training,
    )

def write_daily_summary(
    root: Path,
    ts: datetime,
    metrics: Metrics,
    latest_session_id: str,
) -> None:
    summary_path = daily_summary_path(root)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    tags = ", ".join(f"{tag}({count})" for tag, count in metrics.top_failure_tags) or "none"
    latest_switch = metrics.latest_switch_at or "none"

    if metrics.top_failure_tags:
        top_tag = metrics.top_failure_tags[0][0]
        tomorrow_priority = f"Fix top failure tag first: {top_tag}"
    else:
        tomorrow_priority = "No critical failures today. Continue workflow baseline scope."

    content = "\n".join(
        [
            f"# Daily Summary - {ts.strftime('%Y-%m-%d')}",
            "",
            f"- last_update: {timestamp_key(ts)}",
            "- source: scripts/workflow_entry_cli.py",
            "",
            "## Must-Track (Top 5)",
            f"1. New sessions total: {metrics.new_sessions}",
            (
                "2. Pending tasks: "
                f"analysis={metrics.pending_analysis}, training={metrics.pending_training}"
            ),
            (
                "3. A/B switch record: "
                f"switch_count={metrics.ab_switch_count}, latest_switch_at={latest_switch}"
            ),
            f"4. Top3 failure reason tags: {tags}",
            f"5. Tomorrow first priority: {tomorrow_priority}",
            "",
            "## Extra",
            f"- total_events_today: {metrics.total_events}",
            f"- latest_session_id: {latest_session_id}",
            f"- latest_decision: {metrics.latest_decision}",
            f"- latest_training: {metrics.latest_training}",
        ]
    )
    summary_path.write_text(content + "\n", encoding="utf-8")

def write_session_snapshot(
    root: Path,
    ts: datetime,
    metrics: Metrics,
    focus: str,
    latest_session_id: str,
) -> None:
    snapshot_path = session_snapshot_path(root)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    events_path = relative_to_root(root, event_file(root, ts))

    blocker = "none"
    if metrics.top_failure_tags:
        blocker = f"failure tag: {metrics.top_failure_tags[0][0]}"

    content = "\n".join(
        [
            "# Session Snapshot",
            "",
            f"- last_update: {timestamp_key(ts)}",
            "- current_track: runtime-baseline",
            f"- current_focus: {focus}",
            "",
            "## Today",
            (
                "1. Completed: chat entry active; event logs, analysis task auto-creation, "
                "decision + training execution, minimal web chat page, and per-round markdown "
                "snapshots are auto-updated."
            ),
            (
                "2. <span style=\"color:red\">Not completed: Gate1 still pending workflow-vs-CLI "
                "latency benchmark closure and full-page replay evidence, Gate2 still pending real "
                "trainer report callback, Gate3 still needs sustained daily runs proving stable "
                "`gap_after=0`.</span>"
            ),
            f"3. Largest blocker: {blocker}",
            "",
            "## Key Metrics",
            f"1. new_sessions: {metrics.new_sessions}",
            f"2. pending_analysis: {metrics.pending_analysis}",
            f"3. pending_training: {metrics.pending_training}",
            f"4. ab_switch_count: {metrics.ab_switch_count}",
            f"5. critical_failures: {metrics.critical_failures}",
            f"6. latest_decision: {metrics.latest_decision}",
            f"7. latest_training: {metrics.latest_training}",
            "",
            "## Next Start",
            f"1. First log to check: {events_path}",
            "2. First action: continue chat rounds and keep logs complete.",
            "",
            "## Session",
            f"- latest_session_id: {latest_session_id}",
        ]
    )
    snapshot_path.write_text(content + "\n", encoding="utf-8")
