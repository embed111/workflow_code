#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_acceptance_role_creation_browser import (  # type: ignore
    api_request,
    assert_true,
    find_edge,
    edge_dom,
    prepare_runtime_root,
    record_api,
    role_message_text,
    running_server,
    wait_for_health,
    wait_for_role_creation_idle,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Acceptance for role-creation async message batching and delete behavior."
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8144)
    parser.add_argument("--artifacts-dir", default=os.getenv("TEST_ARTIFACTS_DIR") or ".test/evidence")
    parser.add_argument("--logs-dir", default=os.getenv("TEST_LOG_DIR") or ".test/evidence")
    return parser.parse_args()


def capture_dom(edge_path: Path, base_url: str, evidence_root: Path, name: str, session_id: str) -> str:
    query = urlencode(
        {
            "tc_probe": "1",
            "tc_probe_case": "rc_default",
            "tc_probe_session": session_id,
            "_ts": str(int(time.time() * 1000)),
        }
    )
    dom_text = edge_dom(
        edge_path,
        base_url.rstrip("/") + "/?" + query,
        profile_dir=evidence_root / "edge-profile" / name,
    )
    out_path = evidence_root / "dom" / f"{name}.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(dom_text, encoding="utf-8")
    return out_path.as_posix()


def task_ids_from_detail(detail: dict) -> list[str]:
    node_ids: list[str] = []
    for stage in list(detail.get("stages") or []):
        for task in list(stage.get("active_tasks") or []):
            node_id = str(task.get("node_id") or "").strip()
            if node_id:
                node_ids.append(node_id)
    return node_ids


def task_ref_ids_from_detail(detail: dict) -> list[str]:
    node_ids: list[str] = []
    for task_ref in list(detail.get("task_refs") or []):
        node_id = str(task_ref.get("node_id") or "").strip()
        if node_id:
            node_ids.append(node_id)
    return node_ids


def all_task_ids_from_detail(detail: dict) -> list[str]:
    ordered: dict[str, None] = {}
    for node_id in task_ids_from_detail(detail) + task_ref_ids_from_detail(detail):
        ordered.setdefault(node_id, None)
    return list(ordered.keys())


def wait_for_role_creation_delete_available(
    base_url: str,
    session_id: str,
    timeout_s: float = 120.0,
) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last_payload: dict[str, Any] = {}
    while time.time() < deadline:
        status, data = api_request(base_url, "GET", f"/api/training/role-creation/sessions/{session_id}")
        if status == 200 and isinstance(data, dict) and data.get("ok"):
            last_payload = data
            session = dict(data.get("session") or {})
            if bool(session.get("delete_available")):
                return data
        time.sleep(1)
    raise RuntimeError(
        "role creation delete-available timeout: "
        + str(
            {
                "session_id": session_id,
                "last_status": (last_payload.get("session") or {}).get("status"),
                "last_delete_available": (last_payload.get("session") or {}).get("delete_available"),
                "last_delete_block_reason": (last_payload.get("session") or {}).get("delete_block_reason"),
                "last_assignment_running_node_count": (last_payload.get("session") or {}).get(
                    "assignment_running_node_count"
                ),
            }
        )
    )


def main() -> int:
    args = parse_args()
    repo_root = Path(args.root).resolve()
    run_key = datetime.now().strftime("%Y%m%d-%H%M%S")
    artifacts_dir = Path(args.artifacts_dir).resolve()
    logs_dir = Path(args.logs_dir).resolve()
    evidence_root = artifacts_dir / f"role-creation-async-delete-{run_key}"
    log_root = logs_dir / f"role-creation-async-delete-{run_key}"
    api_dir = evidence_root / "api"
    evidence_root.mkdir(parents=True, exist_ok=True)
    api_dir.mkdir(parents=True, exist_ok=True)
    log_root.mkdir(parents=True, exist_ok=True)
    runtime_base = Path(os.getenv("TEST_TMP_DIR") or (repo_root / ".test" / "runtime")).resolve()
    runtime_root = prepare_runtime_root(repo_root, runtime_base / "role-creation-async-delete")
    base_url = f"http://{args.host}:{args.port}"
    edge_path = find_edge()

    sys.path.insert(0, str(repo_root / "src"))
    from workflow_app.server.bootstrap import web_server_runtime as ws  # type: ignore
    from workflow_app.server.infra.db.migrations import ensure_tables  # type: ignore

    ensure_tables(runtime_root)
    ws.bind_training_center_runtime_once()

    evidence: dict = {
        "repo_root": str(repo_root),
        "runtime_root": str(runtime_root),
        "base_url": base_url,
        "edge_path": str(edge_path),
        "api": {},
        "dom": {},
        "assertions": {},
    }
    operator = "role-creation-async-delete-acceptance"

    try:
        with running_server(
            repo_root,
            runtime_root,
            host=args.host,
            port=args.port,
            stdout_path=log_root / "server.stdout.log",
            stderr_path=log_root / "server.stderr.log",
        ):
            evidence["healthz"] = wait_for_health(base_url)

            agent_root = (runtime_root / "workspace-root").resolve()
            artifact_root = (evidence_root / "task-output").resolve()
            (agent_root / "workflow").mkdir(parents=True, exist_ok=True)
            artifact_root.mkdir(parents=True, exist_ok=True)

            status, body = api_request(
                base_url,
                "POST",
                "/api/config/agent-search-root",
                {"agent_search_root": agent_root.as_posix()},
            )
            assert_true(status == 200 and isinstance(body, dict) and body.get("ok"), "switch agent root failed")
            evidence["api"]["switch_agent_root"] = record_api(
                api_dir,
                stage="setup",
                name="switch_agent_root",
                method="POST",
                path="/api/config/agent-search-root",
                payload={"agent_search_root": agent_root.as_posix()},
                status=status,
                body=body,
            )

            status, body = api_request(
                base_url,
                "POST",
                "/api/config/artifact-root",
                {"artifact_root": artifact_root.as_posix()},
            )
            assert_true(status == 200 and isinstance(body, dict) and body.get("ok"), "switch artifact root failed")
            evidence["api"]["switch_artifact_root"] = record_api(
                api_dir,
                stage="setup",
                name="switch_artifact_root",
                method="POST",
                path="/api/config/artifact-root",
                payload={"artifact_root": artifact_root.as_posix()},
                status=status,
                body=body,
            )

            draft_payload = {"session_title": "AsyncDelete Draft", "operator": operator}
            status, draft_create = api_request(base_url, "POST", "/api/training/role-creation/sessions", draft_payload)
            assert_true(status == 200 and isinstance(draft_create, dict) and draft_create.get("ok"), "draft create failed")
            draft_session_id = str((draft_create.get("session") or {}).get("session_id") or "").strip()
            evidence["api"]["draft_create"] = record_api(
                api_dir,
                stage="draft",
                name="create_session",
                method="POST",
                path="/api/training/role-creation/sessions",
                payload=draft_payload,
                status=status,
                body=draft_create,
            )

            draft_dom_path = capture_dom(edge_path, base_url, evidence_root, "draft-delete-visible", draft_session_id)
            evidence["dom"]["draft_delete_visible"] = draft_dom_path
            draft_dom_text = Path(draft_dom_path).read_text(encoding="utf-8")
            assert_true(
                f"data-rc-delete-session=\"{draft_session_id}\"" in draft_dom_text
                or f"data-rc-delete-session='{draft_session_id}'" in draft_dom_text,
                "draft delete button missing in DOM",
            )

            status, draft_delete = api_request(
                base_url,
                "DELETE",
                f"/api/training/role-creation/sessions/{draft_session_id}",
                {"operator": operator},
            )
            assert_true(status == 200 and isinstance(draft_delete, dict) and draft_delete.get("ok"), "draft delete failed")
            evidence["api"]["draft_delete"] = record_api(
                api_dir,
                stage="draft",
                name="delete_session",
                method="DELETE",
                path=f"/api/training/role-creation/sessions/{draft_session_id}",
                payload={"operator": operator},
                status=status,
                body=draft_delete,
            )

            async_payload = {"session_title": "AsyncDelete Batch", "operator": operator}
            status, async_create = api_request(base_url, "POST", "/api/training/role-creation/sessions", async_payload)
            assert_true(status == 200 and isinstance(async_create, dict) and async_create.get("ok"), "async create failed")
            async_session_id = str((async_create.get("session") or {}).get("session_id") or "").strip()
            evidence["api"]["async_create"] = record_api(
                api_dir,
                stage="async",
                name="create_session",
                method="POST",
                path="/api/training/role-creation/sessions",
                payload=async_payload,
                status=status,
                body=async_create,
            )

            timings: list[float] = []
            async_responses: list[dict] = []
            for index, content in enumerate(
                [
                    "先记住角色名是异步验收草稿。",
                    "再补充职责边界和工作方式，连续消息要合并处理。",
                ],
                start=1,
            ):
                message_payload = {
                    "content": content,
                    "operator": operator,
                    "client_message_id": f"async-delete-{index}",
                }
                started_at = time.perf_counter()
                status, async_message = api_request(
                    base_url,
                    "POST",
                    f"/api/training/role-creation/sessions/{async_session_id}/messages",
                    message_payload,
                )
                timings.append(time.perf_counter() - started_at)
                assert_true(
                    status == 200 and isinstance(async_message, dict) and async_message.get("ok"),
                    f"async message {index} failed",
                )
                async_responses.append(async_message)
                evidence["api"][f"async_message_{index}"] = record_api(
                    api_dir,
                    stage="async",
                    name=f"message_{index}",
                    method="POST",
                    path=f"/api/training/role-creation/sessions/{async_session_id}/messages",
                    payload=message_payload,
                    status=status,
                    body=async_message,
                )

            second_session = dict(async_responses[-1].get("session") or {})
            assert_true(
                str(second_session.get("message_processing_status") or "").strip().lower() in {"pending", "running"},
                "async session should be pending or running after second message",
            )
            assert_true(
                int(second_session.get("unhandled_user_message_count") or 0) >= 2,
                "async session should report at least two unhandled messages after second post",
            )

            status, blocked_delete = api_request(
                base_url,
                "DELETE",
                f"/api/training/role-creation/sessions/{async_session_id}",
                {"operator": operator},
            )
            assert_true(
                status == 409
                and isinstance(blocked_delete, dict)
                and str(blocked_delete.get("code") or "").strip() == "role_creation_delete_processing_blocked",
                "processing delete should be blocked",
            )
            evidence["api"]["async_delete_blocked"] = record_api(
                api_dir,
                stage="async",
                name="delete_processing_blocked",
                method="DELETE",
                path=f"/api/training/role-creation/sessions/{async_session_id}",
                payload={"operator": operator},
                status=status,
                body=blocked_delete,
            )

            async_idle = wait_for_role_creation_idle(base_url, async_session_id)
            evidence["api"]["async_idle"] = record_api(
                api_dir,
                stage="async",
                name="idle_detail",
                method="GET",
                path=f"/api/training/role-creation/sessions/{async_session_id}",
                payload=None,
                status=200,
                body=async_idle,
            )
            async_messages = list(async_idle.get("messages") or [])
            async_user_rows = [m for m in async_messages if str(m.get("role") or "").strip().lower() == "user"]
            async_processed_users = [
                m
                for m in async_user_rows
                if str(m.get("processing_state") or (m.get("meta") or {}).get("processing_state") or "").strip().lower()
                == "processed"
            ]
            async_assistant_rows = [
                m
                for m in async_messages
                if str(m.get("role") or "").strip().lower() == "assistant"
                and str(m.get("message_type") or "chat").strip().lower() == "chat"
            ]
            assert_true(len(async_processed_users) >= 2, "async user messages should end as processed")
            assert_true(len(async_assistant_rows) == 2, "async flow should keep welcome + one merged assistant reply")

            cleanup_payload = {"session_title": "AsyncDelete Creating Cleanup", "operator": operator}
            status, cleanup_create = api_request(base_url, "POST", "/api/training/role-creation/sessions", cleanup_payload)
            assert_true(status == 200 and isinstance(cleanup_create, dict) and cleanup_create.get("ok"), "cleanup create failed")
            cleanup_session_id = str((cleanup_create.get("session") or {}).get("session_id") or "").strip()
            evidence["api"]["cleanup_create"] = record_api(
                api_dir,
                stage="cleanup",
                name="create_session",
                method="POST",
                path="/api/training/role-creation/sessions",
                payload=cleanup_payload,
                status=status,
                body=cleanup_create,
            )

            cleanup_message_payload = {
                "content": role_message_text("Async Delete Cleanup Role"),
                "operator": operator,
                "client_message_id": "cleanup-role-spec",
            }
            status, cleanup_message = api_request(
                base_url,
                "POST",
                f"/api/training/role-creation/sessions/{cleanup_session_id}/messages",
                cleanup_message_payload,
            )
            assert_true(
                status == 200 and isinstance(cleanup_message, dict) and cleanup_message.get("ok"),
                "cleanup role-spec message failed",
            )
            evidence["api"]["cleanup_message"] = record_api(
                api_dir,
                stage="cleanup",
                name="message",
                method="POST",
                path=f"/api/training/role-creation/sessions/{cleanup_session_id}/messages",
                payload=cleanup_message_payload,
                status=status,
                body=cleanup_message,
            )

            cleanup_ready = wait_for_role_creation_idle(base_url, cleanup_session_id)
            evidence["api"]["cleanup_idle"] = record_api(
                api_dir,
                stage="cleanup",
                name="idle_detail",
                method="GET",
                path=f"/api/training/role-creation/sessions/{cleanup_session_id}",
                payload=None,
                status=200,
                body=cleanup_ready,
            )

            status, cleanup_start = api_request(
                base_url,
                "POST",
                f"/api/training/role-creation/sessions/{cleanup_session_id}/start",
                {"operator": operator},
            )
            assert_true(status == 200 and isinstance(cleanup_start, dict) and cleanup_start.get("ok"), "cleanup start failed")
            cleanup_session = dict(cleanup_start.get("session") or {})
            cleanup_ticket_id = str(
                cleanup_session.get("assignment_ticket_id")
                or (cleanup_start.get("stage_meta") or {}).get("ticket_id")
                or ""
            ).strip()
            assert_true(
                str(cleanup_session.get("status") or "").strip().lower() == "creating" and cleanup_ticket_id,
                "cleanup session should enter creating with ticket",
            )
            evidence["api"]["cleanup_start"] = record_api(
                api_dir,
                stage="cleanup",
                name="start_session",
                method="POST",
                path=f"/api/training/role-creation/sessions/{cleanup_session_id}/start",
                payload={"operator": operator},
                status=status,
                body=cleanup_start,
            )

            status, cleanup_started_detail = api_request(
                base_url,
                "GET",
                f"/api/training/role-creation/sessions/{cleanup_session_id}",
            )
            assert_true(
                status == 200 and isinstance(cleanup_started_detail, dict) and cleanup_started_detail.get("ok"),
                "cleanup started detail fetch failed",
            )
            evidence["api"]["cleanup_detail_started"] = record_api(
                api_dir,
                stage="cleanup",
                name="detail_started",
                method="GET",
                path=f"/api/training/role-creation/sessions/{cleanup_session_id}",
                payload=None,
                status=status,
                body=cleanup_started_detail,
            )
            cleanup_started_session = dict(cleanup_started_detail.get("session") or {})
            cleanup_workspace_path = str(
                cleanup_started_session.get("created_agent_workspace_path")
                or cleanup_session.get("created_agent_workspace_path")
                or ""
            ).strip()
            assert_true(bool(cleanup_workspace_path), "cleanup workspace path missing after start")
            cleanup_workspace = Path(cleanup_workspace_path).resolve(strict=False)
            assert_true(cleanup_workspace.exists(), "cleanup workspace should exist before delete")
            cleanup_task_ids = all_task_ids_from_detail(cleanup_started_detail)
            if not cleanup_task_ids:
                cleanup_runtime_detail = ws.get_role_creation_session_detail(runtime_root, cleanup_session_id)
                cleanup_task_ids = all_task_ids_from_detail(cleanup_runtime_detail)
            assert_true(bool(cleanup_task_ids), "cleanup session task ids missing")

            cleanup_running_node_count = int(cleanup_started_session.get("assignment_running_node_count") or 0)
            cleanup_running_block_checked = False
            if cleanup_running_node_count > 0:
                status, cleanup_delete_blocked = api_request(
                    base_url,
                    "DELETE",
                    f"/api/training/role-creation/sessions/{cleanup_session_id}",
                    {"operator": operator},
                )
                assert_true(
                    status == 409
                    and isinstance(cleanup_delete_blocked, dict)
                    and str(cleanup_delete_blocked.get("code") or "").strip() == "role_creation_delete_running_tasks_blocked",
                    "cleanup delete should be blocked while assignment nodes are running",
                )
                evidence["api"]["cleanup_delete_blocked_running"] = record_api(
                    api_dir,
                    stage="cleanup",
                    name="delete_running_blocked",
                    method="DELETE",
                    path=f"/api/training/role-creation/sessions/{cleanup_session_id}",
                    payload={"operator": operator},
                    status=status,
                    body=cleanup_delete_blocked,
                )
                cleanup_running_block_checked = True

            for node_id in cleanup_task_ids:
                ws.deliver_assignment_artifact(
                    runtime_root,
                    ticket_id_text=cleanup_ticket_id,
                    node_id_text=node_id,
                    operator=operator,
                    artifact_label=f"{node_id}.html",
                    delivery_note="async cleanup acceptance delivered",
                )
                ws.override_assignment_node_status(
                    runtime_root,
                    ticket_id_text=cleanup_ticket_id,
                    node_id_text=node_id,
                    target_status="succeeded",
                    operator=operator,
                    reason="async cleanup acceptance completed",
                    result_ref=f"acceptance://{node_id}",
                )

            cleanup_delete_ready = wait_for_role_creation_delete_available(base_url, cleanup_session_id)
            evidence["api"]["cleanup_delete_ready"] = record_api(
                api_dir,
                stage="cleanup",
                name="delete_ready_detail",
                method="GET",
                path=f"/api/training/role-creation/sessions/{cleanup_session_id}",
                payload=None,
                status=200,
                body=cleanup_delete_ready,
            )
            cleanup_delete_ready_session = dict(cleanup_delete_ready.get("session") or {})
            assert_true(
                str(cleanup_delete_ready_session.get("status") or "").strip().lower() == "creating",
                "cleanup session should still be creating before cleanup delete",
            )
            assert_true(
                int(cleanup_delete_ready_session.get("assignment_running_node_count") or 0) == 0,
                "cleanup delete should wait until running assignment nodes drop to zero",
            )

            cleanup_dom_path = capture_dom(edge_path, base_url, evidence_root, "cleanup-delete-visible", cleanup_session_id)
            evidence["dom"]["cleanup_delete_visible"] = cleanup_dom_path
            cleanup_dom_text = Path(cleanup_dom_path).read_text(encoding="utf-8")
            assert_true(
                f"data-rc-delete-session=\"{cleanup_session_id}\"" in cleanup_dom_text
                or f"data-rc-delete-session='{cleanup_session_id}'" in cleanup_dom_text,
                "cleanup-ready creating session should expose delete button in DOM",
            )

            status, cleanup_delete = api_request(
                base_url,
                "DELETE",
                f"/api/training/role-creation/sessions/{cleanup_session_id}",
                {"operator": operator},
            )
            assert_true(
                status == 200 and isinstance(cleanup_delete, dict) and cleanup_delete.get("ok"),
                "cleanup delete failed",
            )
            cleanup_result = dict(cleanup_delete.get("cleanup_result") or {})
            assert_true(
                str(cleanup_result.get("mode") or "").strip() == "creating_cleanup",
                "cleanup delete should return creating_cleanup result",
            )
            assert_true(
                bool((cleanup_result.get("assignment_cleanup") or {}).get("removed")),
                "cleanup delete should remove assignment workspace",
            )
            assert_true(
                bool((cleanup_result.get("workspace_cleanup") or {}).get("removed")),
                "cleanup delete should remove role workspace",
            )
            evidence["api"]["cleanup_delete"] = record_api(
                api_dir,
                stage="cleanup",
                name="delete_session",
                method="DELETE",
                path=f"/api/training/role-creation/sessions/{cleanup_session_id}",
                payload={"operator": operator},
                status=status,
                body=cleanup_delete,
            )

            status, cleanup_detail_missing = api_request(
                base_url,
                "GET",
                f"/api/training/role-creation/sessions/{cleanup_session_id}",
            )
            assert_true(
                status == 404
                and isinstance(cleanup_detail_missing, dict)
                and str(cleanup_detail_missing.get("code") or "").strip() == "role_creation_session_not_found",
                "cleanup-deleted session detail should return not found",
            )
            evidence["api"]["cleanup_detail_missing"] = record_api(
                api_dir,
                stage="cleanup",
                name="detail_after_delete",
                method="GET",
                path=f"/api/training/role-creation/sessions/{cleanup_session_id}",
                payload=None,
                status=status,
                body=cleanup_detail_missing,
            )

            status, cleanup_graph_missing = api_request(
                base_url,
                "GET",
                f"/api/assignments/{cleanup_ticket_id}/graph",
            )
            assert_true(
                status == 404
                and isinstance(cleanup_graph_missing, dict)
                and str(cleanup_graph_missing.get("code") or "").strip() == "assignment_graph_not_found",
                "cleanup-deleted assignment graph should return not found",
            )
            evidence["api"]["cleanup_graph_missing"] = record_api(
                api_dir,
                stage="cleanup",
                name="graph_after_delete",
                method="GET",
                path=f"/api/assignments/{cleanup_ticket_id}/graph",
                payload=None,
                status=status,
                body=cleanup_graph_missing,
            )
            assert_true(not cleanup_workspace.exists(), "cleanup delete should remove created workspace directory")

            completed_payload = {"session_title": "AsyncDelete Completed Record", "operator": operator}
            status, completed_create = api_request(
                base_url,
                "POST",
                "/api/training/role-creation/sessions",
                completed_payload,
            )
            assert_true(
                status == 200 and isinstance(completed_create, dict) and completed_create.get("ok"),
                "completed flow create failed",
            )
            completed_session_id = str((completed_create.get("session") or {}).get("session_id") or "").strip()
            evidence["api"]["completed_create"] = record_api(
                api_dir,
                stage="completed",
                name="create_session",
                method="POST",
                path="/api/training/role-creation/sessions",
                payload=completed_payload,
                status=status,
                body=completed_create,
            )

            completed_message_payload = {
                "content": role_message_text("Async Delete Completed Role"),
                "operator": operator,
                "client_message_id": "completed-role-spec",
            }
            status, completed_message = api_request(
                base_url,
                "POST",
                f"/api/training/role-creation/sessions/{completed_session_id}/messages",
                completed_message_payload,
            )
            assert_true(
                status == 200 and isinstance(completed_message, dict) and completed_message.get("ok"),
                "completed flow role-spec message failed",
            )
            evidence["api"]["completed_message"] = record_api(
                api_dir,
                stage="completed",
                name="message",
                method="POST",
                path=f"/api/training/role-creation/sessions/{completed_session_id}/messages",
                payload=completed_message_payload,
                status=status,
                body=completed_message,
            )

            completed_idle = wait_for_role_creation_idle(base_url, completed_session_id)
            evidence["api"]["completed_idle"] = record_api(
                api_dir,
                stage="completed",
                name="idle_detail",
                method="GET",
                path=f"/api/training/role-creation/sessions/{completed_session_id}",
                payload=None,
                status=200,
                body=completed_idle,
            )

            status, completed_start = api_request(
                base_url,
                "POST",
                f"/api/training/role-creation/sessions/{completed_session_id}/start",
                {"operator": operator},
            )
            assert_true(
                status == 200 and isinstance(completed_start, dict) and completed_start.get("ok"),
                "completed flow start failed",
            )
            completed_started_session = dict(completed_start.get("session") or {})
            completed_ticket_id = str(
                completed_started_session.get("assignment_ticket_id")
                or (completed_start.get("stage_meta") or {}).get("ticket_id")
                or ""
            ).strip()
            assert_true(
                str(completed_started_session.get("status") or "").strip().lower() == "creating" and completed_ticket_id,
                "completed flow session should enter creating with ticket",
            )
            evidence["api"]["completed_start"] = record_api(
                api_dir,
                stage="completed",
                name="start_session",
                method="POST",
                path=f"/api/training/role-creation/sessions/{completed_session_id}/start",
                payload={"operator": operator},
                status=status,
                body=completed_start,
            )

            status, completed_started_detail = api_request(
                base_url,
                "GET",
                f"/api/training/role-creation/sessions/{completed_session_id}",
            )
            assert_true(
                status == 200 and isinstance(completed_started_detail, dict) and completed_started_detail.get("ok"),
                "completed flow started detail fetch failed",
            )
            evidence["api"]["completed_detail_started"] = record_api(
                api_dir,
                stage="completed",
                name="detail_started",
                method="GET",
                path=f"/api/training/role-creation/sessions/{completed_session_id}",
                payload=None,
                status=status,
                body=completed_started_detail,
            )
            completed_workspace_path = str(
                ((completed_started_detail.get("session") or {}).get("created_agent_workspace_path"))
                or completed_started_session.get("created_agent_workspace_path")
                or ""
            ).strip()
            completed_workspace = Path(completed_workspace_path).resolve(strict=False) if completed_workspace_path else None
            if completed_workspace is not None:
                assert_true(completed_workspace.exists(), "completed flow workspace should exist before record delete")

            completed_task_ids = all_task_ids_from_detail(completed_started_detail)
            if not completed_task_ids:
                completed_runtime_detail = ws.get_role_creation_session_detail(runtime_root, completed_session_id)
                completed_task_ids = all_task_ids_from_detail(completed_runtime_detail)
            assert_true(bool(completed_task_ids), "completed flow task ids missing")
            for node_id in completed_task_ids:
                ws.deliver_assignment_artifact(
                    runtime_root,
                    ticket_id_text=completed_ticket_id,
                    node_id_text=node_id,
                    operator=operator,
                    artifact_label=f"{node_id}.html",
                    delivery_note="async completed acceptance delivered",
                )
                ws.override_assignment_node_status(
                    runtime_root,
                    ticket_id_text=completed_ticket_id,
                    node_id_text=node_id,
                    target_status="succeeded",
                    operator=operator,
                    reason="async completed acceptance completed",
                    result_ref=f"acceptance://{node_id}",
                )

            complete_payload = {
                "operator": operator,
                "confirmed": True,
                "acceptance_note": "all starter tasks completed in acceptance harness",
            }
            status, completed = api_request(
                base_url,
                "POST",
                f"/api/training/role-creation/sessions/{completed_session_id}/complete",
                complete_payload,
            )
            assert_true(status == 200 and isinstance(completed, dict) and completed.get("ok"), "complete session failed")
            completed_session = dict(completed.get("session") or {})
            assert_true(
                str(completed_session.get("status") or "").strip().lower() == "completed",
                "session should become completed",
            )
            evidence["api"]["completed_session"] = record_api(
                api_dir,
                stage="completed",
                name="complete_session",
                method="POST",
                path=f"/api/training/role-creation/sessions/{completed_session_id}/complete",
                payload=complete_payload,
                status=status,
                body=completed,
            )

            completed_dom_path = capture_dom(edge_path, base_url, evidence_root, "completed-delete-visible", completed_session_id)
            evidence["dom"]["completed_delete_visible"] = completed_dom_path
            completed_dom_text = Path(completed_dom_path).read_text(encoding="utf-8")
            assert_true(
                f"data-rc-delete-session=\"{completed_session_id}\"" in completed_dom_text
                or f"data-rc-delete-session='{completed_session_id}'" in completed_dom_text,
                "completed session should expose delete button in DOM",
            )

            status, completed_delete = api_request(
                base_url,
                "DELETE",
                f"/api/training/role-creation/sessions/{completed_session_id}",
                {"operator": operator},
            )
            assert_true(
                status == 200 and isinstance(completed_delete, dict) and completed_delete.get("ok"),
                "completed delete failed",
            )
            assert_true(
                not bool(completed_delete.get("cleanup_result")),
                "completed delete should only remove record, not run creating cleanup",
            )
            evidence["api"]["completed_delete"] = record_api(
                api_dir,
                stage="completed",
                name="delete_session",
                method="DELETE",
                path=f"/api/training/role-creation/sessions/{completed_session_id}",
                payload={"operator": operator},
                status=status,
                body=completed_delete,
            )

            status, completed_detail_missing = api_request(
                base_url,
                "GET",
                f"/api/training/role-creation/sessions/{completed_session_id}",
            )
            assert_true(
                status == 404
                and isinstance(completed_detail_missing, dict)
                and str(completed_detail_missing.get("code") or "").strip() == "role_creation_session_not_found",
                "completed-deleted session detail should return not found",
            )
            evidence["api"]["completed_detail_missing"] = record_api(
                api_dir,
                stage="completed",
                name="detail_after_delete",
                method="GET",
                path=f"/api/training/role-creation/sessions/{completed_session_id}",
                payload=None,
                status=status,
                body=completed_detail_missing,
            )
            if completed_workspace is not None:
                assert_true(completed_workspace.exists(), "completed record delete should keep created workspace directory")

            evidence["assertions"] = {
                "async_post_latencies_ms": [round(item * 1000, 1) for item in timings],
                "async_unhandled_after_second_post": int(second_session.get("unhandled_user_message_count") or 0),
                "async_final_user_processed_count": len(async_processed_users),
                "async_final_assistant_chat_count": len(async_assistant_rows),
                "cleanup_task_count": len(cleanup_task_ids),
                "completed_task_count": len(completed_task_ids),
                "draft_session_id": draft_session_id,
                "async_session_id": async_session_id,
                "cleanup_session_id": cleanup_session_id,
                "cleanup_ticket_id": cleanup_ticket_id,
                "completed_session_id": completed_session_id,
                "completed_ticket_id": completed_ticket_id,
                "cleanup_running_block_checked": cleanup_running_block_checked,
            }

            summary_md = evidence_root / "summary.md"
            summary_md.write_text(
                "\n".join(
                    [
                        "# Role Creation Async/Delete Acceptance",
                        "",
                        f"- base_url: {base_url}",
                        f"- runtime_root: {runtime_root.as_posix()}",
                        f"- edge_path: {edge_path.as_posix()}",
                        f"- artifact_root: {artifact_root.as_posix()}",
                        "",
                        "## Checks",
                        "",
                        f"- draft delete visible in DOM and API delete succeeds: session `{draft_session_id}`",
                        f"- async batching returns quickly, delete blocked during processing, then settles idle: session `{async_session_id}`",
                        (
                            f"- creating session only exposes cleanup delete after running assignment nodes drop to zero; "
                            f"cleanup delete removes session, assignment graph, and workspace: session `{cleanup_session_id}`"
                        ),
                        f"- completed session shows delete and can remove only the session record: session `{completed_session_id}`",
                        "",
                        "## Evidence",
                        "",
                        f"- api_dir: {api_dir.as_posix()}",
                        f"- draft_dom: {draft_dom_path}",
                        f"- cleanup_dom: {cleanup_dom_path}",
                        f"- completed_dom: {completed_dom_path}",
                        f"- server_stdout: {(log_root / 'server.stdout.log').as_posix()}",
                        f"- server_stderr: {(log_root / 'server.stderr.log').as_posix()}",
                        "",
                        "## Metrics",
                        "",
                        f"- async_post_latencies_ms: {evidence['assertions']['async_post_latencies_ms']}",
                        f"- async_unhandled_after_second_post: {evidence['assertions']['async_unhandled_after_second_post']}",
                        f"- async_final_user_processed_count: {evidence['assertions']['async_final_user_processed_count']}",
                        f"- async_final_assistant_chat_count: {evidence['assertions']['async_final_assistant_chat_count']}",
                        f"- cleanup_task_count: {evidence['assertions']['cleanup_task_count']}",
                        f"- completed_task_count: {evidence['assertions']['completed_task_count']}",
                        f"- cleanup_running_block_checked: {evidence['assertions']['cleanup_running_block_checked']}",
                        "",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            evidence["summary_md"] = summary_md.as_posix()
            evidence["ok"] = True
    finally:
        write_json(evidence_root / "summary.json", evidence)

    print((evidence_root / "summary.md").as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
