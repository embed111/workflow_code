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
DEFAULT_MEMORY_SPEC = """# Memory Spec

## Purpose
- Keep `.codex/*` as memory and internal guidance, not runtime state.
- Append current-round summaries into daily memory files only.
"""


def write_role_creation_codex_stub(bin_dir: Path) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    script_path = bin_dir / "codex_stub.py"
    cmd_path = bin_dir / "codex.cmd"
    script_path.write_text(
        "\n".join(
            [
                "import json",
                "import os",
                "import re",
                "import sys",
                "import time",
                "",
                "prompt = sys.stdin.read()",
                "is_assignment_prompt = 'artifact_markdown' in prompt or '执行要求：' in prompt",
                "",
                "def extract_json_line(label, default=None):",
                "    matched = re.search(r'^\\s*[-]\\s*' + re.escape(label) + r'\\s*:\\s*(.+)$', prompt, flags=re.M)",
                "    if not matched:",
                "        return default",
                "    raw = matched.group(1).strip()",
                "    try:",
                "        return json.loads(raw)",
                "    except Exception:",
                "        return raw.strip('\"')",
                "",
                "def emit(payload):",
                "    print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(payload, ensure_ascii=False)}}, ensure_ascii=False))",
                "",
                "def emit_turn_completed():",
                "    print(json.dumps({'type': 'turn.completed', 'message': 'stub turn completed'}, ensure_ascii=False))",
                "",
                "latest_user_message = str(extract_json_line('latest_user_message', '') or '')",
                "session_id = str(extract_json_line('session_id', '') or '')",
                "session_status = str(extract_json_line('session_status', '') or '').strip().lower()",
                "current_stage_key = str(extract_json_line('current_stage_key', 'persona_collection') or 'persona_collection').strip().lower() or 'persona_collection'",
                "can_start = bool(extract_json_line('can_start', False))",
                "missing_fields = extract_json_line('missing_fields', [])",
                "if not isinstance(missing_fields, list):",
                "    missing_fields = []",
                "state_dir = str(os.getenv('WORKFLOW_ROLE_CREATION_STUB_STATE_DIR') or '').strip()",
                "failure_marker = ''",
                "if state_dir:",
                "    os.makedirs(state_dir, exist_ok=True)",
                "    failure_marker = os.path.join(state_dir, re.sub(r'[^A-Za-z0-9._-]+', '_', session_id or 'session') + '.fail_once')",
                "",
                "if is_assignment_prompt:",
                "    node_name = ''",
                "    matched_node = re.search(r'^\\s*-\\s*node_name\\s*:\\s*(.+)$', prompt, flags=re.M)",
                "    if matched_node:",
                "        node_name = matched_node.group(1).strip()",
                "    artifact_label = (node_name or '任务产物').replace('/', '-').replace('\\\\', '-') + '.html'",
                "    artifact_markdown = '\\n'.join([",
                "        '# ' + (node_name or '任务产物'),",
                "        '',",
                "        '这是浏览器验收 stub 自动生成的交付内容。',",
                "        '',",
                "        '## 结果摘要',",
                "        '当前任务已通过本地 stub 返回结构化结果，用于验证 workflow 的调度、回写与展示链路。',",
                "    ])",
                "    emit({",
                "        'result_summary': (node_name or '任务') + ' 已按验收 stub 完成。',",
                "        'artifact_label': artifact_label,",
                "        'artifact_markdown': artifact_markdown,",
                "        'artifact_files': [],",
                "        'warnings': [],",
                "    })",
                "    emit_turn_completed()",
                "    raise SystemExit(0)",
                "",
                "time.sleep(1.8)",
                "if '模拟失败' in latest_user_message or '模拟失败' in prompt:",
                "    if failure_marker and not os.path.exists(failure_marker):",
                "        with open(failure_marker, 'w', encoding='utf-8') as fh:",
                "            fh.write('failed')",
                "        sys.stderr.write('simulated role creation failure')",
                "        raise SystemExit(17)",
                "",
                "delegate_tasks = []",
                "suggested_stage_key = current_stage_key",
                "assistant_reply = '信息已收到。我会继续按当前阶段收口角色画像，如需我拆后台任务，直接说明要补什么和希望回传什么产物。'",
                "",
                "if any(token in latest_user_message for token in ['另起一个任务', '后台去做', '回传预览', '补行业案例', '补竞品案例']):",
                "    if any(token in latest_user_message for token in ['回传', '预览', '截图']):",
                "        task_stage = 'review_and_alignment'",
                "    elif any(token in latest_user_message for token in ['案例', '竞品', '行业']):",
                "        task_stage = 'persona_collection'",
                "    else:",
                "        task_stage = 'capability_generation'",
                "    task_title = '补充行业案例并回传预览' if '行业' in latest_user_message else ('补充竞品案例并回传预览' if '竞品' in latest_user_message else '补充任务并回传预览')",
                "    task_goal = latest_user_message.replace('另起一个任务去', '').strip() or '补充资料并回传预览。'",
                "    delegate_tasks = [{",
                "        'title': task_title,",
                "        'goal': task_goal,",
                "        'stage_key': task_stage,",
                "        'expected_artifact': task_title + '.html',",
                "        'priority': 'P1',",
                "    }]",
                "    suggested_stage_key = task_stage",
                "    assistant_reply = '已记录这条后台任务，主线角色画像会继续保留在当前会话里，等任务回传后再一起对齐。'",
                "elif can_start:",
                "    suggested_stage_key = 'capability_generation'",
                "    assistant_reply = '角色画像已经收口：目标、核心能力、边界、适用场景和协作方式都已明确。下一步可以进入能力展开与交付样例整理。'",
                "",
                "emit({",
                "    'assistant_reply': assistant_reply,",
                "    'delegate_tasks': delegate_tasks,",
                "    'suggested_stage_key': suggested_stage_key,",
                "    'ready_to_start': bool(can_start) and not bool(missing_fields),",
                "    'missing_fields': [str(item).strip() for item in missing_fields if str(item).strip()],",
                "    'reasoning_summary': 'acceptance_stub',",
                "})",
                "emit_turn_completed()",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    cmd_path.write_text("@echo off\r\n" + f"\"{sys.executable}\" \"{script_path.as_posix()}\" %*\r\n", encoding="utf-8")
    return cmd_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Browser acceptance for training center role creation workbench.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8143)
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


def api_request(base_url: str, method: str, route: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    payload = None
    headers = {"Accept": "application/json"}
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(base_url + route, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            content_type = str(response.headers.get("Content-Type") or "")
            if "application/json" in content_type:
                return int(response.status), read_json_response(response)
            return int(response.status), response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        content_type = str(exc.headers.get("Content-Type") or "")
        if "application/json" in content_type:
            return int(exc.code), read_json_response(exc)
        return int(exc.code), exc.read().decode("utf-8")


def wait_for_health(base_url: str, timeout_s: float = 90.0) -> dict[str, Any]:
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


def wait_for_role_creation_idle(base_url: str, session_id: str, timeout_s: float = 120.0) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last_payload: dict[str, Any] = {}
    while time.time() < deadline:
        status, data = api_request(base_url, "GET", f"/api/training/role-creation/sessions/{session_id}")
        if status == 200 and isinstance(data, dict) and data.get("ok"):
            last_payload = data
            session = data.get("session") or {}
            queue_status = str(session.get("message_processing_status") or "").strip().lower()
            try:
                unhandled = int(session.get("unhandled_user_message_count") or 0)
            except Exception:
                unhandled = 0
            if queue_status in {"", "idle"} and unhandled <= 0:
                return data
        time.sleep(1)
    raise RuntimeError(
        "role creation idle timeout: "
        + json.dumps(
            {
                "session_id": session_id,
                "last_status": (last_payload.get("session") or {}).get("message_processing_status"),
                "last_unhandled": (last_payload.get("session") or {}).get("unhandled_user_message_count"),
            },
            ensure_ascii=False,
        )
    )


def wait_for_role_creation_failed(base_url: str, session_id: str, timeout_s: float = 120.0) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last_payload: dict[str, Any] = {}
    while time.time() < deadline:
        status, data = api_request(base_url, "GET", f"/api/training/role-creation/sessions/{session_id}")
        if status == 200 and isinstance(data, dict) and data.get("ok"):
            last_payload = data
            session = data.get("session") or {}
            if str(session.get("message_processing_status") or "").strip().lower() == "failed":
                return data
        time.sleep(1)
    raise RuntimeError(
        "role creation failed timeout: "
        + json.dumps(
            {
                "session_id": session_id,
                "last_status": (last_payload.get("session") or {}).get("message_processing_status"),
                "last_error": (last_payload.get("session") or {}).get("message_processing_error"),
            },
            ensure_ascii=False,
        )
    )


def wait_for_role_creation_started(base_url: str, session_id: str, timeout_s: float = 240.0) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last_payload: dict[str, Any] = {}
    while time.time() < deadline:
        status, data = api_request(base_url, "GET", f"/api/training/role-creation/sessions/{session_id}")
        if status == 200 and isinstance(data, dict) and data.get("ok"):
            last_payload = data
            session = data.get("session") or {}
            if (
                str(session.get("status") or "").strip().lower() == "creating"
                and str(session.get("assignment_ticket_id") or "").strip()
                and str(session.get("workspace_init_ref") or "").strip()
            ):
                return data
        time.sleep(1)
    raise RuntimeError(
        "role creation start timeout: "
        + json.dumps(
            {
                "session_id": session_id,
                "last_status": (last_payload.get("session") or {}).get("status"),
                "last_stage": (last_payload.get("session") or {}).get("current_stage_key"),
                "last_ticket_id": (last_payload.get("session") or {}).get("assignment_ticket_id"),
                "last_workspace_init_ref": (last_payload.get("session") or {}).get("workspace_init_ref"),
            },
            ensure_ascii=False,
        )
    )


def allow_async_writes_to_settle(delay_s: float = 3.0) -> None:
    time.sleep(max(0.2, float(delay_s)))


def find_edge() -> Path:
    candidates = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    for path in candidates:
        if path.exists() and path.is_file():
            return path
    raise RuntimeError("msedge not found")


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
    profile_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(edge_path),
        "--headless=new",
        "--disable-gpu",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-sync",
        "--no-first-run",
        "--no-default-browser-check",
        f"--user-data-dir={profile_dir.as_posix()}",
        f"--window-size={width},{height}",
        f"--virtual-time-budget={max(1000, int(budget_ms))}",
        f"--screenshot={shot_path.as_posix()}",
        url,
    ]
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
    profile_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(edge_path),
        "--headless=new",
        "--disable-gpu",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-sync",
        "--no-first-run",
        "--no-default-browser-check",
        f"--user-data-dir={profile_dir.as_posix()}",
        f"--window-size={width},{height}",
        f"--virtual-time-budget={max(1000, int(budget_ms))}",
        "--dump-dom",
        url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=180)
    if proc.returncode != 0:
        raise RuntimeError(f"edge dump-dom failed: {proc.stderr}")
    return proc.stdout


def parse_probe(dom_text: str) -> dict[str, Any]:
    matched = re.search(
        r"<pre[^>]*id=['\"]trainingCenterProbeOutput['\"][^>]*>(.*?)</pre>",
        str(dom_text or ""),
        flags=re.I | re.S,
    )
    if not matched:
        raise RuntimeError("trainingCenterProbeOutput_not_found")
    raw = html.unescape(matched.group(1) or "").strip()
    if not raw:
        raise RuntimeError("trainingCenterProbeOutput_empty")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError("trainingCenterProbeOutput_not_dict")
    return payload


def tc_probe_url(base_url: str, case_id: str, extra: dict[str, str] | None = None) -> str:
    query: dict[str, str] = {
        "tc_probe": "1",
        "tc_probe_case": str(case_id),
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
    *,
    budget_ms: int = 26000,
) -> tuple[str, str, dict[str, Any]]:
    url = tc_probe_url(base_url, case_id, extra)
    shot_path = evidence_root / "screenshots" / f"{name}.png"
    probe_path = evidence_root / "screenshots" / f"{name}.probe.json"
    profile_dir = evidence_root / "edge-profile" / name
    budgets = [budget_ms]
    if budget_ms < 60000:
        budgets.append(60000)
    last_error: Exception | None = None
    probe: dict[str, Any] | None = None
    for current_budget_ms in budgets:
        edge_shot(edge_path, url, shot_path, profile_dir=profile_dir, budget_ms=current_budget_ms)
        try:
            probe = parse_probe(edge_dom(edge_path, url, profile_dir=profile_dir, budget_ms=current_budget_ms))
            break
        except RuntimeError as exc:
            last_error = exc
    if probe is None:
        raise last_error or RuntimeError("trainingCenterProbeOutput_not_found")
    write_json(probe_path, probe)
    return shot_path.as_posix(), probe_path.as_posix(), probe


def launch_server(
    repo_root: Path,
    runtime_root: Path,
    *,
    host: str,
    port: int,
    stdout_path: Path,
    stderr_path: Path,
    env: dict[str, str] | None = None,
) -> tuple[subprocess.Popen[bytes], Any, Any]:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_handle = stdout_path.open("wb")
    stderr_handle = stderr_path.open("wb")
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
        cwd=str(repo_root),
        stdout=stdout_handle,
        stderr=stderr_handle,
        env=env or os.environ.copy(),
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
    repo_root: Path,
    runtime_root: Path,
    *,
    host: str,
    port: int,
    stdout_path: Path,
    stderr_path: Path,
    env: dict[str, str] | None = None,
) -> Iterator[None]:
    server, stdout_handle, stderr_handle = launch_server(
        repo_root,
        runtime_root,
        host=host,
        port=port,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        env=env,
    )
    try:
        yield
    finally:
        stop_server(server, stdout_handle, stderr_handle)


def record_api(
    api_dir: Path,
    *,
    stage: str,
    name: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None,
    status: int,
    body: Any,
) -> str:
    file_path = api_dir / f"{stage}-{name}.json"
    write_json(
        file_path,
        {
            "request": {"method": method, "path": path, "payload": payload},
            "response": {"status": status, "body": body},
        },
    )
    return file_path.as_posix()


def prepare_runtime_root(repo_root: Path, runtime_root: Path) -> Path:
    if runtime_root.exists():
        shutil.rmtree(runtime_root, ignore_errors=True)
    for rel in (".codex", "scripts", "agents", "logs/runs", "state"):
        (runtime_root / rel).mkdir(parents=True, exist_ok=True)
    memory_spec_source = repo_root / ".codex" / "MEMORY.md"
    memory_spec_target = runtime_root / ".codex" / "MEMORY.md"
    if memory_spec_source.exists():
        shutil.copy2(memory_spec_source, memory_spec_target)
    else:
        memory_spec_target.write_text(DEFAULT_MEMORY_SPEC, encoding="utf-8")
    shutil.copy2(repo_root / "scripts" / "manage_codex_memory.py", runtime_root / "scripts" / "manage_codex_memory.py")
    return runtime_root


def role_message_text(role_name: str) -> str:
    return (
        f"角色名是{role_name}。"
        "角色目标是把复杂增长问题收口成结构化诊断、实验建议和复盘摘要。"
        "核心能力有问题拆解、漏斗分析、实验设计、复盘摘要。"
        "能力模块：问题拆解 / 漏斗诊断 / 实验设计 / 复盘摘要。"
        "知识沉淀：诊断方法说明、诊断模板、最小示例、反例、验收清单。"
        "边界是不写代码、不直接改数据库。"
        "适用场景是增长复盘、投放问题排查、转化漏斗优化。"
        "协作方式是先给结构化结论，再给证据和建议。"
    )


def role_message_supplement_text() -> str:
    return (
        "默认交付策略：默认先回传结构化诊断摘要和可执行清单，再补完整说明。"
        "格式边界：HTML 为主，Markdown / JSON 为辅，不输出 SVG。"
        "首批优先顺序：先覆盖漏斗诊断，再出实验设计模板，最后整理复盘清单。"
        "首批任务：先沉淀诊断模板和验收清单，再生成首批能力对象。"
    )


def image_attachment_payload(file_name: str) -> list[dict[str, Any]]:
    return [
        {
            "attachment_id": "probe-image-1",
            "kind": "image",
            "file_name": file_name,
            "content_type": "image/png",
            "size_bytes": 68,
            "data_url": IMAGE_DATA_URL,
        }
    ]


def role_task_ids(detail: dict[str, Any]) -> list[str]:
    return [
        str(item.get("node_id") or "").strip()
        for item in list(detail.get("task_refs") or [])
        if str(item.get("node_id") or "").strip()
    ]


def role_stage_task_ids(detail: dict[str, Any], stage_key: str, *, archived: bool = False) -> list[str]:
    ids: list[str] = []
    for stage in list(detail.get("stages") or []):
        if str(stage.get("stage_key") or "").strip() != stage_key:
            continue
        items = stage.get("archived_tasks") if archived else stage.get("active_tasks")
        for item in list(items or []):
            node_id = str(item.get("node_id") or "").strip()
            if node_id:
                ids.append(node_id)
    return ids


def capture_required_probe(
    edge_path: Path,
    base_url: str,
    evidence_root: Path,
    name: str,
    case_id: str,
    extra: dict[str, str] | None,
) -> dict[str, Any]:
    shot, probe_file, probe = capture_probe(edge_path, base_url, evidence_root, name, case_id, extra)
    assert_true(bool(probe.get("pass")), f"probe failed for {case_id}: {probe}")
    return {"image": shot, "probe": probe_file, "result": probe}


def main() -> int:
    args = parse_args()
    repo_root = Path(args.root).resolve()
    artifacts_dir = Path(args.artifacts_dir).resolve()
    logs_dir = Path(args.logs_dir).resolve()
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    evidence_root = artifacts_dir / "role-creation-browser-acceptance"
    log_root = logs_dir / "role-creation-browser-acceptance"
    if evidence_root.exists():
        shutil.rmtree(evidence_root, ignore_errors=True)
    if log_root.exists():
        shutil.rmtree(log_root, ignore_errors=True)
    api_dir = evidence_root / "api"
    shots_dir = evidence_root / "screenshots"
    api_dir.mkdir(parents=True, exist_ok=True)
    shots_dir.mkdir(parents=True, exist_ok=True)
    log_root.mkdir(parents=True, exist_ok=True)
    runtime_stamp = time.strftime("%Y%m%d-%H%M%S")
    runtime_base = Path(os.getenv("TEST_TMP_DIR") or (repo_root / ".test" / "runtime")).resolve()
    runtime_root = prepare_runtime_root(repo_root, runtime_base / f"role-creation-browser-acceptance-{runtime_stamp}")
    stub_bin = runtime_root / "bin"
    stub_cmd = write_role_creation_codex_stub(stub_bin)
    server_env = os.environ.copy()
    server_env["PATH"] = stub_bin.as_posix() + os.pathsep + server_env.get("PATH", "")
    server_env["WORKFLOW_ROLE_CREATION_CODEX_BIN"] = stub_cmd.as_posix()
    server_env["WORKFLOW_ROLE_CREATION_STUB_STATE_DIR"] = (runtime_root / "stub-state").as_posix()
    base_url = f"http://{args.host}:{args.port}"
    edge_path = find_edge()

    sys.path.insert(0, str(repo_root / "src"))
    from workflow_app.server.bootstrap import web_server_runtime as ws  # type: ignore
    from workflow_app.server.infra.db.migrations import ensure_tables  # type: ignore

    ensure_tables(runtime_root)
    ws.bind_training_center_runtime_once()

    evidence: dict[str, Any] = {
        "repo_root": str(repo_root),
        "runtime_root": str(runtime_root),
        "base_url": base_url,
        "edge_path": str(edge_path),
        "codex_stub": str(stub_cmd),
        "api": {},
        "screenshots": {},
        "sessions": {},
        "assertions": {},
    }
    operator = "role-creation-browser-acceptance"

    try:
        with running_server(
            repo_root,
            runtime_root,
            host=args.host,
            port=args.port,
            stdout_path=log_root / "server.stdout.log",
            stderr_path=log_root / "server.stderr.log",
            env=server_env,
        ):
            evidence["healthz"] = wait_for_health(base_url)

            agent_root = (runtime_root / "workspace-root").resolve()
            (agent_root / "workflow").mkdir(parents=True, exist_ok=True)
            artifact_root = (evidence_root / "task-output").resolve()
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

            assignment_settings_payload = {
                "execution_provider": "codex",
                "codex_command_path": stub_cmd.as_posix(),
                "command_template": "",
                "global_concurrency_limit": 1,
                "operator": operator,
            }
            status, body = api_request(
                base_url,
                "POST",
                "/api/assignments/settings/execution",
                assignment_settings_payload,
            )
            assert_true(status == 200 and isinstance(body, dict) and body.get("ok"), "configure assignment execution failed")
            evidence["api"]["configure_assignment_execution"] = record_api(
                api_dir,
                stage="setup",
                name="configure_assignment_execution",
                method="POST",
                path="/api/assignments/settings/execution",
                payload=assignment_settings_payload,
                status=status,
                body=body,
            )

            default_create_payload = {"session_title": "浏览器默认视图草稿", "operator": operator}
            status, default_create = api_request(base_url, "POST", "/api/training/role-creation/sessions", default_create_payload)
            assert_true(status == 200 and isinstance(default_create, dict) and default_create.get("ok"), "default create session failed")
            evidence["api"]["default_create_session"] = record_api(
                api_dir,
                stage="default",
                name="create_session",
                method="POST",
                path="/api/training/role-creation/sessions",
                payload=default_create_payload,
                status=status,
                body=default_create,
            )
            default_session_id = str((default_create.get("session") or {}).get("session_id") or "").strip()
            assert_true(default_session_id, "default session_id missing")
            evidence["sessions"]["default"] = {"session_id": default_session_id}

            main_role_name = "增长分析师浏览器验收主线"
            main_create_payload = {"session_title": "主线角色创建验收", "operator": operator}
            status, main_create = api_request(base_url, "POST", "/api/training/role-creation/sessions", main_create_payload)
            assert_true(status == 200 and isinstance(main_create, dict) and main_create.get("ok"), "main create session failed")
            evidence["api"]["main_create_session"] = record_api(
                api_dir,
                stage="main",
                name="create_session",
                method="POST",
                path="/api/training/role-creation/sessions",
                payload=main_create_payload,
                status=status,
                body=main_create,
            )
            main_session_id = str((main_create.get("session") or {}).get("session_id") or "").strip()
            assert_true(main_session_id, "main session_id missing")

            main_message_payload = {
                "content": role_message_text(main_role_name),
                "attachments": image_attachment_payload("growth-main.png"),
                "operator": operator,
            }
            status, main_message = api_request(
                base_url,
                "POST",
                f"/api/training/role-creation/sessions/{main_session_id}/messages",
                main_message_payload,
            )
            assert_true(status == 200 and isinstance(main_message, dict) and main_message.get("ok"), "main message post failed")
            evidence["api"]["main_message_with_image"] = record_api(
                api_dir,
                stage="main",
                name="message_with_image",
                method="POST",
                path=f"/api/training/role-creation/sessions/{main_session_id}/messages",
                payload=main_message_payload,
                status=status,
                body=main_message,
            )
            main_message_ready = wait_for_role_creation_idle(base_url, main_session_id)
            evidence["api"]["main_message_idle"] = record_api(
                api_dir,
                stage="main",
                name="message_idle",
                method="GET",
                path=f"/api/training/role-creation/sessions/{main_session_id}",
                payload=None,
                status=200,
                body=main_message_ready,
            )
            main_supplement_payload = {
                "content": role_message_supplement_text(),
                "operator": operator,
            }
            status, main_supplement = api_request(
                base_url,
                "POST",
                f"/api/training/role-creation/sessions/{main_session_id}/messages",
                main_supplement_payload,
            )
            assert_true(status == 200 and isinstance(main_supplement, dict) and main_supplement.get("ok"), "main supplement post failed")
            evidence["api"]["main_message_supplement"] = record_api(
                api_dir,
                stage="main",
                name="message_supplement",
                method="POST",
                path=f"/api/training/role-creation/sessions/{main_session_id}/messages",
                payload=main_supplement_payload,
                status=status,
                body=main_supplement,
            )
            evidence["screenshots"]["analysis_progress"] = capture_required_probe(
                edge_path,
                base_url,
                evidence_root,
                "rc_analysis_progress",
                "rc_profile_tab",
                {"tc_probe_session": main_session_id},
            )
            main_supplement_ready = wait_for_role_creation_idle(base_url, main_session_id)
            evidence["api"]["main_message_supplement_idle"] = record_api(
                api_dir,
                stage="main",
                name="message_supplement_idle",
                method="GET",
                path=f"/api/training/role-creation/sessions/{main_session_id}",
                payload=None,
                status=200,
                body=main_supplement_ready,
            )

            main_start_payload = {"operator": operator}
            status, main_start = api_request(
                base_url,
                "POST",
                f"/api/training/role-creation/sessions/{main_session_id}/start",
                main_start_payload,
            )
            evidence["api"]["main_start_session"] = record_api(
                api_dir,
                stage="main",
                name="start_session",
                method="POST",
                path=f"/api/training/role-creation/sessions/{main_session_id}/start",
                payload=main_start_payload,
                status=status,
                body=main_start,
            )
            assert_true(status == 200 and isinstance(main_start, dict) and main_start.get("ok"), "main start failed")
            main_ticket_id = str((main_start.get("session") or {}).get("assignment_ticket_id") or "").strip()
            main_workspace_init_ref = str((main_start.get("session") or {}).get("workspace_init_ref") or "").strip()
            assert_true(main_ticket_id, "main ticket_id missing")
            assert_true(main_workspace_init_ref, "main workspace init ref missing")
            assert_true((runtime_root / main_workspace_init_ref).exists(), "workspace init evidence missing on disk")
            allow_async_writes_to_settle()

            status, main_detail_started = api_request(
                base_url,
                "GET",
                f"/api/training/role-creation/sessions/{main_session_id}",
            )
            assert_true(status == 200 and isinstance(main_detail_started, dict) and main_detail_started.get("ok"), "main detail fetch failed")
            evidence["api"]["main_detail_started"] = record_api(
                api_dir,
                stage="main",
                name="detail_started",
                method="GET",
                path=f"/api/training/role-creation/sessions/{main_session_id}",
                payload=None,
                status=status,
                body=main_detail_started,
            )
            main_task_ids_before_delegate = set(role_task_ids(main_detail_started))
            main_delegate_payload = {"content": "另起一个任务去补行业案例并回传预览。", "operator": operator}
            status, main_delegate = api_request(
                base_url,
                "POST",
                f"/api/training/role-creation/sessions/{main_session_id}/messages",
                main_delegate_payload,
            )
            assert_true(status == 200 and isinstance(main_delegate, dict) and main_delegate.get("ok"), "main delegate message failed")
            evidence["api"]["main_explicit_delegate"] = record_api(
                api_dir,
                stage="main",
                name="explicit_delegate",
                method="POST",
                path=f"/api/training/role-creation/sessions/{main_session_id}/messages",
                payload=main_delegate_payload,
                status=status,
                body=main_delegate,
            )
            main_delegate_ready = wait_for_role_creation_idle(base_url, main_session_id)
            evidence["api"]["main_explicit_delegate_idle"] = record_api(
                api_dir,
                stage="main",
                name="explicit_delegate_idle",
                method="GET",
                path=f"/api/training/role-creation/sessions/{main_session_id}",
                payload=None,
                status=200,
                body=main_delegate_ready,
            )
            main_delegate_task_ids = sorted(set(role_task_ids(main_delegate_ready)) - main_task_ids_before_delegate)
            assert_true(bool(main_delegate_task_ids), "main delegate task ids missing")
            main_delegate_task_id = main_delegate_task_ids[0]

            main_stage_task_ids = [
                str(item.get("node_id") or "").strip()
                for stage in list(main_delegate_ready.get("stages") or [])
                for item in list(stage.get("active_tasks") or [])
                if str(item.get("node_id") or "").strip()
            ]
            task_id_consistency = {
                "session_id": main_session_id,
                "ticket_id": main_ticket_id,
                "delegate_task_ids": main_delegate_task_ids,
                "task_ref_ids": role_task_ids(main_delegate),
                "stage_task_ids": main_stage_task_ids,
                "matched_delegate_task_ids": [node_id for node_id in main_delegate_task_ids if node_id in main_stage_task_ids],
            }
            assert_true(bool(task_id_consistency["matched_delegate_task_ids"]), "delegate task ids not visible in stage tasks")
            task_consistency_path = api_dir / "main-task_id_consistency.json"
            write_json(task_consistency_path, task_id_consistency)
            evidence["sessions"]["main"] = {
                "session_id": main_session_id,
                "ticket_id": main_ticket_id,
                "workspace_init_ref": main_workspace_init_ref,
                "delegate_task_id": main_delegate_task_id,
            }

            archive_role_name = "增长分析师浏览器验收废案"
            archive_create_payload = {"session_title": "废案入口验收", "operator": operator}
            status, archive_create = api_request(base_url, "POST", "/api/training/role-creation/sessions", archive_create_payload)
            assert_true(status == 200 and isinstance(archive_create, dict) and archive_create.get("ok"), "archive create session failed")
            evidence["api"]["archive_create_session"] = record_api(
                api_dir,
                stage="archive",
                name="create_session",
                method="POST",
                path="/api/training/role-creation/sessions",
                payload=archive_create_payload,
                status=status,
                body=archive_create,
            )
            archive_session_id = str((archive_create.get("session") or {}).get("session_id") or "").strip()
            assert_true(archive_session_id, "archive session_id missing")

            archive_message_payload = {
                "content": role_message_text(archive_role_name),
                "attachments": image_attachment_payload("growth-archive.png"),
                "operator": operator,
            }
            status, archive_message = api_request(
                base_url,
                "POST",
                f"/api/training/role-creation/sessions/{archive_session_id}/messages",
                archive_message_payload,
            )
            assert_true(status == 200 and isinstance(archive_message, dict) and archive_message.get("ok"), "archive message post failed")
            evidence["api"]["archive_message_with_image"] = record_api(
                api_dir,
                stage="archive",
                name="message_with_image",
                method="POST",
                path=f"/api/training/role-creation/sessions/{archive_session_id}/messages",
                payload=archive_message_payload,
                status=status,
                body=archive_message,
            )
            archive_message_ready = wait_for_role_creation_idle(base_url, archive_session_id)
            evidence["api"]["archive_message_idle"] = record_api(
                api_dir,
                stage="archive",
                name="message_idle",
                method="GET",
                path=f"/api/training/role-creation/sessions/{archive_session_id}",
                payload=None,
                status=200,
                body=archive_message_ready,
            )
            archive_supplement_payload = {"content": role_message_supplement_text(), "operator": operator}
            status, archive_supplement = api_request(
                base_url,
                "POST",
                f"/api/training/role-creation/sessions/{archive_session_id}/messages",
                archive_supplement_payload,
            )
            assert_true(status == 200 and isinstance(archive_supplement, dict) and archive_supplement.get("ok"), "archive supplement post failed")
            evidence["api"]["archive_message_supplement"] = record_api(
                api_dir,
                stage="archive",
                name="message_supplement",
                method="POST",
                path=f"/api/training/role-creation/sessions/{archive_session_id}/messages",
                payload=archive_supplement_payload,
                status=status,
                body=archive_supplement,
            )
            archive_supplement_ready = wait_for_role_creation_idle(base_url, archive_session_id)
            evidence["api"]["archive_message_supplement_idle"] = record_api(
                api_dir,
                stage="archive",
                name="message_supplement_idle",
                method="GET",
                path=f"/api/training/role-creation/sessions/{archive_session_id}",
                payload=None,
                status=200,
                body=archive_supplement_ready,
            )

            status, archive_start = api_request(
                base_url,
                "POST",
                f"/api/training/role-creation/sessions/{archive_session_id}/start",
                {"operator": operator},
            )
            assert_true(status == 200 and isinstance(archive_start, dict) and archive_start.get("ok"), "archive start failed")
            evidence["api"]["archive_start_session"] = record_api(
                api_dir,
                stage="archive",
                name="start_session",
                method="POST",
                path=f"/api/training/role-creation/sessions/{archive_session_id}/start",
                payload={"operator": operator},
                status=status,
                body=archive_start,
            )
            archive_ticket_id = str((archive_start.get("session") or {}).get("assignment_ticket_id") or "").strip()
            archive_before_ids = set(role_task_ids(archive_start))
            allow_async_writes_to_settle()
            archive_delegate_payload = {"content": "另起一个任务去补竞品案例并回传预览。", "operator": operator}
            status, archive_delegate = api_request(
                base_url,
                "POST",
                f"/api/training/role-creation/sessions/{archive_session_id}/messages",
                archive_delegate_payload,
            )
            assert_true(status == 200 and isinstance(archive_delegate, dict) and archive_delegate.get("ok"), "archive delegate failed")
            evidence["api"]["archive_explicit_delegate"] = record_api(
                api_dir,
                stage="archive",
                name="explicit_delegate",
                method="POST",
                path=f"/api/training/role-creation/sessions/{archive_session_id}/messages",
                payload=archive_delegate_payload,
                status=status,
                body=archive_delegate,
            )
            archive_delegate_ready = wait_for_role_creation_idle(base_url, archive_session_id)
            evidence["api"]["archive_explicit_delegate_idle"] = record_api(
                api_dir,
                stage="archive",
                name="explicit_delegate_idle",
                method="GET",
                path=f"/api/training/role-creation/sessions/{archive_session_id}",
                payload=None,
                status=200,
                body=archive_delegate_ready,
            )
            archive_new_ids = sorted(set(role_task_ids(archive_delegate_ready)) - archive_before_ids)
            archive_task_id = archive_new_ids[0] if archive_new_ids else role_stage_task_ids(archive_delegate_ready, "review_and_alignment")[0]
            archive_api_payload = {"close_reason": "主线方案已足够，先收口到废案", "operator": operator}
            status, archive_result = api_request(
                base_url,
                "POST",
                f"/api/training/role-creation/sessions/{archive_session_id}/tasks/{archive_task_id}/archive",
                archive_api_payload,
            )
            assert_true(status == 200 and isinstance(archive_result, dict) and archive_result.get("ok"), "archive task failed")
            evidence["api"]["archive_task"] = record_api(
                api_dir,
                stage="archive",
                name="archive_task",
                method="POST",
                path=f"/api/training/role-creation/sessions/{archive_session_id}/tasks/{archive_task_id}/archive",
                payload=archive_api_payload,
                status=status,
                body=archive_result,
            )
            evidence["sessions"]["archive"] = {
                "session_id": archive_session_id,
                "ticket_id": archive_ticket_id,
                "archived_task_id": archive_task_id,
            }

            failure_role_name = "增长分析师浏览器验收失败演练"
            failure_create_payload = {"session_title": "失败重试验收", "operator": operator}
            status, failure_create = api_request(base_url, "POST", "/api/training/role-creation/sessions", failure_create_payload)
            assert_true(status == 200 and isinstance(failure_create, dict) and failure_create.get("ok"), "failure create session failed")
            evidence["api"]["failure_create_session"] = record_api(
                api_dir,
                stage="failure",
                name="create_session",
                method="POST",
                path="/api/training/role-creation/sessions",
                payload=failure_create_payload,
                status=status,
                body=failure_create,
            )
            failure_session_id = str((failure_create.get("session") or {}).get("session_id") or "").strip()
            assert_true(failure_session_id, "failure session_id missing")
            failure_message_payload = {
                "content": role_message_text(failure_role_name) + role_message_supplement_text() + "模拟失败。",
                "operator": operator,
            }
            status, failure_message = api_request(
                base_url,
                "POST",
                f"/api/training/role-creation/sessions/{failure_session_id}/messages",
                failure_message_payload,
            )
            assert_true(status == 200 and isinstance(failure_message, dict) and failure_message.get("ok"), "failure message post failed")
            evidence["api"]["failure_message"] = record_api(
                api_dir,
                stage="failure",
                name="message",
                method="POST",
                path=f"/api/training/role-creation/sessions/{failure_session_id}/messages",
                payload=failure_message_payload,
                status=status,
                body=failure_message,
            )
            failure_detail = wait_for_role_creation_failed(base_url, failure_session_id)
            evidence["api"]["failure_detail"] = record_api(
                api_dir,
                stage="failure",
                name="detail_failed",
                method="GET",
                path=f"/api/training/role-creation/sessions/{failure_session_id}",
                payload=None,
                status=200,
                body=failure_detail,
            )
            evidence["screenshots"]["failure_retry"] = capture_required_probe(
                edge_path,
                base_url,
                evidence_root,
                "rc_failure_retry",
                "rc_failure",
                {"tc_probe_session": failure_session_id},
            )
            status, failure_retry = api_request(
                base_url,
                "POST",
                f"/api/training/role-creation/sessions/{failure_session_id}/retry-analysis",
                {"operator": operator},
            )
            assert_true(status == 200 and isinstance(failure_retry, dict) and failure_retry.get("ok"), "failure retry api failed")
            evidence["api"]["failure_retry"] = record_api(
                api_dir,
                stage="failure",
                name="retry_analysis",
                method="POST",
                path=f"/api/training/role-creation/sessions/{failure_session_id}/retry-analysis",
                payload={"operator": operator},
                status=status,
                body=failure_retry,
            )
            failure_retry_ready = wait_for_role_creation_idle(base_url, failure_session_id)
            evidence["api"]["failure_retry_idle"] = record_api(
                api_dir,
                stage="failure",
                name="retry_idle",
                method="GET",
                path=f"/api/training/role-creation/sessions/{failure_session_id}",
                payload=None,
                status=200,
                body=failure_retry_ready,
            )
            assert_true(not bool(failure_retry_ready.get("codex_failure")), "failure retry should clear codex_failure")
            evidence["sessions"]["failure"] = {"session_id": failure_session_id}

            high_role_name = "增长分析师浏览器验收高负载"
            high_create_payload = {"session_title": "高任务量验收", "operator": operator}
            status, high_create = api_request(base_url, "POST", "/api/training/role-creation/sessions", high_create_payload)
            assert_true(status == 200 and isinstance(high_create, dict) and high_create.get("ok"), "high-load create session failed")
            evidence["api"]["high_load_create_session"] = record_api(
                api_dir,
                stage="high",
                name="create_session",
                method="POST",
                path="/api/training/role-creation/sessions",
                payload=high_create_payload,
                status=status,
                body=high_create,
            )
            high_session_id = str((high_create.get("session") or {}).get("session_id") or "").strip()
            assert_true(high_session_id, "high-load session_id missing")

            high_message_payload = {
                "content": role_message_text(high_role_name),
                "attachments": image_attachment_payload("growth-high-load.png"),
                "operator": operator,
            }
            status, high_message = api_request(
                base_url,
                "POST",
                f"/api/training/role-creation/sessions/{high_session_id}/messages",
                high_message_payload,
            )
            assert_true(status == 200 and isinstance(high_message, dict) and high_message.get("ok"), "high-load message post failed")
            evidence["api"]["high_load_message_with_image"] = record_api(
                api_dir,
                stage="high",
                name="message_with_image",
                method="POST",
                path=f"/api/training/role-creation/sessions/{high_session_id}/messages",
                payload=high_message_payload,
                status=status,
                body=high_message,
            )
            high_message_ready = wait_for_role_creation_idle(base_url, high_session_id)
            evidence["api"]["high_load_message_idle"] = record_api(
                api_dir,
                stage="high",
                name="message_idle",
                method="GET",
                path=f"/api/training/role-creation/sessions/{high_session_id}",
                payload=None,
                status=200,
                body=high_message_ready,
            )
            high_supplement_payload = {"content": role_message_supplement_text(), "operator": operator}
            status, high_supplement = api_request(
                base_url,
                "POST",
                f"/api/training/role-creation/sessions/{high_session_id}/messages",
                high_supplement_payload,
            )
            assert_true(status == 200 and isinstance(high_supplement, dict) and high_supplement.get("ok"), "high-load supplement post failed")
            evidence["api"]["high_load_message_supplement"] = record_api(
                api_dir,
                stage="high",
                name="message_supplement",
                method="POST",
                path=f"/api/training/role-creation/sessions/{high_session_id}/messages",
                payload=high_supplement_payload,
                status=status,
                body=high_supplement,
            )
            high_supplement_ready = wait_for_role_creation_idle(base_url, high_session_id)
            evidence["api"]["high_load_message_supplement_idle"] = record_api(
                api_dir,
                stage="high",
                name="message_supplement_idle",
                method="GET",
                path=f"/api/training/role-creation/sessions/{high_session_id}",
                payload=None,
                status=200,
                body=high_supplement_ready,
            )

            high_start_payload = {"operator": operator}
            high_start_status = 0
            high_start: Any = {}
            try:
                high_start_status, high_start = api_request(
                    base_url,
                    "POST",
                    f"/api/training/role-creation/sessions/{high_session_id}/start",
                    high_start_payload,
                )
            except TimeoutError as exc:
                high_start = {
                    "ok": False,
                    "error": "client_timeout",
                    "message": str(exc),
                }
            evidence["api"]["high_load_start_session"] = record_api(
                api_dir,
                stage="high",
                name="start_session",
                method="POST",
                path=f"/api/training/role-creation/sessions/{high_session_id}/start",
                payload=high_start_payload,
                status=high_start_status,
                body=high_start,
            )
            if high_start_status == 200 and isinstance(high_start, dict) and high_start.get("ok"):
                high_start_detail = high_start
            else:
                high_start_detail = wait_for_role_creation_started(base_url, high_session_id)
                evidence["api"]["high_load_start_session_eventual"] = record_api(
                    api_dir,
                    stage="high",
                    name="start_session_eventual",
                    method="GET",
                    path=f"/api/training/role-creation/sessions/{high_session_id}",
                    payload=None,
                    status=200,
                    body=high_start_detail,
                )
            assert_true(
                isinstance(high_start_detail, dict)
                and high_start_detail.get("ok")
                and str((high_start_detail.get("session") or {}).get("status") or "").strip().lower() == "creating",
                "high-load start failed",
            )
            high_ticket_id = str((high_start_detail.get("session") or {}).get("assignment_ticket_id") or "").strip()
            assert_true(high_ticket_id, "high-load ticket_id missing")
            allow_async_writes_to_settle()

            high_task_specs = [
                ("persona_collection", "收集行业漏斗案例", "整理 6 份增长漏斗案例并给出摘要。"),
                ("capability_generation", "生成漏斗诊断模板", "生成漏斗诊断模板并沉淀 HTML 预览。"),
                ("review_and_alignment", "生成交付预览页", "生成交付预览页并回传给当前会话。"),
            ]
            high_created_task_ids: list[str] = []
            for index, (stage_key, task_name, node_goal) in enumerate(high_task_specs, start=1):
                payload = {
                    "stage_key": stage_key,
                    "task_name": task_name,
                    "node_goal": node_goal,
                    "operator": operator,
                }
                status, created_task = api_request(
                    base_url,
                    "POST",
                    f"/api/training/role-creation/sessions/{high_session_id}/tasks",
                    payload,
                )
                assert_true(status == 200 and isinstance(created_task, dict) and created_task.get("ok"), f"high-load task create failed: {task_name}")
                evidence["api"][f"high_load_create_task_{index}"] = record_api(
                    api_dir,
                    stage="high",
                    name=f"create_task_{index}",
                    method="POST",
                    path=f"/api/training/role-creation/sessions/{high_session_id}/tasks",
                    payload=payload,
                    status=status,
                    body=created_task,
                )
                node_id = str((created_task.get("created_task") or {}).get("node_id") or "").strip()
                if node_id:
                    high_created_task_ids.append(node_id)

            high_archive_task_id = next((node_id for node_id in high_created_task_ids if node_id), "")
            assert_true(high_archive_task_id, "high-load archive task id missing")
            high_archive_payload = {"close_reason": "高负载验收里保留一条废案入口", "operator": operator}
            status, high_archive = api_request(
                base_url,
                "POST",
                f"/api/training/role-creation/sessions/{high_session_id}/tasks/{high_archive_task_id}/archive",
                high_archive_payload,
            )
            assert_true(status == 200 and isinstance(high_archive, dict) and high_archive.get("ok"), "high-load archive failed")
            evidence["api"]["high_load_archive_task"] = record_api(
                api_dir,
                stage="high",
                name="archive_task",
                method="POST",
                path=f"/api/training/role-creation/sessions/{high_session_id}/tasks/{high_archive_task_id}/archive",
                payload=high_archive_payload,
                status=status,
                body=high_archive,
            )

            status, high_detail = api_request(
                base_url,
                "GET",
                f"/api/training/role-creation/sessions/{high_session_id}",
            )
            assert_true(status == 200 and isinstance(high_detail, dict) and high_detail.get("ok"), "high-load detail fetch failed")
            evidence["api"]["high_load_detail"] = record_api(
                api_dir,
                stage="high",
                name="detail",
                method="GET",
                path=f"/api/training/role-creation/sessions/{high_session_id}",
                payload=None,
                status=status,
                body=high_detail,
            )

            success_candidates = role_stage_task_ids(high_detail, "persona_collection")[:2]
            if len(success_candidates) < 2:
                success_candidates = role_task_ids(high_detail)[:2]
            assert_true(len(success_candidates) >= 2, "high-load success candidates missing")
            for node_id in success_candidates[:2]:
                ws.deliver_assignment_artifact(
                    runtime_root,
                    ticket_id_text=high_ticket_id,
                    node_id_text=node_id,
                    operator=operator,
                    artifact_label=f"{node_id}.html",
                    delivery_note="browser acceptance delivered",
                )
                ws.override_assignment_node_status(
                    runtime_root,
                    ticket_id_text=high_ticket_id,
                    node_id_text=node_id,
                    target_status="succeeded",
                    operator=operator,
                    reason="browser acceptance completed",
                    result_ref=f"acceptance://{node_id}",
                )

            high_final_detail = ws.get_role_creation_session_detail(runtime_root, high_session_id)
            high_state_snapshot_path = api_dir / "high-final-state.json"
            write_json(high_state_snapshot_path, high_final_detail)
            evidence["sessions"]["high_load"] = {
                "session_id": high_session_id,
                "ticket_id": high_ticket_id,
                "archived_task_id": high_archive_task_id,
                "succeeded_task_ids": success_candidates[:2],
            }

            stage_meta = dict(main_detail_started.get("stage_meta") or {})
            main_profile = dict(main_supplement_ready.get("profile") or {})
            main_start_gate = dict(main_supplement_ready.get("start_gate") or {})
            main_structured_specs = dict(main_supplement_ready.get("structured_specs") or {})
            main_capability_spec = dict(main_structured_specs.get("capability_package_spec") or {})
            main_knowledge_plan = dict(main_structured_specs.get("knowledge_asset_plan") or {})
            main_seed_plan = dict(main_structured_specs.get("seed_delivery_plan") or {})
            main_module_names = [
                str((item or {}).get("module_name") or "").strip()
                for item in list(main_capability_spec.get("capability_modules") or [])
                if str((item or {}).get("module_name") or "").strip()
            ]
            main_knowledge_topics = [
                str((item or {}).get("asset_topic") or "").strip()
                for item in list(main_knowledge_plan.get("assets") or [])
                if str((item or {}).get("asset_topic") or "").strip()
            ]
            main_seed_task_names = [
                str((item or {}).get("task_name") or "").strip()
                for item in list(main_seed_plan.get("task_suggestions") or [])
                if str((item or {}).get("task_name") or "").strip()
            ]
            main_boundary_lines = [
                str(item).strip()
                for item in list(main_profile.get("boundaries") or [])
                if str(item).strip()
            ]
            main_delivery_summary = str((main_capability_spec.get("default_delivery_policy") or {}).get("summary") or "").strip()
            main_format_strategy = dict(main_capability_spec.get("format_strategy") or {})
            main_preferred_formats = {
                str(item).strip()
                for item in list(main_format_strategy.get("preferred_formats") or [])
                if str(item).strip()
            }
            main_allowed_formats = {
                str(item).strip()
                for item in list(main_format_strategy.get("allowed_formats") or [])
                if str(item).strip()
            }
            main_avoided_formats = {
                str(item).strip()
                for item in list(main_format_strategy.get("avoided_formats") or [])
                if str(item).strip()
            }
            evidence["assertions"]["current_stage_api"] = {
                "session_id": main_session_id,
                "current_stage_key": str((main_detail_started.get("session") or {}).get("current_stage_key") or ""),
                "detail_api": evidence["api"]["main_detail_started"],
            }
            evidence["assertions"]["role_spec_api"] = {
                "session_id": main_session_id,
                "role_name": str(main_profile.get("role_name") or ""),
                "core_capabilities": list(main_profile.get("core_capabilities") or []),
                "capability_modules": list(main_capability_spec.get("capability_modules") or []),
                "knowledge_assets": list(main_knowledge_plan.get("assets") or []),
                "seed_tasks": list(main_seed_plan.get("task_suggestions") or []),
                "message_api": evidence["api"]["main_message_supplement_idle"],
            }
            evidence["assertions"]["delegate_task_api"] = {
                "session_id": main_session_id,
                "delegate_task_ids": main_delegate_task_ids,
                "delegate_api": evidence["api"]["main_explicit_delegate"],
            }
            evidence["assertions"]["task_id_consistency"] = task_id_consistency
            evidence["assertions"]["workspace_init"] = {
                "session_id": main_session_id,
                "workspace_init_ref": main_workspace_init_ref,
                "workspace_init_path": str((runtime_root / main_workspace_init_ref).resolve()),
            }
            evidence["assertions"]["structured_quality"] = {
                "session_id": main_session_id,
                "module_names": main_module_names,
                "knowledge_topics": main_knowledge_topics,
                "seed_task_names": main_seed_task_names,
                "boundary_lines": main_boundary_lines,
                "default_delivery_summary": main_delivery_summary,
                "preferred_formats": sorted(main_preferred_formats),
                "allowed_formats": sorted(main_allowed_formats),
                "avoided_formats": sorted(main_avoided_formats),
            }

            assert_true(str((main_detail_started.get("session") or {}).get("current_stage_key") or "").strip() != "", "current stage key missing")
            assert_true(str(main_profile.get("role_name") or "").strip() == main_role_name, "role profile name mismatch")
            assert_true(len(list(main_profile.get("core_capabilities") or [])) >= 3, "role profile capabilities missing")
            assert_true(bool(main_start_gate.get("can_start")), "main start gate should be ready after supplement")
            assert_true(len(list(main_capability_spec.get("capability_modules") or [])) >= 2, "capability modules missing")
            assert_true(len(list(main_knowledge_plan.get("assets") or [])) >= 2, "knowledge assets missing")
            assert_true(len(list(main_seed_plan.get("task_suggestions") or [])) >= 1, "seed task suggestions missing")
            assert_true(
                {"问题拆解", "漏斗诊断", "实验设计", "复盘摘要"}.issubset(set(main_module_names)),
                "capability modules should contain the explicit module split",
            )
            assert_true(
                {"诊断方法说明", "诊断模板", "最小示例", "反例", "验收清单"}.issubset(set(main_knowledge_topics)),
                "knowledge assets should contain the explicit asset plan",
            )
            assert_true(
                not any(any(token in item for token in ("HTML", "Markdown", "JSON", "SVG")) for item in main_boundary_lines),
                "format boundary should not be mixed into role boundaries",
            )
            assert_true(
                "结构化诊断摘要" in main_delivery_summary and "可执行清单" in main_delivery_summary,
                "default delivery summary missing expected structured delivery hints",
            )
            assert_true(
                ("HTML" in main_preferred_formats or "HTML" in main_allowed_formats) and "SVG" in main_avoided_formats,
                "format strategy missing expected preferred/avoided formats",
            )
            assert_true(
                not any(any(token in item for token in ("知识沉淀：", "首批任务：", "角色名是")) for item in main_module_names + main_knowledge_topics + main_seed_task_names),
                "structured items should not keep raw label prefixes or role-name noise",
            )
            assert_true(bool(main_delegate_task_ids), "delegate task evidence missing")
            assert_true(stage_meta.get("ticket_id"), "stage meta ticket id missing")

            evidence["screenshots"]["default_view"] = capture_required_probe(
                edge_path,
                base_url,
                evidence_root,
                "rc_default_overview",
                "rc_default",
                {"tc_probe_session": default_session_id},
            )
            evidence["screenshots"]["message_with_image"] = capture_required_probe(
                edge_path,
                base_url,
                evidence_root,
                "rc_message_with_image",
                "rc_message_with_image",
                {"tc_probe_session": main_session_id},
            )
            evidence["screenshots"]["profile_tab"] = capture_required_probe(
                edge_path,
                base_url,
                evidence_root,
                "rc_profile_tab",
                "rc_profile_tab",
                {"tc_probe_session": main_session_id},
            )
            evidence["screenshots"]["task_hover"] = capture_required_probe(
                edge_path,
                base_url,
                evidence_root,
                "rc_task_hover",
                "rc_task_hover",
                {"tc_probe_session": main_session_id, "tc_probe_node": main_delegate_task_id},
            )
            evidence["screenshots"]["task_pinned"] = capture_required_probe(
                edge_path,
                base_url,
                evidence_root,
                "rc_task_pinned",
                "rc_task_pinned",
                {"tc_probe_session": main_session_id, "tc_probe_node": main_delegate_task_id},
            )
            evidence["screenshots"]["archive_entry"] = capture_required_probe(
                edge_path,
                base_url,
                evidence_root,
                "rc_archive_entry",
                "rc_archive",
                {"tc_probe_session": archive_session_id},
            )
            evidence["screenshots"]["high_load"] = capture_required_probe(
                edge_path,
                base_url,
                evidence_root,
                "rc_high_load",
                "rc_high_load",
                {"tc_probe_session": high_session_id},
            )

            summary_path = evidence_root / "summary.md"
            lines = [
                "# Role Creation Browser Acceptance",
                "",
                f"- runtime_root: {runtime_root.as_posix()}",
                f"- base_url: {base_url}",
                f"- edge_path: {edge_path.as_posix()}",
                f"- artifact_root: {artifact_root.as_posix()}",
                f"- api_dir: {api_dir.as_posix()}",
                f"- screenshots_dir: {shots_dir.as_posix()}",
                f"- server_stdout: {(log_root / 'server.stdout.log').as_posix()}",
                f"- server_stderr: {(log_root / 'server.stderr.log').as_posix()}",
                "",
                "## Sessions",
                "",
                f"- default: {default_session_id}",
                f"- main: {main_session_id} ticket={main_ticket_id} workspace_init_ref={main_workspace_init_ref}",
                f"- archive: {archive_session_id} ticket={archive_ticket_id} archived_task={archive_task_id}",
                f"- failure: {failure_session_id}",
                f"- high_load: {high_session_id} ticket={high_ticket_id} archived_task={high_archive_task_id}",
                "",
                "## Required Screenshots",
                "",
            ]
            for key, payload in evidence["screenshots"].items():
                lines.append(f"- {key}: {payload['image']}")
                lines.append(f"  probe: {payload['probe']}")
            lines.extend(
                [
                    "",
                    "## Key Evidence",
                    "",
                    f"- current_stage_api: {evidence['api']['main_detail_started']}",
                    f"- role_spec_api: {evidence['api']['main_message_supplement_idle']}",
                    f"- explicit_delegate_api: {evidence['api']['main_explicit_delegate']}",
                    f"- failure_retry_api: {evidence['api']['failure_retry_idle']}",
                    f"- task_id_consistency: {task_consistency_path.as_posix()}",
                    f"- workspace_init: {(runtime_root / main_workspace_init_ref).as_posix()}",
                    f"- high_load_state: {high_state_snapshot_path.as_posix()}",
                    "",
                ]
            )
            summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            evidence["summary_md"] = summary_path.as_posix()
            evidence["ok"] = True

        write_json(evidence_root / "summary.json", evidence)
        return 0
    finally:
        if not (evidence_root / "summary.json").exists():
            write_json(evidence_root / "summary.json", evidence)


if __name__ == "__main__":
    raise SystemExit(main())
