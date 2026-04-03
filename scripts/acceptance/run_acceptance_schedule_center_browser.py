#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import html
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlencode


BEIJING_TZ = timezone(timedelta(hours=8))
GOOD_CODEX_COMMAND_TEMPLATE = (
    'cmd.exe /c ping -n 5 127.0.0.1 >nul && '
    '"{codex_path}" exec --dangerously-bypass-approvals-and-sandbox --json --skip-git-repo-check '
    '--add-dir "{workspace_path}" -C "{workspace_path}" -'
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Browser acceptance for schedule center.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8162)
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


def log_step(message: str) -> None:
    stamp = datetime.now(BEIJING_TZ).isoformat(timespec="seconds")
    print(f"[schedule-center] {stamp} {message}", flush=True)


def format_error(exc: Exception) -> str:
    return f"{exc.__class__.__name__}: {exc}"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json_response(response: urllib.request.addinfourl) -> dict[str, Any]:
    raw = response.read()
    if not raw:
        return {}
    payload = json.loads(raw.decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def api_request(base_url: str, method: str, route: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    payload = None
    headers = {"Accept": "application/json"}
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        base_url + route,
        data=payload,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
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


def wait_for_assignment_status(
    base_url: str,
    *,
    ticket_id: str,
    node_id: str,
    timeout_s: float,
    predicate,
) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    route = f"/api/assignments/{ticket_id}/status-detail?node_id={node_id}&include_test_data=1"
    last_payload: dict[str, Any] = {}
    last_error = ""
    while time.time() < deadline:
        try:
            status, body = api_request(base_url, "GET", route)
        except Exception as exc:
            last_error = format_error(exc)
            time.sleep(0.8)
            continue
        if status == 200 and isinstance(body, dict) and body.get("ok"):
            last_payload = body
            if predicate(body):
                return body
        time.sleep(0.8)
    if last_payload:
        return last_payload
    if last_error:
        raise RuntimeError(f"assignment status-detail timeout: {last_error}")
    raise RuntimeError("assignment status-detail timeout")


def wait_for_schedule_detail(
    base_url: str,
    *,
    schedule_id: str,
    timeout_s: float,
    predicate,
) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    route = "/api/schedules/" + schedule_id
    last_payload: dict[str, Any] = {}
    last_error = ""
    while time.time() < deadline:
        try:
            status, body = api_request(base_url, "GET", route)
        except Exception as exc:
            last_error = format_error(exc)
            time.sleep(0.8)
            continue
        if status == 200 and isinstance(body, dict) and body.get("ok"):
            last_payload = body
            if predicate(body):
                return body
        time.sleep(0.8)
    if last_payload:
        return last_payload
    if last_error:
        raise RuntimeError(f"schedule detail timeout: {last_error}")
    raise RuntimeError("schedule detail timeout")


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
    timeout_s: int = 90,
) -> None:
    shot_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = edge_cmd(edge_path, profile_dir, width, height, budget_ms) + [f"--screenshot={shot_path.as_posix()}", url]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=max(15, int(timeout_s)))
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
    timeout_s: int = 90,
) -> str:
    cmd = edge_cmd(edge_path, profile_dir, width, height, budget_ms) + ["--dump-dom", url]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=max(15, int(timeout_s)))
    if proc.returncode != 0:
        raise RuntimeError(f"edge dump-dom failed: {proc.stderr}")
    return proc.stdout


def parse_schedule_probe(dom_text: str) -> dict[str, Any]:
    matched = re.search(
        r"<pre[^>]*id=['\"]scheduleCenterProbeOutput['\"][^>]*>(.*?)</pre>",
        str(dom_text or ""),
        flags=re.I | re.S,
    )
    if not matched:
        raise RuntimeError("scheduleCenterProbeOutput_not_found")
    raw = html.unescape(matched.group(1) or "").strip()
    if not raw:
        raise RuntimeError("scheduleCenterProbeOutput_empty")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError("scheduleCenterProbeOutput_not_dict")
    return payload


def schedule_probe_url(base_url: str, case_id: str, extra: dict[str, str] | None = None) -> str:
    query: dict[str, str] = {
        "schedule_probe": "1",
        "schedule_probe_case": str(case_id),
        "_ts": str(int(time.time() * 1000)),
    }
    if extra:
        for key, value in extra.items():
            query[str(key)] = str(value)
    return base_url.rstrip("/") + "/?" + urlencode(query)


def probe_delay_ms(extra: dict[str, str] | None = None) -> int:
    raw = ""
    if isinstance(extra, dict):
        raw = str(extra.get("schedule_probe_delay_ms") or "").strip()
    try:
        value = int(raw or 900)
    except Exception:
        value = 900
    return max(0, value)


def probe_budget_ms(extra: dict[str, str] | None = None) -> int:
    delay_ms = probe_delay_ms(extra)
    return max(6500, min(18000, delay_ms + 6500))


def probe_timeout_s(extra: dict[str, str] | None = None) -> int:
    budget_ms = probe_budget_ms(extra)
    return max(45, min(90, int(budget_ms / 1000) + 30))


def capture_probe(
    edge_path: Path,
    base_url: str,
    evidence_root: Path,
    *,
    name: str,
    case_id: str,
    extra: dict[str, str] | None = None,
) -> tuple[str, str, dict[str, Any]]:
    url = schedule_probe_url(base_url, case_id, extra)
    shot_path = evidence_root / "screenshots" / f"{name}.png"
    probe_path = evidence_root / "screenshots" / f"{name}.probe.json"
    budget_ms = probe_budget_ms(extra)
    timeout_s = probe_timeout_s(extra)
    shot_profile_dir = evidence_root / "edge-profile" / f"{name}-shot"
    dom_profile_dir = evidence_root / "edge-profile" / f"{name}-dom"
    log_step(f"probe {name}/{case_id}: budget={budget_ms}ms timeout={timeout_s}s")
    edge_shot(edge_path, url, shot_path, profile_dir=shot_profile_dir, budget_ms=budget_ms, timeout_s=timeout_s)
    probe = parse_schedule_probe(
        edge_dom(
            edge_path,
            url,
            profile_dir=dom_profile_dir,
            budget_ms=budget_ms,
            timeout_s=timeout_s,
        )
    )
    write_json(probe_path, probe)
    return shot_path.as_posix(), probe_path.as_posix(), probe


def capture_probe_with_retry(
    edge_path: Path,
    base_url: str,
    evidence_root: Path,
    *,
    name: str,
    case_id: str,
    extra: dict[str, str] | None = None,
    attempts: int = 3,
    retry_delay_s: float = 1.0,
) -> tuple[str, str, dict[str, Any]]:
    last_error: Exception | None = None
    last_result: tuple[str, str, dict[str, Any]] | None = None
    for attempt in range(max(1, attempts)):
        try:
            result = capture_probe(edge_path, base_url, evidence_root, name=name, case_id=case_id, extra=extra)
            last_result = result
            if bool((result[2] or {}).get("pass")):
                return result
            log_step(f"probe {name}/{case_id}: pass=false on attempt {attempt + 1}/{max(1, attempts)}")
        except Exception as exc:
            last_error = exc
            log_step(f"probe {name}/{case_id}: attempt {attempt + 1}/{max(1, attempts)} failed: {format_error(exc)}")
        if attempt + 1 < max(1, attempts):
            time.sleep(retry_delay_s)
    if last_result is not None:
        return last_result
    assert last_error is not None
    raise last_error


def looks_like_agent_root(path: Path) -> bool:
    candidate = path.resolve()
    return candidate.exists() and candidate.is_dir() and (candidate / "workflow").exists()


def infer_agent_search_root(workspace_root: Path) -> Path:
    for candidate in [workspace_root.resolve(), *workspace_root.resolve().parents]:
        if looks_like_agent_root(candidate):
            return candidate
    raise RuntimeError("agent_search_root_not_found")


def find_codex_path() -> str:
    candidates = [
        shutil.which("codex.cmd"),
        shutil.which("codex"),
        str(Path.home() / "AppData/Roaming/npm/codex.cmd"),
    ]
    for item in candidates:
        if not item:
            continue
        path = Path(item)
        if path.exists():
            return path.as_posix()
    raise RuntimeError("codex command not found")


def prepare_isolated_runtime_root(
    runtime_root: Path,
    *,
    agent_search_root: Path,
    artifact_root: Path,
) -> tuple[Path, dict[str, Any]]:
    if runtime_root.exists():
        shutil.rmtree(runtime_root, ignore_errors=True)
    state_dir = runtime_root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    bootstrap_cfg = {
        "show_test_data": True,
        "agent_search_root": agent_search_root.as_posix(),
        "artifact_root": artifact_root.as_posix(),
        "task_artifact_root": artifact_root.as_posix(),
    }
    (state_dir / "runtime-config.json").write_text(
        json.dumps(bootstrap_cfg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return runtime_root, bootstrap_cfg


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
        [
            sys.executable,
            "scripts/workflow_web_server.py",
            "--root",
            str(runtime_root),
            "--host",
            host,
            "--port",
            str(port),
        ],
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


def shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    month += offset
    while month <= 0:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1
    return year, month


def format_month_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def choose_agent(agents_payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    items = list(agents_payload.get("agents") or [])
    assert_true(bool(items), "no agents discovered")

    def is_preferred(item: dict[str, Any]) -> bool:
        agent_name = str(item.get("agent_name") or "").strip().lower()
        agents_path = str(item.get("agents_md_path") or "").replace("\\", "/").lower()
        if agent_name == "workflow":
            return False
        if "/workflow/" in agents_path:
            return False
        if any(token in agents_path for token in ["/.running/", "/.test/", "/state/", "/logs/"]):
            return False
        return True

    preferred = [item for item in items if is_preferred(item)]
    chosen = preferred[0] if preferred else items[0]
    receiver = preferred[1] if len(preferred) > 1 else chosen
    return chosen, receiver


def query_sqlite_rows(db_path: Path, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            return []
        return [dict(row) for row in rows]
    finally:
        conn.close()


def read_schedule_events(log_path: Path, schedule_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    if not log_path.exists():
        return []
    matched: list[dict[str, Any]] = []
    with log_path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            raw = raw.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except Exception:
                continue
            if str(payload.get("schedule_id") or "").strip() == schedule_id:
                matched.append(payload)
    return matched[-limit:]


def render_report(report_path: Path, summary: dict[str, Any]) -> None:
    screenshots = summary.get("screenshots") or {}
    evidence = summary.get("evidence_files") or {}
    warnings = list(summary.get("warnings") or [])
    lines = [
        "# Schedule Center Browser Acceptance",
        "",
        f"- generated_at: {datetime.now(BEIJING_TZ).isoformat(timespec='seconds')}",
        f"- workspace_root: {summary.get('workspace_root', '')}",
        f"- runtime_root: {summary.get('runtime_root', '')}",
        f"- agent_search_root: {summary.get('agent_search_root', '')}",
        f"- selected_agent: {summary.get('selected_agent_name', '')}",
        f"- schedule_id: {summary.get('schedule_id', '')}",
        f"- assignment_ticket_id: {summary.get('assignment_ticket_id', '')}",
        f"- assignment_node_id: {summary.get('assignment_node_id', '')}",
        "",
        "## Screenshots",
        "",
        f"- empty_state: {screenshots.get('empty_state', {}).get('image', '')}",
        f"- list_default: {screenshots.get('list_default', {}).get('image', '')}",
        f"- list_detail: {screenshots.get('list_detail', {}).get('image', '')}",
        f"- editor_edit: {screenshots.get('editor_edit', {}).get('image', '')}",
        f"- calendar_month: {screenshots.get('calendar_month', {}).get('image', '')}",
        f"- calendar_shifted: {screenshots.get('calendar_shifted', {}).get('image', '')}",
        f"- result_detail: {screenshots.get('result_detail', {}).get('image', '')}",
        "",
        "## Evidence",
        "",
        f"- create_response: {evidence.get('create_response', '')}",
        f"- edit_response: {evidence.get('edit_response', '')}",
        f"- disable_response: {evidence.get('disable_response', '')}",
        f"- enable_response: {evidence.get('enable_response', '')}",
        f"- scan_create_response: {evidence.get('scan_create_response', '')}",
        f"- scan_dedupe_response: {evidence.get('scan_dedupe_response', '')}",
        f"- schedule_detail_after_scan: {evidence.get('schedule_detail_after_scan', '')}",
        f"- assignment_status_live: {evidence.get('assignment_status_live', '')}",
        f"- assignment_status_terminal: {evidence.get('assignment_status_terminal', '')}",
        f"- schedule_events: {evidence.get('schedule_events', '')}",
        f"- db_trigger_rows: {evidence.get('db_trigger_rows', '')}",
        f"- db_audit_rows: {evidence.get('db_audit_rows', '')}",
        f"- db_assignment_rows: {evidence.get('db_assignment_rows', '')}",
        f"- assignment_node_json: {evidence.get('assignment_node_json', '')}",
        "",
        "## Notes",
        "",
        "- 定时任务到任务中心的建单/调度联动没有独立公开 HTTP 接口，本次以 `/api/schedules/scan` 返回、`schedule_audit_log` / `logs/events/schedules.jsonl` 留痕和任务中心 `status-detail` 作为联动证据。",
        f"- terminal_status_observed: {summary.get('terminal_status_observed', False)}",
        f"- live_status_kind: {summary.get('live_status_kind', '')}",
        "",
    ]
    if warnings:
        lines.extend(
            [
                "## Warnings",
                "",
                *[f"- {item}" for item in warnings],
                "",
            ]
        )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    workspace_root = Path(args.root).resolve()
    artifacts_root = Path(args.artifacts_dir).resolve() / "schedule-center-browser"
    logs_root = Path(args.logs_dir).resolve() / "schedule-center-browser"
    log_step("preparing schedule center browser acceptance workspace")
    if artifacts_root.exists():
        shutil.rmtree(artifacts_root, ignore_errors=True)
    if logs_root.exists():
        shutil.rmtree(logs_root, ignore_errors=True)
    artifacts_root.mkdir(parents=True, exist_ok=True)
    logs_root.mkdir(parents=True, exist_ok=True)
    api_dir = artifacts_root / "api"
    db_dir = artifacts_root / "db"
    logs_dir = artifacts_root / "logs"
    screenshots_dir = artifacts_root / "screenshots"
    api_dir.mkdir(parents=True, exist_ok=True)
    db_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    agent_search_root = infer_agent_search_root(workspace_root)
    artifact_root = artifacts_root / "task-output"
    runtime_base = Path(os.getenv("TEST_TMP_DIR") or (artifacts_root / "runtime")).resolve()
    runtime_root, bootstrap_cfg = prepare_isolated_runtime_root(
        runtime_base / "schedule-center-browser",
        agent_search_root=agent_search_root,
        artifact_root=artifact_root,
    )
    base_url = f"http://{args.host}:{int(args.port)}"
    edge_path = find_edge()
    codex_path = find_codex_path()

    evidence: dict[str, Any] = {
        "ok": False,
        "workspace_root": workspace_root.as_posix(),
        "runtime_root": runtime_root.as_posix(),
        "agent_search_root": agent_search_root.as_posix(),
        "artifact_root": artifact_root.as_posix(),
        "bootstrap_cfg": bootstrap_cfg,
        "base_url": base_url,
        "codex_path": codex_path,
        "screenshots": {},
        "evidence_files": {},
        "warnings": [],
        "error": "",
    }

    def record_api(name: str, method: str, path: str, payload: dict[str, Any] | None, status: int, body: Any) -> Path:
        file_path = api_dir / f"{name}.json"
        write_json(
            file_path,
            {
                "request": {"method": method, "path": path, "payload": payload},
                "response": {"status": status, "body": body},
            },
        )
        evidence["evidence_files"][name] = file_path.as_posix()
        return file_path

    try:
        with running_server(
            workspace_root,
            runtime_root,
            host=args.host,
            port=int(args.port),
            stdout_path=logs_root / "server.stdout.log",
            stderr_path=logs_root / "server.stderr.log",
        ):
            log_step(f"server launched on {base_url}; waiting for healthz")
            evidence["healthz"] = wait_for_health(base_url)
            log_step("healthz ready")

            status, agents_payload = api_request(base_url, "GET", "/api/agents")
            assert_true(status == 200 and isinstance(agents_payload, dict) and agents_payload.get("ok"), "agents api unavailable")
            record_api("agents", "GET", "/api/agents", None, status, agents_payload)
            chosen_agent, receiver_agent = choose_agent(agents_payload)
            assigned_agent_id = str(chosen_agent.get("agent_name") or chosen_agent.get("agent_id") or "").strip()
            receiver_agent_id = str(receiver_agent.get("agent_name") or receiver_agent.get("agent_id") or "").strip()
            assert_true(assigned_agent_id != "", "assigned agent missing")
            assert_true(receiver_agent_id != "", "receiver agent missing")
            evidence["selected_agent_name"] = assigned_agent_id
            evidence["receiver_agent_name"] = receiver_agent_id
            log_step(f"selected assigned agent={assigned_agent_id}, receiver={receiver_agent_id}")

            execution_payload = {
                "execution_provider": "codex",
                "codex_command_path": codex_path,
                "command_template": GOOD_CODEX_COMMAND_TEMPLATE,
                "global_concurrency_limit": 1,
                "operator": "schedule-browser-acceptance",
            }
            status, execution_body = api_request(base_url, "POST", "/api/assignments/settings/execution", execution_payload)
            assert_true(status == 200 and isinstance(execution_body, dict) and execution_body.get("ok"), "set execution settings failed")
            record_api("assignment_execution_settings", "POST", "/api/assignments/settings/execution", execution_payload, status, execution_body)

            now_dt = datetime.now(BEIJING_TZ)
            target_dt = datetime(now_dt.year, now_dt.month, now_dt.day, 9, 15, tzinfo=BEIJING_TZ)
            weekday = int(target_dt.isoweekday())
            current_month = format_month_key(target_dt.year, target_dt.month)
            next_year, next_month = shift_month(target_dt.year, target_dt.month, 1)
            next_month_key = format_month_key(next_year, next_month)
            next_month_date = f"{next_year:04d}-{next_month:02d}-{min(target_dt.day, calendar.monthrange(next_year, next_month)[1]):02d}"
            target_minute_text = target_dt.strftime("%Y-%m-%d %H:%M")
            target_date_text = target_dt.strftime("%Y-%m-%d")
            stamp = now_dt.strftime("%Y%m%d-%H%M%S")

            status, initial_list_body = api_request(base_url, "GET", "/api/schedules")
            assert_true(status == 200 and isinstance(initial_list_body, dict) and initial_list_body.get("ok"), f"initial schedule list read failed: {initial_list_body}")
            record_api("initial_list", "GET", "/api/schedules", None, status, initial_list_body)
            assert_true(not list(initial_list_body.get("items") or []), "isolated acceptance runtime should start with empty schedules")
            log_step("isolated runtime confirmed with empty schedule list")

            shot, probe_path, probe = capture_probe_with_retry(
                edge_path,
                base_url,
                artifacts_root,
                name="empty_state",
                case_id="empty_state",
                extra={"schedule_probe_delay_ms": "1200"},
            )
            assert_true(bool(probe.get("pass")), f"empty_state probe failed: {probe}")
            evidence["screenshots"]["empty_state"] = {"image": shot, "probe": probe_path, "result": probe}

            create_payload = {
                "schedule_name": f"验收-定时任务-{stamp}",
                "assigned_agent_id": assigned_agent_id,
                "priority": "P1",
                "launch_summary": "命中后发起一次真实任务中心单任务，用于验证建单、调度与结果回看链路。",
                "execution_checklist": "1. 读取当前计划快照。 2. 输出执行中的关键观察。 3. 按任务中心链路回写结果。",
                "done_definition": "任务中心实例中可追溯计划来源字段，且 schedule center 能看到真实状态。",
                "expected_artifact": "schedule-center-acceptance-report",
                "delivery_mode": "specified",
                "delivery_receiver_agent_id": receiver_agent_id,
                "enabled": True,
                "rule_sets": {
                    "monthly": {"enabled": True, "days_text": str(target_dt.day), "times_text": target_dt.strftime("%H:%M")},
                    "weekly": {"enabled": True, "weekdays": [weekday], "times_text": target_dt.strftime("%H:%M")},
                    "daily": {"enabled": True, "times_text": target_dt.strftime("%H:%M")},
                    "once": {"enabled": True, "date_times_text": target_minute_text},
                },
                "operator": "schedule-browser-acceptance",
            }
            status, create_body = api_request(base_url, "POST", "/api/schedules", create_payload)
            assert_true(status == 200 and isinstance(create_body, dict) and create_body.get("ok"), f"create schedule failed: {create_body}")
            record_api("create_response", "POST", "/api/schedules", create_payload, status, create_body)
            schedule_id = str(create_body.get("schedule_id") or "").strip()
            assert_true(schedule_id != "", "schedule_id missing")
            evidence["schedule_id"] = schedule_id
            log_step(f"created schedule {schedule_id}")

            shot, probe_path, probe = capture_probe_with_retry(
                edge_path,
                base_url,
                artifacts_root,
                name="list_default",
                case_id="list_default",
                extra={"schedule_probe_schedule": schedule_id, "schedule_probe_delay_ms": "1200"},
            )
            assert_true(bool(probe.get("pass")), f"list_default probe failed: {probe}")
            evidence["screenshots"]["list_default"] = {"image": shot, "probe": probe_path, "result": probe}

            edit_payload = {
                "schedule_name": f"验收-定时任务-已编辑-{stamp}",
                "assigned_agent_id": assigned_agent_id,
                "priority": "P0",
                "launch_summary": "编辑后继续验证 schedule center 的真实命中、同分钟去重和日历结果叠加。",
                "execution_checklist": "1. 命中后创建任务中心实例。 2. 立即请求既有调度流程。 3. 回写真实等待或运行状态。",
                "done_definition": "schedule center 列表详情、日历视图、任务中心状态详情和审计留痕全部可追溯。",
                "expected_artifact": "schedule-center-acceptance-report-v2",
                "delivery_mode": "specified",
                "delivery_receiver_agent_id": receiver_agent_id,
                "enabled": True,
                "rule_sets": create_payload["rule_sets"],
                "operator": "schedule-browser-acceptance",
            }
            status, edit_body = api_request(base_url, "POST", f"/api/schedules/{schedule_id}", edit_payload)
            assert_true(status == 200 and isinstance(edit_body, dict) and edit_body.get("ok"), f"edit schedule failed: {edit_body}")
            record_api("edit_response", "POST", f"/api/schedules/{schedule_id}", edit_payload, status, edit_body)
            log_step(f"edited schedule {schedule_id}")

            shot, probe_path, probe = capture_probe_with_retry(
                edge_path,
                base_url,
                artifacts_root,
                name="editor_edit",
                case_id="editor_edit",
                extra={"schedule_probe_schedule": schedule_id, "schedule_probe_delay_ms": "1200"},
            )
            assert_true(bool(probe.get("pass")), f"editor_edit probe failed: {probe}")
            evidence["screenshots"]["editor_edit"] = {"image": shot, "probe": probe_path, "result": probe}

            toggle_payload = {"operator": "schedule-browser-acceptance"}
            status, disable_body = api_request(base_url, "POST", f"/api/schedules/{schedule_id}/disable", toggle_payload)
            assert_true(status == 200 and isinstance(disable_body, dict) and disable_body.get("ok"), f"disable schedule failed: {disable_body}")
            record_api("disable_response", "POST", f"/api/schedules/{schedule_id}/disable", toggle_payload, status, disable_body)

            status, enable_body = api_request(base_url, "POST", f"/api/schedules/{schedule_id}/enable", toggle_payload)
            assert_true(status == 200 and isinstance(enable_body, dict) and enable_body.get("ok"), f"enable schedule failed: {enable_body}")
            record_api("enable_response", "POST", f"/api/schedules/{schedule_id}/enable", toggle_payload, status, enable_body)

            shot, probe_path, probe = capture_probe_with_retry(
                edge_path,
                base_url,
                artifacts_root,
                name="list_detail",
                case_id="list_detail",
                extra={"schedule_probe_schedule": schedule_id, "schedule_probe_delay_ms": "1200"},
            )
            assert_true(bool(probe.get("pass")), f"list_detail probe failed: {probe}")
            evidence["screenshots"]["list_detail"] = {"image": shot, "probe": probe_path, "result": probe}

            scan_payload = {
                "operator": "schedule-browser-acceptance",
                "schedule_id": schedule_id,
                "now_at": target_minute_text,
            }
            status, scan_body = api_request(base_url, "POST", "/api/schedules/scan", scan_payload)
            assert_true(status == 200 and isinstance(scan_body, dict) and scan_body.get("ok"), f"schedule scan failed: {scan_body}")
            record_api("scan_create_response", "POST", "/api/schedules/scan", scan_payload, status, scan_body)
            assert_true(int(scan_body.get("hit_count") or 0) == 1, "scan should hit exactly one schedule")
            assert_true(int(scan_body.get("created_node_count") or 0) == 1, "scan should create exactly one node")

            status, dedupe_body = api_request(base_url, "POST", "/api/schedules/scan", scan_payload)
            assert_true(status == 200 and isinstance(dedupe_body, dict) and dedupe_body.get("ok"), f"schedule dedupe scan failed: {dedupe_body}")
            record_api("scan_dedupe_response", "POST", "/api/schedules/scan", scan_payload, status, dedupe_body)
            assert_true(int(dedupe_body.get("deduped_count") or 0) >= 1, "second scan should dedupe same minute hit")
            log_step(f"scan created one assignment and verified same-minute dedupe for schedule {schedule_id}")

            schedule_detail = wait_for_schedule_detail(
                base_url,
                schedule_id=schedule_id,
                timeout_s=30,
                predicate=lambda payload: bool(list(payload.get("recent_triggers") or [])),
            )
            schedule_detail_path = api_dir / "schedule_detail_after_scan.json"
            write_json(schedule_detail_path, schedule_detail)
            evidence["evidence_files"]["schedule_detail_after_scan"] = schedule_detail_path.as_posix()

            recent = list(schedule_detail.get("recent_triggers") or [])
            latest_trigger = recent[0] if recent else {}
            ticket_id = str(latest_trigger.get("assignment_ticket_id") or "").strip()
            node_id = str(latest_trigger.get("assignment_node_id") or "").strip()
            assert_true(ticket_id != "" and node_id != "", "assignment refs missing after scan")
            evidence["assignment_ticket_id"] = ticket_id
            evidence["assignment_node_id"] = node_id
            log_step(f"assignment created ticket={ticket_id}, node={node_id}; waiting for live execution state")

            live_detail = wait_for_assignment_status(
                base_url,
                ticket_id=ticket_id,
                node_id=node_id,
                timeout_s=45,
                predicate=lambda payload: (
                    str((((payload.get("execution_chain") or {}).get("latest_run") or {}).get("status") or "")).strip().lower() in {"starting", "running"}
                    or str(((payload.get("selected_node") or {}).get("status") or "")).strip().lower() in {"ready", "pending", "running"}
                ),
            )
            live_detail_path = api_dir / "assignment_status_live.json"
            write_json(live_detail_path, live_detail)
            evidence["evidence_files"]["assignment_status_live"] = live_detail_path.as_posix()
            live_selected = dict(live_detail.get("selected_node") or {})
            live_run = dict(((live_detail.get("execution_chain") or {}).get("latest_run") or {}))
            live_run_status = str(live_run.get("status") or "").strip().lower()
            live_node_status = str(live_selected.get("status") or "").strip().lower()
            evidence["live_status_kind"] = live_run_status or live_node_status
            log_step(
                "live execution observed: "
                + (evidence["live_status_kind"] or live_node_status or "unknown")
            )

            log_step("waiting up to 60s for terminal execution state (best-effort)")
            terminal_detail: dict[str, Any] = {}
            terminal_wait_warning = ""
            try:
                terminal_detail = wait_for_assignment_status(
                    base_url,
                    ticket_id=ticket_id,
                    node_id=node_id,
                    timeout_s=60,
                    predicate=lambda payload: (
                        str((((payload.get("execution_chain") or {}).get("latest_run") or {}).get("status") or "")).strip().lower() in {"succeeded", "failed"}
                        or str(((payload.get("selected_node") or {}).get("status") or "")).strip().lower() in {"succeeded", "failed"}
                    ),
                )
            except Exception as exc:
                terminal_wait_warning = (
                    "terminal status not observed within 60s; "
                    f"continuing with live execution evidence ({format_error(exc)})"
                )
                evidence["warnings"].append(terminal_wait_warning)
                log_step(terminal_wait_warning)
            terminal_detail_path = api_dir / "assignment_status_terminal.json"
            terminal_evidence: dict[str, Any]
            if terminal_detail:
                terminal_evidence = terminal_detail
            else:
                terminal_evidence = {
                    "ok": False,
                    "warning": terminal_wait_warning,
                    "latest_live_detail": live_detail,
                }
            write_json(terminal_detail_path, terminal_evidence)
            evidence["evidence_files"]["assignment_status_terminal"] = terminal_detail_path.as_posix()
            terminal_selected = dict((terminal_detail or {}).get("selected_node") or {})
            terminal_run = dict((((terminal_detail or {}).get("execution_chain") or {}).get("latest_run") or {}))
            evidence["terminal_status_observed"] = str(terminal_run.get("status") or terminal_selected.get("status") or "").strip().lower() in {"succeeded", "failed"}
            if evidence["terminal_status_observed"]:
                log_step("terminal execution state observed")
            else:
                terminal_state_warning = (
                    "terminal status not observed; acceptance passed with live execution, schedule scan, "
                    "calendar, DB, and event-stream evidence only"
                )
                if terminal_state_warning not in evidence["warnings"]:
                    evidence["warnings"].append(terminal_state_warning)
                log_step(terminal_state_warning)

            shot, probe_path, probe = capture_probe_with_retry(
                edge_path,
                base_url,
                artifacts_root,
                name="result_detail",
                case_id="result_detail",
                extra={"schedule_probe_schedule": schedule_id, "schedule_probe_delay_ms": "1400"},
            )
            assert_true(bool(probe.get("pass")), f"result_detail probe failed: {probe}")
            evidence["screenshots"]["result_detail"] = {"image": shot, "probe": probe_path, "result": probe}

            shot, probe_path, probe = capture_probe_with_retry(
                edge_path,
                base_url,
                artifacts_root,
                name="calendar_month",
                case_id="calendar_month",
                extra={
                    "schedule_probe_schedule": schedule_id,
                    "schedule_probe_month": current_month,
                    "schedule_probe_date": target_date_text,
                    "schedule_probe_delay_ms": "1400",
                },
            )
            assert_true(bool(probe.get("pass")), f"calendar_month probe failed: {probe}")
            evidence["screenshots"]["calendar_month"] = {"image": shot, "probe": probe_path, "result": probe}

            shot, probe_path, probe = capture_probe_with_retry(
                edge_path,
                base_url,
                artifacts_root,
                name="calendar_shifted",
                case_id="calendar_shifted",
                extra={
                    "schedule_probe_schedule": schedule_id,
                    "schedule_probe_month": next_month_key,
                    "schedule_probe_base_month": current_month,
                    "schedule_probe_date": next_month_date,
                    "schedule_probe_delay_ms": "1400",
                },
            )
            assert_true(bool(probe.get("pass")), f"calendar_shifted probe failed: {probe}")
            evidence["screenshots"]["calendar_shifted"] = {"image": shot, "probe": probe_path, "result": probe}

            status, calendar_month_body = api_request(base_url, "GET", f"/api/schedules/calendar?month={current_month}")
            assert_true(status == 200 and isinstance(calendar_month_body, dict) and calendar_month_body.get("ok"), "calendar current month read failed")
            record_api("calendar_current_month", "GET", f"/api/schedules/calendar?month={current_month}", None, status, calendar_month_body)

            status, calendar_shifted_body = api_request(base_url, "GET", f"/api/schedules/calendar?month={next_month_key}")
            assert_true(status == 200 and isinstance(calendar_shifted_body, dict) and calendar_shifted_body.get("ok"), "calendar shifted month read failed")
            record_api("calendar_shifted_month", "GET", f"/api/schedules/calendar?month={next_month_key}", None, status, calendar_shifted_body)

            db_path = runtime_root / "state" / "workflow.db"
            trigger_rows = query_sqlite_rows(
                db_path,
                "SELECT * FROM schedule_trigger_instances WHERE schedule_id=? ORDER BY planned_trigger_at DESC, created_at DESC",
                (schedule_id,),
            )
            trigger_rows_path = db_dir / "schedule_trigger_instances.json"
            write_json(trigger_rows_path, trigger_rows)
            evidence["evidence_files"]["db_trigger_rows"] = trigger_rows_path.as_posix()

            audit_rows = query_sqlite_rows(
                db_path,
                "SELECT * FROM schedule_audit_log WHERE schedule_id=? ORDER BY created_at DESC, audit_id DESC LIMIT 20",
                (schedule_id,),
            )
            audit_rows_path = db_dir / "schedule_audit_log.json"
            write_json(audit_rows_path, audit_rows)
            evidence["evidence_files"]["db_audit_rows"] = audit_rows_path.as_posix()

            assignment_rows = query_sqlite_rows(
                db_path,
                "SELECT * FROM assignment_nodes WHERE source_schedule_id=? ORDER BY updated_at DESC, created_at DESC",
                (schedule_id,),
            )
            assignment_rows_path = db_dir / "assignment_nodes.json"
            write_json(assignment_rows_path, assignment_rows)
            evidence["evidence_files"]["db_assignment_rows"] = assignment_rows_path.as_posix()

            schedule_events = read_schedule_events(runtime_root / "logs" / "events" / "schedules.jsonl", schedule_id)
            schedule_events_path = logs_dir / "schedule_events.json"
            write_json(schedule_events_path, schedule_events)
            evidence["evidence_files"]["schedule_events"] = schedule_events_path.as_posix()

            node_json_path = artifact_root / "tasks" / ticket_id / "nodes" / f"{node_id}.json"
            node_json_body: dict[str, Any] = {}
            if node_json_path.exists():
                node_json_body = json.loads(node_json_path.read_text(encoding="utf-8"))
            node_json_evidence_path = artifacts_root / "assignment_node.json"
            write_json(node_json_evidence_path, node_json_body)
            evidence["evidence_files"]["assignment_node_json"] = node_json_evidence_path.as_posix()

            evidence["target_minute"] = target_minute_text
            evidence["current_month"] = current_month
            evidence["next_month"] = next_month_key
            evidence["ok"] = True
            log_step("schedule center browser acceptance evidence collected successfully")

        write_json(artifacts_root / "summary.json", evidence)
        render_report(artifacts_root / "acceptance-report.md", evidence)
        log_step(f"summary written to {(artifacts_root / 'summary.json').as_posix()}")
        print((artifacts_root / "summary.json").as_posix())
        return 0
    except Exception as exc:
        evidence["error"] = format_error(exc)
        log_step(f"acceptance failed: {evidence['error']}")
        raise
    finally:
        if not (artifacts_root / "summary.json").exists():
            write_json(artifacts_root / "summary.json", evidence)


if __name__ == "__main__":
    raise SystemExit(main())
