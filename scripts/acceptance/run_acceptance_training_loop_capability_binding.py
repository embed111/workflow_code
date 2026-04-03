#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def call(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout_s: int = 90,
) -> tuple[int, dict[str, Any]]:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(base_url + path, data=data, method=method, headers=headers)
    try:
        with urlopen(req, timeout=max(10, int(timeout_s))) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, (json.loads(body) if body else {})
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            payload_obj = json.loads(body) if body else {}
        except Exception:
            payload_obj = {"raw": body}
        return exc.code, payload_obj


def wait_health(base_url: str, timeout_s: int = 80) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            status, payload = call(base_url, "GET", "/healthz", None, timeout_s=10)
            if status == 200 and bool(payload.get("ok")):
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError("healthz timeout")


def pick_port(host: str, start_port: int = 18110, attempts: int = 50) -> int:
    for port in range(start_port, start_port + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError("no free port")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def find_edge() -> Path:
    for candidate in (
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ):
        if candidate.exists() and candidate.is_file():
            return candidate
    raise RuntimeError("msedge not found")


def edge_cmd(edge_path: Path, profile_dir: Path, *, width: int, height: int, budget_ms: int) -> list[str]:
    return [
        str(edge_path),
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        f"--user-data-dir={profile_dir.as_posix()}",
        f"--window-size={width},{height}",
        f"--virtual-time-budget={budget_ms}",
    ]


def edge_shot(edge_path: Path, url: str, shot_path: Path, *, width: int, height: int, budget_ms: int) -> None:
    shot_path.parent.mkdir(parents=True, exist_ok=True)
    profile_dir = shot_path.parent / ".edge-profile" / f"shot-{uuid.uuid4().hex}"
    profile_dir.mkdir(parents=True, exist_ok=True)
    cmd = edge_cmd(edge_path, profile_dir, width=width, height=height, budget_ms=budget_ms) + [
        f"--screenshot={shot_path.as_posix()}",
        url,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=180)
        if proc.returncode != 0:
            raise RuntimeError(f"edge screenshot failed: {proc.stderr}")
    finally:
        try:
            import shutil

            shutil.rmtree(profile_dir, ignore_errors=True)
        except Exception:
            pass


def edge_dom(edge_path: Path, url: str, *, width: int, height: int, budget_ms: int) -> str:
    profile_dir = Path.cwd() / ".test" / "tmp-edge-dom" / uuid.uuid4().hex
    profile_dir.mkdir(parents=True, exist_ok=True)
    cmd = edge_cmd(edge_path, profile_dir, width=width, height=height, budget_ms=budget_ms) + ["--dump-dom", url]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=180)
        if proc.returncode != 0:
            raise RuntimeError(f"edge dump-dom failed: {proc.stderr}")
        return proc.stdout
    finally:
        try:
            import shutil

            shutil.rmtree(profile_dir, ignore_errors=True)
        except Exception:
            pass


def pick_training_agent(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    rows = [row for row in items if isinstance(row, dict)]
    for preferred_id in ("Analyst2",):
        for row in rows:
            if str(row.get("agent_id") or "").strip() == preferred_id:
                return row
    for row in rows:
        if str(row.get("agent_id") or "").strip() != "Analyst":
            return row
    return rows[0] if rows else None


def require_capability_shape(capability: dict[str, Any]) -> None:
    required = [
        "capability_id",
        "capability_name",
        "capability_goal",
        "preview_evidence",
        "score_current",
        "score_target",
        "gate_status",
        "historical_regression_result",
        "impact_scope",
    ]
    missing = [key for key in required if key not in capability]
    if missing:
        raise RuntimeError(f"capability missing fields: {missing}")


def page_url(base_url: str, *, task_id: str, goal: str, right_tab: str | None = None) -> str:
    params = {
        "tc_loop_mode": "status",
        "tc_loop_task": task_id,
        "tc_loop_node": task_id,
        "tc_loop_search": goal,
    }
    if right_tab:
        params["tc_loop_tab"] = right_tab
    return base_url + "/?" + urlencode(params)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--budget-ms", type=int, default=24000)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    runtime_root = repo_root / ".runtime"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_root = repo_root / "logs" / "runs" / f"tc-loop-capability-binding-{ts}"
    api_dir = run_root / "api"
    shots_dir = run_root / "screenshots"
    probe_dir = run_root / "probes"
    run_root.mkdir(parents=True, exist_ok=True)
    api_dir.mkdir(parents=True, exist_ok=True)
    shots_dir.mkdir(parents=True, exist_ok=True)
    probe_dir.mkdir(parents=True, exist_ok=True)

    host = str(args.host)
    port = int(args.port) if int(args.port) > 0 else pick_port(host)
    base_url = f"http://{host}:{port}"
    stdout_path = run_root / "server_stdout.log"
    stderr_path = run_root / "server_stderr.log"
    proc = subprocess.Popen(
        [
            sys.executable,
            str(repo_root / "scripts" / "workflow_web_server.py"),
            "--host",
            host,
            "--port",
            str(port),
            "--root",
            runtime_root.as_posix(),
            "--agent-search-root",
            repo_root.parent.as_posix(),
        ],
        cwd=repo_root.as_posix(),
        stdout=stdout_path.open("w", encoding="utf-8"),
        stderr=stderr_path.open("w", encoding="utf-8"),
    )

    try:
        wait_health(base_url)

        st_agents, agents_payload = call(base_url, "GET", "/api/training/agents?include_test_data=0")
        if st_agents != 200 or not bool(agents_payload.get("ok")):
            raise RuntimeError(f"list agents failed: {agents_payload}")
        items = agents_payload.get("items") if isinstance(agents_payload, dict) else []
        picked = pick_training_agent(items if isinstance(items, list) else [])
        target_agent_id = str((picked or {}).get("agent_id") or "").strip()
        if not target_agent_id:
            raise RuntimeError("target agent missing")

        goal = f"tc-loop-capability-binding {ts}"
        plan_payload = {
            "target_agent_id": target_agent_id,
            "capability_goal": goal,
            "training_tasks": [
                f"优化训练优化能力列表主视图 {ts}",
                f"补齐 Gate-B Gate-C 绑定取证 {ts}",
                f"校验默认右侧标签与能力基线切换 {ts}",
            ],
            "acceptance_criteria": "能力列表对象化、效果与评分同屏、Gate-B/Gate-C 绑定到能力项、右侧默认任务/能力演进并可切换当前能力基线。",
            "priority": "P0",
            "operator": "acceptance-script",
            "created_by": "acceptance-script",
            "execution_engine": "workflow_native",
        }
        st_plan, plan_resp = call(base_url, "POST", "/api/training/plans/manual", plan_payload)
        if st_plan != 200 or not bool(plan_resp.get("ok")):
            raise RuntimeError(f"create plan failed: {plan_resp}")
        write_json(api_dir / "01_create_plan.json", plan_resp)
        queue_round1 = str(plan_resp.get("queue_task_id") or "").strip()
        if not queue_round1:
            raise RuntimeError("queue_round1 missing")

        st_exec1, exec1 = call(
            base_url,
            "POST",
            f"/api/training/queue/{queue_round1}/execute",
            {"operator": "acceptance-script"},
        )
        if st_exec1 != 200 or not bool(exec1.get("ok")):
            raise RuntimeError(f"execute round1 failed: {exec1}")
        write_json(api_dir / "02_execute_round1.json", exec1)

        st_loop1, loop1 = call(base_url, "GET", f"/api/training/queue/{queue_round1}/loop")
        st_detail1, detail1 = call(base_url, "GET", f"/api/training/queue/{queue_round1}/status-detail")
        if st_loop1 != 200 or not bool(loop1.get("ok")) or st_detail1 != 200 or not bool(detail1.get("ok")):
            raise RuntimeError("round1 loop/detail fetch failed")
        write_json(api_dir / "03_loop_round1.json", loop1)
        write_json(api_dir / "04_status_detail_round1.json", detail1)

        round1_caps = list(detail1.get("capabilities") or [])
        if not round1_caps:
            raise RuntimeError("round1 capabilities missing")
        round1_cap = dict(round1_caps[0])
        require_capability_shape(round1_cap)
        round1_history = round1_cap.get("historical_regression_result") if isinstance(round1_cap.get("historical_regression_result"), dict) else {}
        if str(round1_history.get("status") or "").strip() != "not_affected":
            raise RuntimeError(f"round1 expected not_affected, got {round1_history}")
        write_json(api_dir / "05_capability_example_round1.json", round1_cap)

        st_enter, enter_resp = call(
            base_url,
            "POST",
            f"/api/training/queue/{queue_round1}/loop/enter-next-round",
            {"operator": "acceptance-script", "reason": "acceptance enter next round"},
        )
        if st_enter != 200 or not bool(enter_resp.get("ok")):
            raise RuntimeError(f"enter next round failed: {enter_resp}")
        write_json(api_dir / "06_enter_next_round.json", enter_resp)
        queue_round2 = str(enter_resp.get("created_queue_task_id") or "").strip()
        if not queue_round2:
            raise RuntimeError("queue_round2 missing")

        st_exec2, exec2 = call(
            base_url,
            "POST",
            f"/api/training/queue/{queue_round2}/execute",
            {"operator": "acceptance-script"},
        )
        if st_exec2 != 200 or not bool(exec2.get("ok")):
            raise RuntimeError(f"execute round2 failed: {exec2}")
        write_json(api_dir / "07_execute_round2.json", exec2)

        st_loop2, loop2 = call(base_url, "GET", f"/api/training/queue/{queue_round2}/loop")
        st_detail2, detail2 = call(base_url, "GET", f"/api/training/queue/{queue_round2}/status-detail")
        if st_loop2 != 200 or not bool(loop2.get("ok")) or st_detail2 != 200 or not bool(detail2.get("ok")):
            raise RuntimeError("round2 loop/detail fetch failed")
        write_json(api_dir / "08_loop_round2.json", loop2)
        write_json(api_dir / "09_status_detail_round2.json", detail2)

        round2_caps = list(detail2.get("capabilities") or [])
        blocked_cap = next(
            (
                dict(item)
                for item in round2_caps
                if str((((item or {}).get("gate_status") or {}).get("gate_c") or {}).get("status") or "").strip() == "blocked"
            ),
            None,
        )
        if blocked_cap is None:
            raise RuntimeError("round2 blocked capability missing")
        require_capability_shape(blocked_cap)
        write_json(api_dir / "10_capability_example_round2_blocked.json", blocked_cap)

        tasks_evolution2 = detail2.get("tasks_evolution") if isinstance(detail2.get("tasks_evolution"), dict) else {}
        auto_publish2 = tasks_evolution2.get("auto_publish") if isinstance(tasks_evolution2, dict) else {}
        if str(auto_publish2.get("status") or "").strip() != "blocked":
            raise RuntimeError(f"round2 expected blocked auto_publish, got {auto_publish2}")
        write_json(
            api_dir / "11_behavior_evidence.json",
            {
                "round1_historical_result": round1_history,
                "round2_blocked_capability": blocked_cap.get("historical_regression_result"),
                "round2_auto_publish": auto_publish2,
                "round2_blockers": tasks_evolution2.get("blockers"),
            },
        )

        edge = find_edge()
        url_round1_default = page_url(base_url, task_id=queue_round1, goal=goal)
        url_round2_default = page_url(base_url, task_id=queue_round2, goal=goal)
        url_round2_baseline = page_url(base_url, task_id=queue_round2, goal=goal, right_tab="baseline")

        screenshots = [
            ("角色中心训练优化首屏", shots_dir / "01_training_optimization_first_screen_round1.png", url_round1_default, 1440, 980),
            ("中部聊天壳能力列表", shots_dir / "02_chat_shell_capability_list_round1.png", url_round1_default, 1440, 980),
            ("能力项效果与评分同屏", shots_dir / "03_effect_and_score_round1.png", url_round1_default, 1440, 980),
            ("Gate-B Gate-C 绑定到能力项", shots_dir / "04_gate_binding_round2_blocked.png", url_round2_default, 1440, 980),
            ("右侧默认任务与能力演进", shots_dir / "05_right_tasks_evolution_default_round2.png", url_round2_default, 1440, 980),
            ("右侧当前能力基线", shots_dir / "06_right_baseline_round2.png", url_round2_baseline, 1440, 980),
        ]
        screenshot_refs: list[dict[str, str]] = []
        for title, shot_path, url, width, height in screenshots:
            edge_shot(edge, url, shot_path, width=width, height=height, budget_ms=int(args.budget_ms))
            screenshot_refs.append({"title": title, "path": shot_path.as_posix(), "url": url})

        round1_dom = edge_dom(edge, url_round1_default, width=1440, height=980, budget_ms=int(args.budget_ms))
        round2_dom = edge_dom(edge, url_round2_default, width=1440, height=980, budget_ms=int(args.budget_ms))
        round2_baseline_dom = edge_dom(edge, url_round2_baseline, width=1440, height=980, budget_ms=int(args.budget_ms))
        write_text(probe_dir / "round1_default.dom.html", round1_dom)
        write_text(probe_dir / "round2_default.dom.html", round2_dom)
        write_text(probe_dir / "round2_baseline.dom.html", round2_baseline_dom)

        dom_assertions = {
            "round1_chat_shell": "训练优化会话" in round1_dom and "本轮能力列表" in round1_dom,
            "round1_effect_and_score": "能力展示效果" in round1_dom and "能力评分" in round1_dom,
            "round1_gate_bindings": "Gate-B" in round1_dom and "Gate-C" in round1_dom,
            "round1_unaffected_history": "未影响历史能力" in round1_dom,
            "round2_gate_c_blocked": (
                "该能力项导致历史能力下降，自动发布保持阻塞" in round2_dom
                or "该能力项触发历史能力退化，自动发布保持阻塞" in round2_dom
            ),
            "round2_auto_publish_blocked": "自动发布阻塞" in round2_dom or "自动发布" in round2_dom and "blocked" in round2_dom,
            "right_default_tasks": "data-right-tab=\"tasks\"" in round2_dom and "tc-loop-tab active" in round2_dom,
            "right_baseline_switch": "当前能力基线" in round2_baseline_dom and "data-right-pane=\"baseline\"" in round2_baseline_dom,
        }
        if not all(dom_assertions.values()):
            raise RuntimeError(f"dom assertions failed: {dom_assertions}")
        write_json(probe_dir / "dom_assertions.json", dom_assertions)

        summary_lines = [
            f"# Training Loop Capability Binding Evidence ({ts})",
            "",
            f"- base_url: {base_url}",
            f"- queue_round1: {queue_round1}",
            f"- queue_round2: {queue_round2}",
            f"- server_stdout: {stdout_path.as_posix()}",
            f"- server_stderr: {stderr_path.as_posix()}",
            "",
            "## API",
        ]
        for path in sorted(api_dir.glob("*.json")):
            summary_lines.append(f"- {path.name}: {path.as_posix()}")
        summary_lines.extend(["", "## DOM Probes"])
        for path in sorted(probe_dir.iterdir()):
            summary_lines.append(f"- {path.name}: {path.as_posix()}")
        summary_lines.extend(["", "## Screenshots"])
        for item in screenshot_refs:
            summary_lines.append(f"- {item['title']}: {item['path']}")
            summary_lines.append(f"  url: {item['url']}")
        summary_lines.extend(
            [
                "",
                "## Key Findings",
                "- Round1 capability object renders with effect evidence, score, Gate-B and Gate-C; historical result is `not_affected`.",
                "- Round2 capability object contains `gate_status.gate_c=blocked`; `tasks_evolution.auto_publish.status=blocked`.",
                "- Default right tab stays on `任务 / 能力演进`; `当前能力基线` can be switched independently.",
            ]
        )
        summary_path = run_root / "summary.md"
        write_text(summary_path, "\n".join(summary_lines) + "\n")
        print(summary_path.as_posix())
        return 0
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
