#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path


def _wait_for_trigger(schedule_service, root: Path, trigger_instance_id: str, timeout_seconds: float = 5.0) -> None:
    thread_key = schedule_service._schedule_trigger_thread_key(root, trigger_instance_id)
    deadline = time.time() + max(1.0, float(timeout_seconds))
    while time.time() < deadline:
        with schedule_service._SCHEDULE_TRIGGER_LOCK:
            thread = schedule_service._SCHEDULE_TRIGGER_THREADS.get(thread_key)
        if thread is None:
            return
        thread.join(timeout=0.1)
    raise TimeoutError(f"schedule trigger thread did not finish in time: {trigger_instance_id}")


def _load_active_schedule_nodes(root: Path, schedule_id: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    tasks_root = root / "artifacts-root" / "tasks"
    if not tasks_root.exists():
        return items
    for node_path in tasks_root.glob("*/*/*.json"):
        if node_path.parent.name != "nodes":
            continue
        try:
            payload = json.loads(node_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        if str(payload.get("source_schedule_id") or "").strip() != schedule_id:
            continue
        if str(payload.get("record_state") or "active").strip().lower() == "deleted":
            continue
        items.append(
            {
                "ticket_id": str(node_path.parents[1].name or "").strip(),
                "node_id": str(payload.get("node_id") or "").strip(),
                "trigger_instance_id": str(payload.get("trigger_instance_id") or "").strip(),
                "status": str(payload.get("status") or "").strip().lower(),
            }
        )
    return sorted(items, key=lambda item: (item["trigger_instance_id"], item["node_id"]))


def main() -> int:
    workspace_root = Path(__file__).resolve().parents[2]
    src_root = workspace_root / "src"
    if src_root.as_posix() not in sys.path:
        sys.path.insert(0, src_root.as_posix())

    from workflow_app.server.bootstrap import web_server_runtime  # noqa: F401
    from workflow_app.server.services import assignment_service, schedule_service

    root = workspace_root / ".test" / "runtime-schedule-pending-trigger-replaced"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    artifact_root = (root / "artifacts-root").resolve()
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "state" / "runtime-config.json").write_text(
        json.dumps(
            {
                "show_test_data": False,
                "agent_search_root": str(Path("C:/work/J-Agents").resolve()),
                "artifact_root": artifact_root.as_posix(),
                "task_artifact_root": artifact_root.as_posix(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    cfg = type("Cfg", (), {"root": root, "runtime_environment": "prod"})()

    original_schedule_load_agents = schedule_service._load_available_agents
    original_assignment_list_agents = assignment_service.list_available_agents
    original_request_dispatch = schedule_service._request_assignment_dispatch

    schedule_service._load_available_agents = lambda _cfg: [{"agent_id": "workflow", "agent_name": "workflow"}]
    assignment_service.list_available_agents = lambda _cfg, analyze_policy=False: [{"agent_id": "workflow", "agent_name": "workflow"}]
    schedule_service._request_assignment_dispatch = lambda _root, _ticket_id: {
        "dispatch_status": "requested",
        "dispatch_message": "assigned agent already has running node",
    }
    try:
        created = schedule_service.create_schedule(
            cfg,
            {
                "operator": "test",
                "schedule_name": "定时排队覆盖探针",
                "enabled": True,
                "assigned_agent_id": "workflow",
                "launch_summary": "verify newer schedule trigger replaces older pending trigger",
                "execution_checklist": "1) hit first trigger\n2) keep node pending\n3) hit second trigger\n4) first pending trigger should be superseded",
                "done_definition": "only the latest pending schedule node remains active",
                "priority": "P1",
                "expected_artifact": "continuous-improvement-report.md",
                "delivery_mode": "none",
                "rule_sets": {
                    "monthly": {"enabled": False},
                    "weekly": {"enabled": False},
                    "daily": {"enabled": False},
                    "once": {
                        "enabled": True,
                        "date_times_text": "\n".join(
                            [
                                "2026-04-10T10:00:00+08:00",
                                "2026-04-10T10:01:00+08:00",
                            ]
                        ),
                    },
                },
            },
        )
        schedule_id = str(created.get("schedule_id") or "").strip()
        assert schedule_id, created

        first_scan = schedule_service.run_schedule_scan(
            cfg,
            operator="test",
            now_at="2026-04-10T10:00:00+08:00",
            schedule_id=schedule_id,
        )
        first_trigger_id = str(first_scan["items"][0]["trigger_instance_id"] or "").strip()
        assert first_trigger_id, first_scan
        _wait_for_trigger(schedule_service, root, first_trigger_id)

        first_detail = schedule_service.get_schedule_detail(root, schedule_id)
        first_recent = list(first_detail.get("recent_triggers") or [])
        assert len(first_recent) == 1, first_detail
        assert str(first_recent[0].get("result_status") or "") == "queued", first_recent[0]
        active_after_first = _load_active_schedule_nodes(root, schedule_id)
        assert len(active_after_first) == 1, active_after_first
        assert active_after_first[0]["trigger_instance_id"] == first_trigger_id, active_after_first

        second_scan = schedule_service.run_schedule_scan(
            cfg,
            operator="test",
            now_at="2026-04-10T10:01:00+08:00",
            schedule_id=schedule_id,
        )
        second_trigger_id = str(second_scan["items"][0]["trigger_instance_id"] or "").strip()
        assert second_trigger_id and second_trigger_id != first_trigger_id, second_scan
        _wait_for_trigger(schedule_service, root, second_trigger_id)

        detail = schedule_service.get_schedule_detail(root, schedule_id)
        recent = list(detail.get("recent_triggers") or [])
        assert len(recent) >= 2, detail
        latest = dict(recent[0] or {})
        previous = dict(recent[1] or {})
        assert latest.get("trigger_instance_id") == second_trigger_id, latest
        assert latest.get("result_status") == "queued", latest
        assert previous.get("trigger_instance_id") == first_trigger_id, previous
        assert previous.get("trigger_status") == "superseded", previous
        assert previous.get("result_status") == "superseded", previous

        active_nodes = _load_active_schedule_nodes(root, schedule_id)
        assert len(active_nodes) == 1, active_nodes
        assert active_nodes[0]["trigger_instance_id"] == second_trigger_id, active_nodes

        conn = schedule_service.connect_db(root)
        try:
            stored = conn.execute(
                """
                SELECT trigger_instance_id,planned_trigger_at,trigger_status,trigger_message
                FROM schedule_trigger_instances
                WHERE schedule_id=?
                ORDER BY planned_trigger_at ASC
                """,
                (schedule_id,),
            ).fetchall()
        finally:
            conn.close()

        rows = [dict(item) for item in stored]
        assert [str(item.get("trigger_status") or "") for item in rows] == ["superseded", "queued"], rows

        print(
            json.dumps(
                {
                    "ok": True,
                    "schedule_id": schedule_id,
                    "first_trigger_id": first_trigger_id,
                    "second_trigger_id": second_trigger_id,
                    "active_nodes": active_nodes,
                    "recent_triggers": recent[:2],
                    "stored_rows": rows,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    finally:
        schedule_service._load_available_agents = original_schedule_load_agents
        assignment_service.list_available_agents = original_assignment_list_agents
        schedule_service._request_assignment_dispatch = original_request_dispatch


if __name__ == "__main__":
    raise SystemExit(main())
