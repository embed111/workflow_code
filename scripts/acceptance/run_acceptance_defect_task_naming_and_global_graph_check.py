#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


GLOBAL_REQUEST_ID = "workflow-ui-global-graph-v1"

try:
    BEIJING_TZ = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:
    BEIJING_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate defect task naming and global graph behavior.")
    parser.add_argument("--root", required=True, help="runtime root for the temporary validation server")
    parser.add_argument("--host", default="127.0.0.1", help="bind host")
    parser.add_argument("--port", type=int, default=18096, help="bind port")
    parser.add_argument("--agent-search-root", required=True, help="agent search root passed to workflow server")
    parser.add_argument("--artifacts-dir", default="", help="directory for collected artifacts")
    parser.add_argument("--logs-dir", default="", help="directory for server stdout/stderr logs")
    return parser.parse_args()


class ValidationContext:
    def __init__(self, args: argparse.Namespace) -> None:
        self.repo_root = Path(__file__).resolve().parents[2]
        self.runtime_root = Path(args.root).resolve(strict=False)
        self.host = str(args.host)
        self.port = int(args.port)
        self.base_url = f"http://{self.host}:{self.port}"
        self.agent_search_root = str(args.agent_search_root)
        self.artifacts_dir = (
            Path(args.artifacts_dir).resolve(strict=False)
            if str(args.artifacts_dir).strip()
            else self.runtime_root / "artifacts"
        )
        self.logs_dir = (
            Path(args.logs_dir).resolve(strict=False)
            if str(args.logs_dir).strip()
            else self.runtime_root / "logs"
        )
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.server_proc: subprocess.Popen[str] | None = None
        self.server_stdout = None
        self.server_stderr = None

    def dump_json(self, name: str, payload: object) -> Path:
        path = self.artifacts_dir / name
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def dump_text(self, name: str, content: object) -> Path:
        path = self.artifacts_dir / name
        path.write_text(str(content), encoding="utf-8")
        return path

    def api(self, method: str, path: str, payload: dict | None = None, params: dict[str, str] | None = None) -> object:
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = None
        headers: dict[str, str] = {}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                raw = response.read().decode("utf-8")
                content_type = response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            raise RuntimeError(f"{method} {path} failed: {exc.code} {raw}") from exc
        if "application/json" in content_type or raw.lstrip().startswith("{") or raw.lstrip().startswith("["):
            return json.loads(raw)
        return raw

    def wait_for_health(self) -> None:
        last_error = ""
        for _ in range(120):
            try:
                with urllib.request.urlopen(self.base_url + "/healthz", timeout=5) as response:
                    if response.status == 200:
                        return
            except Exception as exc:  # pragma: no cover - retry logic
                last_error = str(exc)
            time.sleep(0.5)
        raise RuntimeError("server healthz did not become ready: " + last_error)

    def start_server(self, tag: str) -> None:
        self.stop_server()
        stdout_path = self.logs_dir / f"{tag}-server.stdout.log"
        stderr_path = self.logs_dir / f"{tag}-server.stderr.log"
        self.server_stdout = open(stdout_path, "a", encoding="utf-8")
        self.server_stderr = open(stderr_path, "a", encoding="utf-8")
        self.server_proc = subprocess.Popen(
            [
                sys.executable,
                "scripts/workflow_web_server.py",
                "--root",
                str(self.runtime_root),
                "--host",
                self.host,
                "--port",
                str(self.port),
                "--agent-search-root",
                self.agent_search_root,
            ],
            cwd=str(self.repo_root),
            stdout=self.server_stdout,
            stderr=self.server_stderr,
            text=True,
        )
        self.wait_for_health()

    def stop_server(self) -> None:
        if self.server_proc is not None:
            if self.server_proc.poll() is None:
                self.server_proc.terminate()
                try:
                    self.server_proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    self.server_proc.kill()
                    self.server_proc.wait(timeout=15)
            self.server_proc = None
        if self.server_stdout is not None:
            self.server_stdout.close()
            self.server_stdout = None
        if self.server_stderr is not None:
            self.server_stderr.close()
            self.server_stderr = None


def ensure(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def sorted_titles(items: list[dict], *, action_kind: str) -> list[str]:
    return sorted(
        str(item.get("title") or "").strip()
        for item in list(items or [])
        if str(item.get("action_kind") or "").strip() == action_kind
    )


def run_js_syntax_check(ctx: ValidationContext) -> None:
    node_path = shutil.which("node")
    if not node_path:
        return
    js_paths = [
        "src/workflow_app/web_client/defect_center_state_helpers.js",
        "src/workflow_app/web_client/defect_center_render_runtime.js",
        "src/workflow_app/web_client/defect_center_events.js",
    ]
    node_script = (
        "const fs=require('fs');"
        "for (const file of process.argv.slice(1)) {"
        "  new Function(fs.readFileSync(file,'utf8'));"
        "  console.log('syntax ok ' + file);"
        "}"
    )
    subprocess.run([node_path, "-e", node_script, *js_paths], cwd=str(ctx.repo_root), check=True)


def main() -> int:
    args = parse_args()
    ctx = ValidationContext(args)
    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "py_compile",
                "src/workflow_app/server/services/defect_service_prejudge.py",
                "src/workflow_app/server/services/defect_service_record_commands.py",
                "src/workflow_app/server/services/defect_service_task_commands.py",
            ],
            cwd=str(ctx.repo_root),
            check=True,
        )
        run_js_syntax_check(ctx)

        ctx.start_server("phase1")

        index_html = ctx.api("GET", "/")
        ctx.dump_text("index.html", index_html)
        ensure("assignmentGraphMeta" in str(index_html), "task center graph meta anchor should exist in page html")

        agents = ctx.api("GET", "/api/training/agents")
        ctx.dump_json("training-agents.json", agents)
        agent_items = list((agents or {}).get("items") or [])
        ensure(bool(agent_items), "training agents should not be empty for local validation")
        assigned_agent_id = str(agent_items[0].get("agent_id") or "").strip()
        ensure(bool(assigned_agent_id), "assigned_agent_id should not be empty")

        global_lookup_before = ctx.api(
            "GET",
            "/api/assignments",
            params={"source_workflow": "workflow-ui", "external_request_id": GLOBAL_REQUEST_ID, "limit": "24"},
        )
        ctx.dump_json("assignments-global-before.json", global_lookup_before)

        auto_create = ctx.api(
            "POST",
            "/api/defects",
            {
                "defect_summary": "角色创建任务映射缺失",
                "report_text": "创建角色后任务中心没有映射，页面报错且无法继续查看。",
                "operator": "web-user",
            },
        )
        ctx.dump_json("defect-auto-create.json", auto_create)
        auto_report = dict((auto_create or {}).get("report") or {})
        auto_report_id = str(auto_report.get("report_id") or "").strip()
        auto_display_id = str(auto_report.get("display_id") or "").strip()
        ensure(auto_report_id != "", "auto report id should not be empty")

        queue_on = ctx.api("POST", "/api/defects/queue-mode", {"enabled": True})
        ctx.dump_json("defect-queue-on.json", queue_on)

        auto_detail = ctx.api("GET", f"/api/defects/{urllib.parse.quote(auto_report_id)}")
        ctx.dump_json("defect-auto-detail.json", auto_detail)
        auto_titles = sorted(str(item.get("title") or "").strip() for item in list((auto_detail or {}).get("task_refs") or []))
        ensure(any(title.endswith(" - 分析") for title in auto_titles), "auto queue should create semantic analyze title")
        ensure(any(title.endswith(" - 修复") for title in auto_titles), "auto queue should create semantic fix title")
        ensure(any(title.endswith(" - 推送到目标版本") for title in auto_titles), "auto queue should create semantic release title")
        ensure(all(title not in {"分析缺陷", "修复缺陷", "推送到目标版本"} for title in auto_titles), "auto queue titles should not fall back to generic names")
        ensure(any(title.startswith(auto_display_id + " ") for title in auto_titles), "auto queue title should start with display id")

        queue_off = ctx.api("POST", "/api/defects/queue-mode", {"enabled": False})
        ctx.dump_json("defect-queue-off.json", queue_off)

        manual_create = ctx.api(
            "POST",
            "/api/defects",
            {
                "defect_summary": "启动页双窗口异常",
                "report_text": "点击启动后会出现两个页面，属于异常，无法继续稳定操作。",
                "operator": "web-user",
            },
        )
        ctx.dump_json("defect-manual-create.json", manual_create)
        manual_report = dict((manual_create or {}).get("report") or {})
        manual_report_id = str(manual_report.get("report_id") or "").strip()
        manual_display_id = str(manual_report.get("display_id") or "").strip()
        manual_base_name = f"{manual_display_id} 启动页双窗口异常"
        ensure(manual_report_id != "", "manual report id should not be empty")

        short_create = ctx.api(
            "POST",
            "/api/defects",
            {
                "report_text": "角色名错了",
                "operator": "web-user",
            },
        )
        ctx.dump_json("defect-short-create.json", short_create)
        short_report = dict((short_create or {}).get("report") or {})
        ensure(str(short_report.get("report_id") or "").strip() != "", "short report id should not be empty")
        ensure(bool(short_report.get("is_formal")), "one-line issue report should still enter formal defect flow")
        ensure(str(short_report.get("status") or "").strip() == "unresolved", "one-line issue report should be unresolved")
        ensure(str(short_report.get("display_id") or "").strip().startswith("DTS-"), "formal one-line issue report should allocate DTS id")

        process_first = ctx.api(
            "POST",
            f"/api/defects/{urllib.parse.quote(manual_report_id)}/process-task",
            {"operator": "web-user", "task_name_base": manual_base_name},
        )
        ctx.dump_json("defect-process-first.json", process_first)
        process_titles_first = sorted_titles(list((process_first or {}).get("task_refs") or []), action_kind="process")
        ensure(
            process_titles_first == sorted(
                [
                    manual_base_name + " - 分析",
                    manual_base_name + " - 修复",
                    manual_base_name + " - 推送到目标版本",
                ]
            ),
            "manual process titles should match explicit base name",
        )

        process_second = ctx.api(
            "POST",
            f"/api/defects/{urllib.parse.quote(manual_report_id)}/process-task",
            {"operator": "web-user", "task_name_base": manual_base_name + " 改名不应生效"},
        )
        ctx.dump_json("defect-process-second.json", process_second)
        process_titles_second = sorted_titles(list((process_second or {}).get("task_refs") or []), action_kind="process")
        ensure(process_titles_second == process_titles_first, "existing process chain should keep original titles on retry")

        ctx.api(
            "POST",
            f"/api/defects/{urllib.parse.quote(manual_report_id)}/supplements/text",
            {"text": "补充说明：重新验证后问题仍然存在。", "operator": "web-user"},
        )

        review_first = ctx.api(
            "POST",
            f"/api/defects/{urllib.parse.quote(manual_report_id)}/review-task",
            {"operator": "web-user", "task_name_base": manual_base_name},
        )
        ctx.dump_json("defect-review-first.json", review_first)
        review_titles_first = sorted_titles(list((review_first or {}).get("task_refs") or []), action_kind="review")
        ensure(review_titles_first == [manual_base_name + " - 复核"], "manual review title should match explicit base name")

        review_second = ctx.api(
            "POST",
            f"/api/defects/{urllib.parse.quote(manual_report_id)}/review-task",
            {"operator": "web-user", "task_name_base": manual_base_name + " 改名不应生效"},
        )
        ctx.dump_json("defect-review-second.json", review_second)
        review_titles_second = sorted_titles(list((review_second or {}).get("task_refs") or []), action_kind="review")
        ensure(review_titles_second == review_titles_first, "existing review chain should keep original title on retry")

        global_ticket_id = str((process_first or {}).get("created_task_ticket_id") or "").strip()
        ensure(global_ticket_id != "", "global assignment ticket id should not be empty")

        global_lookup = ctx.api(
            "GET",
            "/api/assignments",
            params={"source_workflow": "workflow-ui", "external_request_id": GLOBAL_REQUEST_ID, "limit": "24"},
        )
        ctx.dump_json("assignments-global.json", global_lookup)
        global_items = list((global_lookup or {}).get("items") or [])
        ensure(len(global_items) == 1, "global graph lookup should return exactly one item")
        ensure(str(global_items[0].get("ticket_id") or "").strip() == global_ticket_id, "global graph ticket id should be stable")

        assignments_before_extra = ctx.api("GET", "/api/assignments", params={"limit": "200"})
        ctx.dump_json("assignments-before-extra.json", assignments_before_extra)
        assignments_before_extra_items = list((assignments_before_extra or {}).get("items") or [])
        assignments_before_extra_ids = [str(item.get("ticket_id") or "").strip() for item in assignments_before_extra_items]
        workflow_ui_graph_ids_before_extra = [
            str(item.get("ticket_id") or "").strip()
            for item in assignments_before_extra_items
            if str(item.get("source_workflow") or "").strip() == "workflow-ui"
        ]
        legacy_active_graphs_before_extra = [
            {
                "ticket_id": str(item.get("ticket_id") or "").strip(),
                "graph_name": str(item.get("graph_name") or "").strip(),
                "source_workflow": str(item.get("source_workflow") or "").strip(),
                "external_request_id": str(item.get("external_request_id") or "").strip(),
            }
            for item in assignments_before_extra_items
            if str(item.get("ticket_id") or "").strip() and str(item.get("ticket_id") or "").strip() != global_ticket_id
        ]
        ensure(global_ticket_id in assignments_before_extra_ids, "unfiltered assignment list should include the global graph")

        graph_global = ctx.api("GET", f"/api/assignments/{urllib.parse.quote(global_ticket_id)}/graph")
        ctx.dump_json("assignment-global-graph.json", graph_global)
        graph_titles = sorted(str(item.get("node_name") or "").strip() for item in list((graph_global or {}).get("nodes") or []))
        ensure(manual_base_name + " - 分析" in graph_titles, "global graph should expose semantic analyze node name")
        ensure(manual_base_name + " - 复核" in graph_titles, "global graph should expose semantic review node name")

        extra_graph = ctx.api(
            "POST",
            "/api/assignments",
            {
                "graph_name": "临时独立任务图",
                "summary": "用于验证 workflow-ui 建图请求会被归一到全局主图",
                "source_workflow": "workflow-ui",
                "operator": "web-user",
            },
        )
        ctx.dump_json("assignment-extra-graph.json", extra_graph)
        extra_ticket_id = str((extra_graph or {}).get("ticket_id") or "").strip()
        ensure(extra_ticket_id == global_ticket_id, "workflow-ui extra graph request should reuse the global ticket id")

        assignments_after_extra = ctx.api("GET", "/api/assignments", params={"limit": "200"})
        ctx.dump_json("assignments-after-extra.json", assignments_after_extra)
        active_graph_ids = [str(item.get("ticket_id") or "").strip() for item in list((assignments_after_extra or {}).get("items") or [])]
        ensure(global_ticket_id in active_graph_ids, "unfiltered assignment list should still include the global graph")
        workflow_ui_graph_ids_after_extra = [
            str(item.get("ticket_id") or "").strip()
            for item in list((assignments_after_extra or {}).get("items") or [])
            if str(item.get("source_workflow") or "").strip() == "workflow-ui"
        ]
        ensure(len(set(workflow_ui_graph_ids_after_extra)) == 1, "assignment list should expose exactly one workflow-ui graph")
        ensure(
            len(set(active_graph_ids)) == len(set(assignments_before_extra_ids)),
            "workflow-ui extra graph request should not add a new active graph",
        )

        bj_now = datetime.now(BEIJING_TZ).replace(second=0, microsecond=0)
        trigger_time = bj_now.strftime("%Y-%m-%d %H:%M")
        schedule_create = ctx.api(
            "POST",
            "/api/schedules",
            {
                "schedule_name": "定时任务单主图检查",
                "enabled": True,
                "assigned_agent_id": assigned_agent_id,
                "launch_summary": "验证定时任务命中后是否仍追加到全局主图。",
                "execution_checklist": "1. 检查任务中心节点是否创建。\\n2. 检查是否复用全局主图。",
                "done_definition": "任务中心出现对应节点且不新增第三张活动图。",
                "priority": "P1",
                "expected_artifact": "定时任务执行记录.html",
                "delivery_mode": "none",
                "rule_sets": {"once": {"enabled": True, "date_times": [trigger_time]}},
                "operator": "web-user",
            },
        )
        ctx.dump_json("schedule-create.json", schedule_create)
        schedule_id = str((schedule_create or {}).get("schedule_id") or "").strip()
        ensure(schedule_id != "", "schedule_id should not be empty")

        schedule_scan = ctx.api(
            "POST",
            "/api/schedules/scan",
            {"schedule_id": schedule_id, "now_at": trigger_time, "operator": "web-user"},
        )
        ctx.dump_json("schedule-scan.json", schedule_scan)
        ensure(bool(list((schedule_scan or {}).get("items") or [])), "schedule scan should create at least one item")

        schedule_detail = ctx.api("GET", f"/api/schedules/{urllib.parse.quote(schedule_id)}")
        ctx.dump_json("schedule-detail.json", schedule_detail)
        related_task_refs = list((schedule_detail or {}).get("related_task_refs") or [])
        ensure(bool(related_task_refs), "schedule detail should include related task refs")
        schedule_ticket_id = str(related_task_refs[0].get("assignment_ticket_id") or "").strip()
        ensure(schedule_ticket_id == global_ticket_id, "schedule trigger should append node to global graph instead of creating new graph")

        assignments_after_schedule = ctx.api("GET", "/api/assignments", params={"limit": "200"})
        ctx.dump_json("assignments-after-schedule.json", assignments_after_schedule)
        active_graph_ids_after_schedule = [str(item.get("ticket_id") or "").strip() for item in list((assignments_after_schedule or {}).get("items") or [])]
        workflow_ui_graph_ids_after_schedule = [
            str(item.get("ticket_id") or "").strip()
            for item in list((assignments_after_schedule or {}).get("items") or [])
            if str(item.get("source_workflow") or "").strip() == "workflow-ui"
        ]
        ensure(len(set(workflow_ui_graph_ids_after_schedule)) == 1, "schedule trigger should still expose only one workflow-ui graph")
        ensure(
            sorted(set(active_graph_ids_after_schedule)) == sorted(set(active_graph_ids)),
            "schedule trigger should not create an additional active graph",
        )

        ctx.stop_server()
        ctx.start_server("phase2")

        assignments_after_restart = ctx.api("GET", "/api/assignments", params={"limit": "200"})
        ctx.dump_json("assignments-after-restart.json", assignments_after_restart)
        restart_graph_ids = [str(item.get("ticket_id") or "").strip() for item in list((assignments_after_restart or {}).get("items") or [])]
        workflow_ui_graph_ids_after_restart = [
            str(item.get("ticket_id") or "").strip()
            for item in list((assignments_after_restart or {}).get("items") or [])
            if str(item.get("source_workflow") or "").strip() == "workflow-ui"
        ]
        ensure(len(set(workflow_ui_graph_ids_after_restart)) == 1, "restart should recover a single workflow-ui graph")
        ensure(sorted(set(restart_graph_ids)) == sorted(set(active_graph_ids)), "restart should recover the same active graph set")

        summary = {
            "global_ticket_id": global_ticket_id,
            "extra_ticket_id": extra_ticket_id,
            "auto_titles": auto_titles,
            "process_titles_first": process_titles_first,
            "process_titles_second": process_titles_second,
            "review_titles_first": review_titles_first,
            "review_titles_second": review_titles_second,
            "active_graph_ids_before_extra": assignments_before_extra_ids,
            "workflow_ui_graph_ids_before_extra": workflow_ui_graph_ids_before_extra,
            "legacy_active_graphs_before_extra": legacy_active_graphs_before_extra,
            "active_graph_ids_after_extra": active_graph_ids,
            "workflow_ui_graph_ids_after_extra": workflow_ui_graph_ids_after_extra,
            "active_graph_ids_after_schedule": active_graph_ids_after_schedule,
            "workflow_ui_graph_ids_after_schedule": workflow_ui_graph_ids_after_schedule,
            "active_graph_ids_after_restart": restart_graph_ids,
            "workflow_ui_graph_ids_after_restart": workflow_ui_graph_ids_after_restart,
            "schedule_ticket_id": schedule_ticket_id,
            "page_has_graph_meta_anchor": "assignmentGraphMeta" in str(index_html),
        }
        ctx.dump_json("summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    finally:
        ctx.stop_server()


if __name__ == "__main__":
    raise SystemExit(main())
