#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlencode


IMAGE_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+cC8QAAAAASUVORK5CYII="
)
DEFECT_ASSIGNMENT_GLOBAL_GRAPH_NAME = "任务中心全局主图"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Browser acceptance for defect center queue flow.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8148)
    parser.add_argument(
        "--artifacts-dir",
        default=os.getenv("TEST_ARTIFACTS_DIR") or ".test/evidence",
    )
    parser.add_argument(
        "--logs-dir",
        default=os.getenv("TEST_LOG_DIR") or ".test/evidence",
    )
    return parser.parse_args()


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json_response(response: urllib.request.addinfourl) -> dict[str, Any]:
    raw = response.read()
    if not raw:
        return {}
    payload = json.loads(raw.decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def api_request(
    base_url: str,
    method: str,
    route: str,
    body: dict[str, Any] | None = None,
    *,
    timeout_s: int = 30,
) -> tuple[int, Any]:
    payload = None
    headers = {"Accept": "application/json"}
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(base_url + route, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=max(5, int(timeout_s))) as response:
            content_type = str(response.headers.get("Content-Type") or "")
            if "application/json" in content_type:
                return int(response.status), read_json_response(response)
            return int(response.status), response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        content_type = str(exc.headers.get("Content-Type") or "")
        if "application/json" in content_type:
            return int(exc.code), read_json_response(exc)
        return int(exc.code), exc.read().decode("utf-8")


def wait_for_health(base_url: str, timeout_s: float = 45.0) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            status, data = api_request(base_url, "GET", "/healthz")
            if status == 200 and isinstance(data, dict) and data.get("ok"):
                return data
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError("healthz timeout")


def load_workspace_runtime_config(workspace_root: Path) -> dict[str, Any]:
    for candidate in (
        workspace_root / ".runtime" / "state" / "runtime-config.json",
        workspace_root / "state" / "runtime-config.json",
    ):
        if not candidate.exists():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}


def looks_like_workspace_root(path: str) -> bool:
    text = str(path or "").strip()
    if not text:
        return False
    candidate = Path(text).resolve()
    return candidate.exists() and candidate.is_dir() and (candidate / "workflow").exists()


def infer_agent_search_root(workspace_root: Path) -> str:
    base = workspace_root.resolve()
    for candidate in [base, *base.parents]:
        if looks_like_workspace_root(candidate.as_posix()):
            return candidate.as_posix()
    return workspace_root.parent.as_posix()


def prepare_isolated_runtime_root(workspace_root: Path, runtime_root: Path) -> tuple[Path, dict[str, Any]]:
    runtime_root = runtime_root.resolve()
    state_dir = runtime_root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    source_cfg = load_workspace_runtime_config(workspace_root)
    bootstrap_cfg: dict[str, Any] = {"show_test_data": True}
    configured_agent_root = str(source_cfg.get("agent_search_root") or "").strip()
    fallback_agent_root = infer_agent_search_root(workspace_root)
    agent_search_root = configured_agent_root if looks_like_workspace_root(configured_agent_root) else fallback_agent_root
    artifact_root = (runtime_root / "artifacts").as_posix()
    if agent_search_root:
        bootstrap_cfg["agent_search_root"] = agent_search_root
    if artifact_root:
        bootstrap_cfg["artifact_root"] = artifact_root
        bootstrap_cfg["task_artifact_root"] = artifact_root
    (state_dir / "runtime-config.json").write_text(
        json.dumps(bootstrap_cfg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return runtime_root, bootstrap_cfg


def find_edge() -> Path:
    candidates = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    for path in candidates:
        if path.exists() and path.is_file():
            return path
    raise RuntimeError("msedge not found")


def edge_cmd(edge_path: Path, profile_dir: Path, width: int, height: int, budget_ms: int) -> list[str]:
    profile_dir.mkdir(parents=True, exist_ok=True)
    return [
        str(edge_path),
        "--headless=new",
        "--disable-gpu",
        "--disable-software-rasterizer",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-sync",
        "--disable-default-apps",
        "--disable-popup-blocking",
        "--disable-crash-reporter",
        "--disable-breakpad",
        "--disable-features=msEdgeSidebarV2,msUndersideButton,OptimizationGuideModelDownloading,Translate,AutofillServerCommunication",
        "--no-first-run",
        "--no-default-browser-check",
        "--no-sandbox",
        f"--user-data-dir={profile_dir.as_posix()}",
        f"--window-size={width},{height}",
        f"--virtual-time-budget={max(1000, int(budget_ms))}",
    ]


def edge_shot(
    edge_path: Path,
    url: str,
    shot_path: Path,
    *,
    profile_dir: Path,
    width: int = 1680,
    height: int = 1200,
    budget_ms: int = 26000,
) -> None:
    shot_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = edge_cmd(edge_path, profile_dir, width, height, budget_ms) + [f"--screenshot={shot_path.as_posix()}", url]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=180)
    if proc.returncode != 0:
        raise RuntimeError(f"edge screenshot failed: {proc.stderr}")


def edge_dom(
    edge_path: Path,
    url: str,
    *,
    profile_dir: Path,
    width: int = 1680,
    height: int = 1200,
    budget_ms: int = 26000,
) -> str:
    cmd = edge_cmd(edge_path, profile_dir, width, height, budget_ms) + ["--dump-dom", url]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=180)
    if proc.returncode != 0:
        raise RuntimeError(f"edge dump-dom failed: {proc.stderr}")
    return proc.stdout


def parse_probe(dom_text: str) -> dict[str, Any]:
    matched = re.search(
        r"<pre[^>]*id=['\"]defectCenterProbeOutput['\"][^>]*>(.*?)</pre>",
        str(dom_text or ""),
        flags=re.I | re.S,
    )
    if not matched:
        raise RuntimeError("defectCenterProbeOutput_not_found")
    raw = html.unescape(matched.group(1) or "").strip()
    if not raw:
        raise RuntimeError("defectCenterProbeOutput_empty")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError("defectCenterProbeOutput_not_dict")
    return payload


def defect_probe_url(base_url: str, case_id: str, extra: dict[str, str] | None = None) -> str:
    query: dict[str, str] = {
        "defect_probe": "1",
        "defect_probe_case": str(case_id),
        "_ts": str(int(time.time() * 1000)),
    }
    if extra:
        for key, value in extra.items():
            query[str(key)] = str(value)
    return base_url.rstrip("/") + "/?" + urlencode(query)


def capture_probe(
    edge_path: Path,
    base_url: str,
    evidence_root: Path,
    name: str,
    case_id: str,
    extra: dict[str, str] | None = None,
) -> tuple[str, str, dict[str, Any]]:
    url = defect_probe_url(base_url, case_id, extra)
    shot_path = evidence_root / "screenshots" / f"{name}.png"
    probe_path = evidence_root / "screenshots" / f"{name}.probe.json"
    profile_dir = evidence_root / "edge-profile" / name
    edge_shot(edge_path, url, shot_path, profile_dir=profile_dir)
    probe = parse_probe(edge_dom(edge_path, url, profile_dir=profile_dir))
    write_json(probe_path, probe)
    return shot_path.as_posix(), probe_path.as_posix(), probe


def capture_probe_with_retry(
    edge_path: Path,
    base_url: str,
    evidence_root: Path,
    name: str,
    case_id: str,
    extra: dict[str, str] | None = None,
    *,
    attempts: int = 3,
    retry_delay_s: float = 1.0,
) -> tuple[str, str, dict[str, Any]]:
    last_error: Exception | None = None
    last_result: tuple[str, str, dict[str, Any]] | None = None
    for attempt in range(max(1, attempts)):
        try:
            result = capture_probe(edge_path, base_url, evidence_root, name, case_id, extra)
            last_result = result
            if bool((result[2] or {}).get("pass")):
                return result
        except Exception as exc:
            last_error = exc
        if attempt + 1 < max(1, attempts):
            time.sleep(retry_delay_s)
    if last_result is not None:
        return last_result
    assert last_error is not None
    raise last_error


def launch_server(
    workspace_root: Path,
    runtime_root: Path,
    *,
    host: str,
    port: int,
    stdout_path: Path,
    stderr_path: Path,
) -> tuple[subprocess.Popen[bytes], Any, Any]:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_handle = stdout_path.open("wb")
    stderr_handle = stderr_path.open("wb")
    env = os.environ.copy()
    env["WORKFLOW_RUNTIME_ENV"] = "test"
    server = subprocess.Popen(
        [sys.executable, "scripts/workflow_web_server.py", "--root", str(runtime_root), "--host", host, "--port", str(port)],
        cwd=str(workspace_root),
        stdout=stdout_handle,
        stderr=stderr_handle,
        env=env,
    )
    return server, stdout_handle, stderr_handle


def stop_server(server: subprocess.Popen[bytes], stdout_handle: Any, stderr_handle: Any) -> None:
    try:
        server.terminate()
        server.wait(timeout=10)
    except subprocess.TimeoutExpired:
        server.kill()
        server.wait(timeout=10)
    finally:
        stdout_handle.close()
        stderr_handle.close()


@contextmanager
def running_server(
    workspace_root: Path,
    runtime_root: Path,
    *,
    host: str,
    port: int,
    stdout_path: Path,
    stderr_path: Path,
) -> Iterator[None]:
    server, stdout_handle, stderr_handle = launch_server(
        workspace_root,
        runtime_root,
        host=host,
        port=port,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )
    try:
        yield
    finally:
        stop_server(server, stdout_handle, stderr_handle)


def write_api_trace(
    api_root: Path,
    name: str,
    *,
    method: str,
    route: str,
    request_body: dict[str, Any] | None,
    status: int,
    response_body: Any,
) -> None:
    write_json(
        api_root / f"{name}.json",
        {
            "method": method,
            "route": route,
            "request_body": request_body,
            "status": status,
            "response": response_body,
        },
    )


def call_json_api(
    base_url: str,
    api_root: Path,
    name: str,
    method: str,
    route: str,
    body: dict[str, Any] | None = None,
    *,
    timeout_s: int = 30,
) -> tuple[int, dict[str, Any]]:
    status, payload = api_request(base_url, method, route, body, timeout_s=timeout_s)
    response_body = payload if isinstance(payload, dict) else {"raw": payload}
    write_api_trace(
        api_root,
        name,
        method=method,
        route=route,
        request_body=body,
        status=status,
        response_body=response_body,
    )
    return status, response_body


def assert_response_ok(status: int, payload: dict[str, Any], message: str) -> dict[str, Any]:
    assert_true(status == 200 and bool(payload.get("ok")), message)
    return payload


def assert_list_order(items: list[dict[str, Any]], expected_report_ids: list[str], message: str) -> None:
    actual = [str((item or {}).get("report_id") or "").strip() for item in items]
    assert_true(actual == expected_report_ids, f"{message}: expected={expected_report_ids} actual={actual}")


def assert_queue_state(
    payload: dict[str, Any],
    *,
    expected_active_id: str,
    expected_next_id: str,
    expected_candidate_total: int | None,
    message: str,
) -> None:
    queue = dict(payload.get("queue") or {})
    active_report_id = str(queue.get("active_report_id") or "").strip()
    next_report_id = str(queue.get("next_report_id") or "").strip()
    assert_true(active_report_id == expected_active_id, f"{message}: active_report_id={active_report_id}")
    assert_true(next_report_id == expected_next_id, f"{message}: next_report_id={next_report_id}")
    if expected_candidate_total is not None:
        assert_true(
            int(queue.get("candidate_total") or 0) == int(expected_candidate_total),
            f"{message}: candidate_total={queue.get('candidate_total')}",
        )
    items = list(payload.get("items") or [])
    active_ids = [
        str((item or {}).get("report_id") or "").strip()
        for item in items
        if str((item or {}).get("queue_mode") or "").strip() == "active"
    ]
    expected_active_ids = [expected_active_id] if expected_active_id else []
    assert_true(active_ids == expected_active_ids, f"{message}: active_ids={active_ids}")


def assert_assignment_priority(
    overview: dict[str, Any],
    expected_priority: str,
    message: str,
    *,
    node_ids: list[str] | None = None,
) -> None:
    nodes = list(overview.get("nodes") or overview.get("node_catalog") or [])
    assert_true(bool(nodes), f"{message}: nodes missing")
    if node_ids:
        wanted = {str(item or "").strip() for item in node_ids if str(item or "").strip()}
        nodes = [
            node
            for node in nodes
            if str((node or {}).get("node_id") or "").strip() in wanted
        ]
        assert_true(bool(nodes), f"{message}: focus nodes missing for {sorted(wanted)}")
    labels = [
        str((node or {}).get("priority_label") or "").strip()
        or str((node or {}).get("priority") or "").strip()
        for node in nodes
    ]
    assert_true(all(label == expected_priority for label in labels), f"{message}: priorities={labels}")


def find_history_detail(history: list[dict[str, Any]], title: str) -> dict[str, Any]:
    for item in history:
        if str((item or {}).get("title") or "").strip() == title:
            detail = (item or {}).get("detail")
            return detail if isinstance(detail, dict) else {}
    return {}


def create_formal_defect(
    base_url: str,
    api_root: Path,
    *,
    name: str,
    defect_summary: str,
    report_text: str,
    task_priority: str,
    reported_at: str,
) -> dict[str, Any]:
    body = {
        "defect_summary": defect_summary,
        "report_text": report_text,
        "evidence_images": [{"name": f"{name}.png", "url": IMAGE_DATA_URL}],
        "task_priority": task_priority,
        "reported_at": reported_at,
        "automation_context": {"suite_id": "defect-queue", "case_id": name, "run_id": "browser-ac", "env": "test"},
        "is_test_data": True,
        "operator": "acceptance",
    }
    status, payload = call_json_api(base_url, api_root, f"create-{name}", "POST", "/api/defects", body)
    data = assert_response_ok(status, payload, f"create defect failed: {name}")
    report = dict(data.get("report") or {})
    assert_true(bool(report.get("is_formal")), f"defect not formal: {name}")
    assert_true(str(report.get("task_priority") or "").strip() == task_priority, f"priority mismatch: {name}")
    assert_true(str(report.get("reported_at") or "").strip() == reported_at, f"reported_at mismatch: {name}")
    return report


def seed_defect_queue_flow(base_url: str, evidence_root: Path, edge_path: Path) -> dict[str, Any]:
    api_root = evidence_root / "api"

    dispute_report = create_formal_defect(
        base_url,
        api_root,
        name="p2-dispute",
        defect_summary="复核链路需要人工确认",
        report_text="升级后复核入口无法稳定打开，并且列表状态显示异常，需要进入复核链路确认。",
        task_priority="P2",
        reported_at="2026-03-25T11:20:00+08:00",
    )
    second_report = create_formal_defect(
        base_url,
        api_root,
        name="p0-next",
        defect_summary="任务中心入口无法打开",
        report_text="升级后任务中心入口无法打开，点击后直接报错，属于高优先级 workflow 缺陷。",
        task_priority="P0",
        reported_at="2026-03-25T09:30:00+08:00",
    )
    third_report = create_formal_defect(
        base_url,
        api_root,
        name="p1-middle",
        defect_summary="缺陷列表刷新后状态回退",
        report_text="缺陷列表刷新后状态会异常回退，任务中心联动不生效，需要尽快修复。",
        task_priority="P1",
        reported_at="2026-03-25T10:10:00+08:00",
    )
    head_report = create_formal_defect(
        base_url,
        api_root,
        name="p0-head",
        defect_summary="工作区路径会被刷掉",
        report_text="升级后工作区路径会直接丢失，页面无法继续使用，属于最高优先级 workflow 缺陷。",
        task_priority="P0",
        reported_at="2026-03-25T08:40:00+08:00",
    )

    dispute_id = str(dispute_report.get("report_id") or "").strip()
    assert_true(dispute_id != "", "dispute report_id missing")
    status, dispute_mark = call_json_api(
        base_url,
        api_root,
        "mark-dispute-p2",
        "POST",
        f"/api/defects/{dispute_id}/dispute",
        {"reason": "需要进入复核链路确认。", "operator": "acceptance"},
    )
    dispute_detail = assert_response_ok(status, dispute_mark, "mark dispute failed")
    dispute_report = dict(dispute_detail.get("report") or {})
    assert_true(str(dispute_report.get("status") or "").strip() == "dispute", "dispute status not applied")

    expected_order = [
        str(head_report.get("report_id") or "").strip(),
        str(second_report.get("report_id") or "").strip(),
        str(third_report.get("report_id") or "").strip(),
        str(dispute_report.get("report_id") or "").strip(),
    ]

    status, list_off = call_json_api(base_url, api_root, "list-off-all", "GET", "/api/defects?status=all")
    list_off = assert_response_ok(status, list_off, "list off failed")
    items_off = list(list_off.get("items") or [])
    assert_list_order(items_off, expected_order, "default order mismatch")
    assert_true(not bool((list_off.get("queue") or {}).get("enabled")), "queue should default off")
    assert_true(all(str((item or {}).get("task_priority") or "").strip() for item in items_off), "task_priority missing in list")
    assert_true(all(str((item or {}).get("reported_at") or "").strip() for item in items_off), "reported_at missing in list")
    assert_true(all(int((item or {}).get("task_ref_total") or 0) == 0 for item in items_off), "queue off should not auto create tasks")

    status, list_search = call_json_api(base_url, api_root, "list-search-stable", "GET", "/api/defects?status=all&keyword=%E5%90%8E")
    list_search = assert_response_ok(status, list_search, "search list failed")
    assert_list_order(list(list_search.get("items") or []), expected_order, "search should keep order")

    status, list_unresolved = call_json_api(base_url, api_root, "list-status-stable", "GET", "/api/defects?status=unresolved")
    list_unresolved = assert_response_ok(status, list_unresolved, "status list failed")
    assert_list_order(list(list_unresolved.get("items") or []), expected_order[:3], "status filter should keep order")

    head_id = expected_order[0]
    second_id = expected_order[1]
    third_id = expected_order[2]
    screenshots: dict[str, Any] = {}

    shot_path, probe_path, probe = capture_probe_with_retry(
        edge_path,
        base_url,
        evidence_root,
        "queue-off",
        "queue_off",
        {"defect_probe_report": head_id},
    )
    assert_true(bool(probe.get("pass")), "probe failed: queue_off")
    assert_true(bool(probe.get("queue_toggle_in_title")), "queue off: toggle should be in title bar")
    assert_true(bool(probe.get("queue_summary_visible")), "queue off: summary card missing")
    assert_true(not bool(probe.get("legacy_queue_strip_present")), "queue off: legacy queue strip should be removed")
    screenshots["queue-off"] = {
        "case": "queue_off",
        "screenshot": shot_path,
        "probe": probe_path,
        "probe_payload": probe,
    }

    status, queue_on = call_json_api(
        base_url,
        api_root,
        "queue-mode-on",
        "POST",
        "/api/defects/queue-mode",
        {"enabled": True},
        timeout_s=120,
    )
    queue_on = assert_response_ok(status, queue_on, "queue mode on failed")
    queue_summary = dict(queue_on.get("queue") or {})
    assert_true(bool(queue_summary.get("enabled")), "queue mode should be on")
    status, list_queue_on = call_json_api(base_url, api_root, "list-queue-on", "GET", "/api/defects?status=all")
    list_queue_on = assert_response_ok(status, list_queue_on, "list queue on failed")
    assert_queue_state(
        list_queue_on,
        expected_active_id=head_id,
        expected_next_id=second_id,
        expected_candidate_total=4,
        message="queue on should immediately promote head",
    )

    status, head_detail = call_json_api(base_url, api_root, "head-detail-active", "GET", f"/api/defects/{head_id}")
    head_detail = assert_response_ok(status, head_detail, "head detail failed")
    head_report = dict(head_detail.get("report") or {})
    head_history = list(head_detail.get("history") or [])
    assert_true(str(head_report.get("queue_mode") or "").strip() == "active", "head should occupy active slot")
    assert_true(int(head_detail.get("task_ref_total") or 0) >= 1, "head should auto create task refs")
    head_task_ref = dict((head_detail.get("task_refs") or [])[0] or {})
    head_ticket_id = str(head_task_ref.get("ticket_id") or "").strip()
    assert_true(head_ticket_id != "", "head ticket id missing")
    assert_true(str(head_task_ref.get("graph_name") or "").strip() == DEFECT_ASSIGNMENT_GLOBAL_GRAPH_NAME, "head graph name mismatch")
    head_task_history = find_history_detail(head_history, "已在任务中心创建处理任务")
    assert_true(bool(head_task_history.get("auto_queue")), "head auto_queue history missing")

    status, head_assignment = call_json_api(base_url, api_root, "head-assignment-graph", "GET", f"/api/assignments/{head_ticket_id}/graph")
    head_assignment = assert_response_ok(status, head_assignment, "head assignment overview failed")
    assert_true(
        str(((head_assignment.get("graph") or {}).get("graph_name") or "")).strip() == DEFECT_ASSIGNMENT_GLOBAL_GRAPH_NAME,
        "head assignment graph name mismatch",
    )
    assert_assignment_priority(
        head_assignment,
        "P0",
        "head assignment priority mismatch",
        node_ids=[f"{head_id}-analyze", f"{head_id}-fix", f"{head_id}-release"],
    )

    status, second_detail_before = call_json_api(base_url, api_root, "second-detail-before-advance", "GET", f"/api/defects/{second_id}")
    second_detail_before = assert_response_ok(status, second_detail_before, "second detail before advance failed")
    second_report_before = dict(second_detail_before.get("report") or {})
    assert_true(str(second_report_before.get("queue_mode") or "").strip() == "next", "second should be next before advance")
    assert_true(int(second_detail_before.get("task_ref_total") or 0) == 0, "second should not have task before advance")

    for name, case_id, report_id in (
        ("queue-on", "queue_on", second_id),
        ("queue-active", "queue_active", head_id),
    ):
        shot_path, probe_path, probe = capture_probe_with_retry(
            edge_path,
            base_url,
            evidence_root,
            name,
            case_id,
            {"defect_probe_report": report_id},
        )
        assert_true(bool(probe.get("pass")), f"probe failed: {case_id}")
        assert_true(bool(probe.get("queue_toggle_in_title")), f"{case_id}: toggle should remain in title bar")
        assert_true(bool(probe.get("queue_summary_visible")), f"{case_id}: summary card missing")
        screenshots[name] = {
            "case": case_id,
            "screenshot": shot_path,
            "probe": probe_path,
            "probe_payload": probe,
        }

    status, manual_blocked = call_json_api(
        base_url,
        api_root,
        "manual-process-blocked",
        "POST",
        f"/api/defects/{second_id}/process-task",
        {"operator": "acceptance"},
        timeout_s=120,
    )
    assert_true(status == 409, "manual process should be blocked while queue active")
    assert_true(str(manual_blocked.get("code") or "").strip() == "defect_queue_gate_blocked", "manual gate code mismatch")
    assert_true(str(manual_blocked.get("active_report_id") or "").strip() == head_id, "manual gate active report mismatch")

    status, resolve_head = call_json_api(
        base_url,
        api_root,
        "resolve-head",
        "POST",
        f"/api/defects/{head_id}/status",
        {"status": "resolved", "resolved_version": "20260325-ac-head", "operator": "acceptance"},
        timeout_s=120,
    )
    resolve_head = assert_response_ok(status, resolve_head, "resolve head failed")
    assert_true(str(((resolve_head.get("report") or {}).get("status") or "")).strip() == "resolved", "head not resolved")
    status, list_after_head = call_json_api(base_url, api_root, "list-after-head-resolved", "GET", "/api/defects?status=all")
    list_after_head = assert_response_ok(status, list_after_head, "list after head resolved failed")
    assert_queue_state(
        list_after_head,
        expected_active_id=second_id,
        expected_next_id=third_id,
        expected_candidate_total=3,
        message="head resolved should auto promote second",
    )

    status, second_detail_active = call_json_api(base_url, api_root, "second-detail-active", "GET", f"/api/defects/{second_id}")
    second_detail_active = assert_response_ok(status, second_detail_active, "second detail after advance failed")
    second_report_active = dict(second_detail_active.get("report") or {})
    second_history = list(second_detail_active.get("history") or [])
    assert_true(str(second_report_active.get("queue_mode") or "").strip() == "active", "second should become active after head resolved")
    assert_true(int(second_detail_active.get("task_ref_total") or 0) >= 1, "second should auto create task refs after advance")
    second_task_ref = dict((second_detail_active.get("task_refs") or [])[0] or {})
    second_ticket_id = str(second_task_ref.get("ticket_id") or "").strip()
    assert_true(second_ticket_id != "", "second ticket id missing")
    assert_true(second_ticket_id == head_ticket_id, "process tasks should share one global graph")
    assert_true(str(second_task_ref.get("graph_name") or "").strip() == DEFECT_ASSIGNMENT_GLOBAL_GRAPH_NAME, "second graph name mismatch")
    second_task_history = find_history_detail(second_history, "已在任务中心创建处理任务")
    assert_true(bool(second_task_history.get("auto_queue")), "second auto_queue history missing")

    status, second_assignment = call_json_api(base_url, api_root, "second-assignment-graph", "GET", f"/api/assignments/{second_ticket_id}/graph")
    second_assignment = assert_response_ok(status, second_assignment, "second assignment overview failed")
    assert_true(
        str(((second_assignment.get("graph") or {}).get("graph_name") or "")).strip() == DEFECT_ASSIGNMENT_GLOBAL_GRAPH_NAME,
        "second assignment graph name mismatch",
    )
    assert_assignment_priority(
        second_assignment,
        "P0",
        "second assignment priority mismatch",
        node_ids=[f"{second_id}-analyze", f"{second_id}-fix", f"{second_id}-release"],
    )

    shot_path, probe_path, probe = capture_probe_with_retry(
        edge_path,
        base_url,
        evidence_root,
        "queue-advanced",
        "queue_advanced",
        {"defect_probe_report": second_id},
    )
    assert_true(bool(probe.get("pass")), "probe failed: queue_advanced")
    screenshots["queue-advanced"] = {
        "case": "queue_advanced",
        "screenshot": shot_path,
        "probe": probe_path,
        "probe_payload": probe,
    }

    status, resolve_second = call_json_api(
        base_url,
        api_root,
        "resolve-second",
        "POST",
        f"/api/defects/{second_id}/status",
        {"status": "resolved", "resolved_version": "20260325-ac-second", "operator": "acceptance"},
        timeout_s=120,
    )
    resolve_second = assert_response_ok(status, resolve_second, "resolve second failed")
    assert_true(str(((resolve_second.get("report") or {}).get("status") or "")).strip() == "resolved", "second not resolved")
    status, list_after_second = call_json_api(base_url, api_root, "list-after-second-resolved", "GET", "/api/defects?status=all")
    list_after_second = assert_response_ok(status, list_after_second, "list after second resolved failed")
    assert_queue_state(
        list_after_second,
        expected_active_id=third_id,
        expected_next_id=dispute_id,
        expected_candidate_total=2,
        message="second resolved should auto promote third",
    )

    status, third_detail_active = call_json_api(base_url, api_root, "third-detail-active", "GET", f"/api/defects/{third_id}")
    third_detail_active = assert_response_ok(status, third_detail_active, "third detail active failed")
    assert_true(str(((third_detail_active.get("report") or {}).get("queue_mode") or "")).strip() == "active", "third should become active")
    assert_true(int(third_detail_active.get("task_ref_total") or 0) >= 1, "third should auto create task refs")

    status, resolve_third = call_json_api(
        base_url,
        api_root,
        "resolve-third",
        "POST",
        f"/api/defects/{third_id}/status",
        {"status": "resolved", "resolved_version": "20260325-ac-third", "operator": "acceptance"},
        timeout_s=120,
    )
    resolve_third = assert_response_ok(status, resolve_third, "resolve third failed")
    assert_true(str(((resolve_third.get("report") or {}).get("status") or "")).strip() == "resolved", "third not resolved")
    status, list_after_third = call_json_api(base_url, api_root, "list-after-third-resolved", "GET", "/api/defects?status=all")
    list_after_third = assert_response_ok(status, list_after_third, "list after third resolved failed")
    assert_queue_state(
        list_after_third,
        expected_active_id=dispute_id,
        expected_next_id="",
        expected_candidate_total=1,
        message="third resolved should auto promote dispute review",
    )

    status, dispute_detail_active = call_json_api(base_url, api_root, "dispute-detail-active", "GET", f"/api/defects/{dispute_id}")
    dispute_detail_active = assert_response_ok(status, dispute_detail_active, "dispute detail active failed")
    dispute_report_active = dict(dispute_detail_active.get("report") or {})
    dispute_history = list(dispute_detail_active.get("history") or [])
    assert_true(str(dispute_report_active.get("queue_mode") or "").strip() == "active", "dispute should become active")
    assert_true(int(dispute_detail_active.get("task_ref_total") or 0) >= 1, "dispute should auto create review task")
    dispute_task_ref = dict((dispute_detail_active.get("task_refs") or [])[0] or {})
    dispute_ticket_id = str(dispute_task_ref.get("ticket_id") or "").strip()
    assert_true(dispute_ticket_id != "", "dispute ticket id missing")
    assert_true(dispute_ticket_id == head_ticket_id, "review task should share the global graph")
    assert_true(str(dispute_task_ref.get("action_kind") or "").strip() == "review", "dispute should create review task")
    assert_true(str(dispute_task_ref.get("graph_name") or "").strip() == DEFECT_ASSIGNMENT_GLOBAL_GRAPH_NAME, "dispute graph name mismatch")
    dispute_task_history = find_history_detail(dispute_history, "已在任务中心创建复核任务")
    assert_true(bool(dispute_task_history.get("auto_queue")), "dispute auto_queue history missing")

    status, dispute_assignment = call_json_api(base_url, api_root, "dispute-assignment-graph", "GET", f"/api/assignments/{dispute_ticket_id}/graph")
    dispute_assignment = assert_response_ok(status, dispute_assignment, "dispute assignment overview failed")
    assert_assignment_priority(
        dispute_assignment,
        "P2",
        "dispute assignment priority mismatch",
        node_ids=[f"{dispute_id}-review"],
    )
    assert_true(
        str(((dispute_assignment.get("graph") or {}).get("graph_name") or "")).strip() == DEFECT_ASSIGNMENT_GLOBAL_GRAPH_NAME,
        "dispute assignment graph name mismatch",
    )

    status, close_dispute = call_json_api(
        base_url,
        api_root,
        "close-dispute",
        "POST",
        f"/api/defects/{dispute_id}/status",
        {"status": "closed", "operator": "acceptance"},
        timeout_s=120,
    )
    close_dispute = assert_response_ok(status, close_dispute, "close dispute failed")
    assert_true(str(((close_dispute.get("report") or {}).get("status") or "")).strip() == "closed", "dispute not closed")

    status, final_list = call_json_api(base_url, api_root, "list-final-all", "GET", "/api/defects?status=all")
    final_list = assert_response_ok(status, final_list, "final list failed")
    assert_list_order(list(final_list.get("items") or []), expected_order, "final list order mismatch")
    assert_queue_state(
        final_list,
        expected_active_id="",
        expected_next_id="",
        expected_candidate_total=0,
        message="queue should drain after final defect exits active slot",
    )

    shot_path, probe_path, probe = capture_probe_with_retry(
        edge_path,
        base_url,
        evidence_root,
        "queue-drained",
        "queue_drained",
        {"defect_probe_report": dispute_id},
    )
    assert_true(bool(probe.get("pass")), "probe failed: queue_drained")
    screenshots["queue-drained"] = {
        "case": "queue_drained",
        "screenshot": shot_path,
        "probe": probe_path,
        "probe_payload": probe,
    }

    return {
        "expected_order": expected_order,
        "global_ticket_id": head_ticket_id,
        "head": {
            "report_id": head_id,
            "display_id": str(head_report.get("display_id") or "").strip(),
            "task_priority": str(head_report.get("task_priority") or "").strip(),
            "ticket_id": head_ticket_id,
        },
        "next": {
            "report_id": second_id,
            "display_id": str(second_report_active.get("display_id") or "").strip(),
            "task_priority": str(second_report_active.get("task_priority") or "").strip(),
            "ticket_id": second_ticket_id,
        },
        "dispute": {
            "report_id": dispute_id,
            "display_id": str(dispute_report_active.get("display_id") or "").strip(),
            "task_priority": str(dispute_report_active.get("task_priority") or "").strip(),
            "ticket_id": dispute_ticket_id,
        },
        "screenshots": screenshots,
    }


def main() -> int:
    args = parse_args()
    workspace_root = Path(args.root).resolve()
    artifacts_root = Path(args.artifacts_dir).resolve() / "defect-center-browser"
    logs_root = Path(args.logs_dir).resolve() / "defect-center-browser"
    if artifacts_root.exists():
        shutil.rmtree(artifacts_root, ignore_errors=True)
    if logs_root.exists():
        shutil.rmtree(logs_root, ignore_errors=True)
    artifacts_root.mkdir(parents=True, exist_ok=True)
    logs_root.mkdir(parents=True, exist_ok=True)
    runtime_root = Path(os.getenv("TEST_TMP_DIR") or (artifacts_root / "runtime")).resolve()
    if runtime_root.exists():
        shutil.rmtree(runtime_root)
    runtime_root, bootstrap_cfg = prepare_isolated_runtime_root(workspace_root, runtime_root)
    edge_path = find_edge()
    base_url = f"http://{args.host}:{int(args.port)}"
    with running_server(
        workspace_root,
        runtime_root,
        host=args.host,
        port=int(args.port),
        stdout_path=logs_root / "server.stdout.log",
        stderr_path=logs_root / "server.stderr.log",
    ):
        health = wait_for_health(base_url)
        seeded = seed_defect_queue_flow(base_url, artifacts_root, edge_path)
        summary = {
            "ok": True,
            "base_url": base_url,
            "health": health,
            "bootstrap_cfg": bootstrap_cfg,
            "seeded": seeded,
            "screenshots": dict(seeded.get("screenshots") or {}),
            "evidence_paths": {
                "api_root": (artifacts_root / "api").as_posix(),
                "screenshots_root": (artifacts_root / "screenshots").as_posix(),
                "server_stdout": (logs_root / "server.stdout.log").as_posix(),
                "server_stderr": (logs_root / "server.stderr.log").as_posix(),
            },
        }
        write_json(artifacts_root / "summary.json", summary)
        print((artifacts_root / "summary.json").as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
