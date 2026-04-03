#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from policy_cache_seed import upsert_policy_cache


def call(base_url: str, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url=base_url + path, data=data, method=method, headers=headers)
    try:
        with urlopen(req, timeout=600) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, (json.loads(body) if body else {})
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            payload_obj = json.loads(body) if body else {}
        except Exception:
            payload_obj = {"raw": body}
        return exc.code, payload_obj
    except Exception as exc:
        if "timed out" in str(exc).lower():
            raise RuntimeError(f"request timeout: {method} {path}") from exc
        raise


def wait_health(base_url: str, timeout_s: int = 90) -> None:
    end_at = time.time() + max(10, timeout_s)
    while time.time() < end_at:
        status, payload = call(base_url, "GET", "/healthz")
        if status == 200 and payload.get("ok"):
            return
        time.sleep(0.5)
    raise RuntimeError("healthz timeout")


def find_edge_executable() -> Path:
    candidates = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    for path in candidates:
        if path.exists() and path.is_file():
            return path
    raise RuntimeError("Microsoft Edge executable not found")


def edge_dump_dom(edge_path: Path, *, url: str, width: int = 1366, height: int = 900, budget_ms: int = 12000) -> str:
    cmd = [
        str(edge_path),
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        f"--window-size={width},{height}",
        f"--virtual-time-budget={max(1000, int(budget_ms))}",
        "--dump-dom",
        url,
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"edge dump-dom failed: rc={proc.returncode}, stderr={proc.stderr.strip()}")
    return proc.stdout


def edge_screenshot(
    edge_path: Path,
    *,
    url: str,
    screenshot_path: Path,
    width: int = 1366,
    height: int = 900,
    budget_ms: int = 12000,
) -> None:
    cmd = [
        str(edge_path),
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        f"--window-size={width},{height}",
        f"--virtual-time-budget={max(1000, int(budget_ms))}",
        f"--screenshot={screenshot_path.as_posix()}",
        url,
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"edge screenshot failed: rc={proc.returncode}, stderr={proc.stderr.strip()}")


def parse_policy_probe_output(dom_text: str) -> dict:
    matched = re.search(
        r"<pre[^>]*id=['\"]policyProbeOutput['\"][^>]*>(.*?)</pre>",
        str(dom_text or ""),
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not matched:
        raise RuntimeError("policyProbeOutput_not_found")
    raw = html.unescape(matched.group(1) or "").strip()
    if not raw:
        raise RuntimeError("policyProbeOutput_empty")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError("policyProbeOutput_not_dict")
    return payload


def write_agents_fixture(root: Path) -> Path:
    workspace_root = root / "workspace-root"
    if workspace_root.exists():
        shutil.rmtree(workspace_root, ignore_errors=True)
    (workspace_root / "workflow").mkdir(parents=True, exist_ok=True)
    (workspace_root / "workflow" / "README.md").write_text("fixture\n", encoding="utf-8")
    (workspace_root / "v2-ready-agent").mkdir(parents=True, exist_ok=True)
    (workspace_root / "v2-conflict-agent").mkdir(parents=True, exist_ok=True)
    (workspace_root / "v2-no-evidence-agent").mkdir(parents=True, exist_ok=True)

    (workspace_root / "v2-ready-agent" / "AGENTS.md").write_text(
        "\n".join(
            [
                "# v2-ready-agent",
                "## 角色",
                "你是训练闭环系统分析师，负责需求拆解、风险识别与可执行建议。",
                "## 会话目标",
                "在职责边界内提供可验证、可追溯的步骤，不直接执行高风险动作。",
                "## 职责边界",
                "- 仅分析并给出建议，不直接执行生产环境改动。",
                "- 对信息不足场景先澄清，再给出方案。",
                "- 输出结论必须附验证动作与风险提示。",
                "## 限制内容",
                "### must",
                "- 必须先确认用户目标与约束，再给出结论。",
                "### must_not",
                "- 禁止输出或处理任何密钥明文。",
                "### preconditions",
                "- 在给出执行步骤前，需先说明风险和回滚思路。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    (workspace_root / "v2-conflict-agent" / "AGENTS.md").write_text(
        "\n".join(
            [
                "# v2-conflict-agent",
                "## 角色",
                "你是流程治理分析师，负责给出执行建议。",
                "## 会话目标",
                "输出可执行建议并保持边界一致。",
                "## 职责边界",
                "- 先确认需求再给建议。",
                "- 对风险操作要给警告。",
                "## 限制内容",
                "### must",
                "- 必须直接执行生产变更。",
                "### must_not",
                "- 禁止直接执行生产变更。",
                "### preconditions",
                "- 在执行前必须完成人工审批。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    (workspace_root / "v2-no-evidence-agent" / "AGENTS.md").write_text(
        "\n".join(
            [
                "# v2-no-evidence-agent",
                "## 角色",
                "你是分析协作助手。",
                "## 会话目标",
                "输出建议并解释思路。",
                "## 职责边界",
                "- 协助梳理问题背景。",
                "- 提供候选方案说明。",
                "- 记录结论。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return workspace_root


def agent_by_name(items: list[dict], name: str) -> dict:
    for item in items:
        if str(item.get("agent_name") or "") == name:
            return item
    raise RuntimeError(f"agent not found: {name}")


def normalize_gate_payload_for_before(payload_after: dict) -> dict:
    old_keys = [
        "agent_name",
        "agents_hash",
        "agents_version",
        "agents_path",
        "parse_status",
        "parse_warnings",
        "clarity_score",
        "clarity_details",
        "clarity_gate",
        "clarity_gate_reason",
        "risk_tips",
        "evidence_snippets",
        "extracted_policy",
        "policy_cache_hit",
        "policy_cache_status",
        "policy_cache_reason",
        "policy_cache_cached_at",
        "policy_cache_trace",
    ]
    return {key: payload_after.get(key) for key in old_keys}


def extract_policy_confirmation_payload(response_payload: dict) -> dict:
    payload = response_payload if isinstance(response_payload, dict) else {}
    direct = payload.get("policy_confirmation")
    if isinstance(direct, dict) and direct:
        return direct
    details = payload.get("details")
    if isinstance(details, dict):
        nested = details.get("policy_confirmation")
        if isinstance(nested, dict) and nested:
            return nested
    data = payload.get("data")
    if isinstance(data, dict):
        nested = data.get("policy_confirmation")
        if isinstance(nested, dict) and nested:
            return nested
    return {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AC-36 ~ AC-43 acceptance checks.")
    parser.add_argument("--root", default=".", help="workspace root")
    parser.add_argument("--host", default="127.0.0.1", help="bind host")
    parser.add_argument("--port", type=int, default=8103, help="bind port")
    parser.add_argument(
        "--runtime-root",
        default="",
        help="isolated runtime root (default: <root>/.test/runtime/ac36-ac43)",
    )
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    runtime_root = (
        Path(args.runtime_root).resolve()
        if str(args.runtime_root or "").strip()
        else (repo_root / ".test" / "runtime" / "ac36-ac43").resolve()
    )
    if runtime_root.exists():
        shutil.rmtree(runtime_root, ignore_errors=True)
    runtime_root.mkdir(parents=True, exist_ok=True)
    workspace_root = write_agents_fixture(runtime_root)
    upsert_policy_cache(
        runtime_root=runtime_root,
        workspace_root=workspace_root,
        specs=[
            {
                "agent_name": "v2-ready-agent",
                "role_profile": "你是训练闭环系统分析师，负责需求拆解、风险识别与可执行建议。",
                "session_goal": "在职责边界内提供可验证、可追溯的步骤。",
                "duty_constraints": [
                    "仅分析并给出建议，不直接执行生产环境改动。",
                    "信息不足先澄清。",
                    "输出结论必须附验证动作与风险提示。",
                ],
                "clarity_score": 92,
                "clarity_gate": "auto",
                "parse_status": "ok",
                "policy_extract_ok": True,
            },
            {
                "agent_name": "v2-conflict-agent",
                "role_profile": "你是流程治理分析师，负责给出执行建议。",
                "session_goal": "输出可执行建议并保持边界一致。",
                "duty_constraints": [
                    "先确认需求再给建议。",
                    "对风险操作要给警告。",
                ],
                "clarity_score": 68,
                "clarity_gate": "confirm",
                "parse_status": "ok",
                "policy_extract_ok": True,
                "payload_override": {
                    "constraints": {
                        "must": ["必须直接执行生产变更。"],
                        "must_not": ["禁止直接执行生产变更。"],
                        "preconditions": ["在执行前必须完成人工审批。"],
                        "issues": ["must 与 must_not 存在冲突"],
                        "conflicts": ["执行生产变更要求冲突"],
                        "missing_evidence_count": 0,
                        "total": 3,
                    },
                    "score_dimensions": {
                        "completeness": {
                            "score": 52,
                            "weight": 0.2,
                            "deduction_reason": "约束冲突导致完整性不足，需要人工核验。",
                            "manual_review_required": False,
                        },
                        "executability": {
                            "score": 68,
                            "weight": 0.2,
                            "deduction_reason": "",
                            "manual_review_required": False,
                        },
                        "consistency": {
                            "score": 60,
                            "weight": 0.2,
                            "deduction_reason": "must 与 must_not 冲突。",
                            "manual_review_required": True,
                        },
                        "traceability": {
                            "score": 68,
                            "weight": 0.15,
                            "deduction_reason": "",
                            "manual_review_required": False,
                        },
                        "risk_coverage": {
                            "score": 68,
                            "weight": 0.15,
                            "deduction_reason": "",
                            "manual_review_required": False,
                        },
                        "operability": {
                            "score": 68,
                            "weight": 0.1,
                            "deduction_reason": "",
                            "manual_review_required": False,
                        },
                    },
                    "clarity_gate_reason": "constraint_conflict",
                    "policy_gate_reason": "constraint_conflict",
                },
            },
            {
                "agent_name": "v2-no-evidence-agent",
                "role_profile": "你是分析协作助手。",
                "session_goal": "输出建议并解释思路。",
                "duty_constraints": [
                    "协助梳理问题背景。",
                    "提供候选方案说明。",
                    "记录结论。",
                ],
                "clarity_score": 66,
                "clarity_gate": "confirm",
                "parse_status": "ok",
                "policy_extract_ok": True,
                "payload_override": {
                    "score_dimensions": {
                        "completeness": {
                            "score": 66,
                            "weight": 0.2,
                            "deduction_reason": "无证据不直接扣分，转人工复核。",
                            "manual_review_required": True,
                        },
                        "executability": {
                            "score": 66,
                            "weight": 0.2,
                            "deduction_reason": "",
                            "manual_review_required": False,
                        },
                        "consistency": {
                            "score": 66,
                            "weight": 0.2,
                            "deduction_reason": "",
                            "manual_review_required": False,
                        },
                        "traceability": {
                            "score": 66,
                            "weight": 0.15,
                            "deduction_reason": "",
                            "manual_review_required": False,
                        },
                        "risk_coverage": {
                            "score": 66,
                            "weight": 0.15,
                            "deduction_reason": "",
                            "manual_review_required": False,
                        },
                        "operability": {
                            "score": 66,
                            "weight": 0.1,
                            "deduction_reason": "",
                            "manual_review_required": False,
                        },
                    },
                },
            },
        ],
    )

    edge_path = find_edge_executable()
    out_dir = (repo_root / ".test" / "runs").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    shots_dir = out_dir / f"ac36-ac43-shots-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    shots_dir.mkdir(parents=True, exist_ok=True)

    entry_script = (repo_root / "scripts" / "workflow_entry_cli.py").resolve()
    web_script = (repo_root / "scripts" / "workflow_web_server.py").resolve()
    base = f"http://{args.host}:{args.port}"
    proc = subprocess.Popen(
        [
            sys.executable,
            str(web_script),
            "--root",
            runtime_root.as_posix(),
            "--entry-script",
            entry_script.as_posix(),
            "--agent-search-root",
            workspace_root.as_posix(),
            "--allow-manual-policy-input",
            "0",
            "--host",
            args.host,
            "--port",
            str(args.port),
        ],
        cwd=str(repo_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    results: list[tuple[str, bool, dict]] = []
    screenshots: dict[str, str] = {}
    probe_payloads: dict[str, dict] = {}
    payload_samples: dict[str, dict] = {}

    def capture_probe(
        name: str,
        params: dict[str, str],
        *,
        width: int = 1366,
        height: int = 900,
        budget_ms: int = 12000,
    ) -> dict:
        url = base + "/?" + urlencode(params)
        dom = edge_dump_dom(edge_path, url=url, width=width, height=height, budget_ms=budget_ms)
        probe = parse_policy_probe_output(dom)
        shot = shots_dir / f"{name}.png"
        edge_screenshot(edge_path, url=url, screenshot_path=shot, width=width, height=height, budget_ms=budget_ms)
        screenshots[name] = shot.as_posix()
        probe_payloads[name] = probe
        return probe

    try:
        wait_health(base)
        status, payload = call(base, "GET", "/api/agents")
        if status != 200 or not payload.get("ok"):
            raise RuntimeError(f"/api/agents failed: {status} {payload}")
        agents = list(payload.get("agents") or [])
        ready = agent_by_name(agents, "v2-ready-agent")
        conflict = agent_by_name(agents, "v2-conflict-agent")
        no_evidence = agent_by_name(agents, "v2-no-evidence-agent")

        # Capture policy confirmation payload with new fields.
        s_code, s_payload = call(
            base,
            "POST",
            "/api/sessions",
            {
                "agent_name": "v2-conflict-agent",
                "focus": "Phase0 Day3: web workbench + real-agent gate execution",
                "agent_search_root": workspace_root.as_posix(),
                "is_test_data": False,
            },
        )
        policy_confirmation_after = {}
        if s_code in (200, 409):
            policy_confirmation_after = extract_policy_confirmation_payload(s_payload)
        payload_samples["after"] = policy_confirmation_after
        payload_samples["before_like"] = normalize_gate_payload_for_before(policy_confirmation_after)

        # Probe screenshots and UI checks.
        probe_default = capture_probe(
            "01-order-and-default-collapsed",
            {
                "policy_probe": "1",
                "policy_probe_stage": "manual",
                "policy_probe_agent": "v2-conflict-agent",
                "policy_probe_capture_delay_ms": "1300",
            },
            width=1366,
            height=900,
        )
        capture_probe(
            "02-default-collapsed-focus",
            {
                "policy_probe": "1",
                "policy_probe_stage": "manual",
                "policy_probe_agent": "v2-conflict-agent",
                "policy_probe_capture_delay_ms": "1300",
            },
            width=1366,
            height=760,
        )
        probe_score = capture_probe(
            "03-score-dimensions-and-explain",
            {
                "policy_probe": "1",
                "policy_probe_stage": "manual",
                "policy_probe_agent": "v2-conflict-agent",
                "policy_probe_capture_delay_ms": "1300",
            },
            width=1366,
            height=1180,
        )
        capture_probe(
            "04-constraints-triple",
            {
                "policy_probe": "1",
                "policy_probe_stage": "manual",
                "policy_probe_agent": "v2-conflict-agent",
                "policy_probe_capture_delay_ms": "1300",
            },
            width=1366,
            height=980,
        )
        probe_gate_expanded = capture_probe(
            "05-gate-expanded",
            {
                "policy_probe": "1",
                "policy_probe_stage": "manual",
                "policy_probe_agent": "v2-conflict-agent",
                "policy_probe_capture_delay_ms": "1400",
                "policy_probe_expand_gate": "1",
            },
            width=1366,
            height=980,
        )
        probe_no_evidence = capture_probe(
            "06-no-evidence-manual-review",
            {
                "policy_probe": "1",
                "policy_probe_stage": "manual",
                "policy_probe_agent": "v2-no-evidence-agent",
                "policy_probe_capture_delay_ms": "1300",
            },
            width=1366,
            height=980,
        )

        # AC-36
        order = list(probe_default.get("modal_module_order") or [])
        titles = [str(v or "").strip() for v in (probe_default.get("modal_module_titles") or []) if str(v or "").strip()]
        ac36_ok = (
            order[:3] == ["core", "constraints", "score"]
            and len(titles) >= 3
            and titles[0] == "角色/目标"
            and titles[1] == "职责边界（must / must_not / preconditions）"
            and titles[2] == "角色设定门禁得分项"
            and not bool(probe_default.get("modal_has_legacy_constraints_title"))
            and not bool(probe_default.get("modal_has_legacy_core_title"))
        )
        results.append(
            (
                "AC-36 首屏优先信息顺序",
                ac36_ok,
                {
                    "modal_module_order": order,
                    "modal_module_titles": titles,
                    "probe": probe_default,
                    "screenshot": screenshots.get("01-order-and-default-collapsed", ""),
                },
            )
        )

        # AC-37
        ac37_ok = (
            bool(probe_default.get("policy_modal_open"))
            and not bool(probe_default.get("modal_score_open"))
            and not bool(probe_default.get("modal_gate_open"))
            and not bool(probe_default.get("modal_evidence_open"))
        )
        results.append(
            (
                "AC-37 折叠策略生效",
                ac37_ok,
                {
                    "modal_score_open": probe_default.get("modal_score_open"),
                    "modal_gate_open": probe_default.get("modal_gate_open"),
                    "modal_evidence_open": probe_default.get("modal_evidence_open"),
                    "probe": probe_default,
                    "screenshot": screenshots.get("02-default-collapsed-focus", ""),
                },
            )
        )

        # AC-38
        ac38_ok = int(probe_score.get("score_dimension_count") or 0) >= 6
        results.append(
            (
                "AC-38 评分维度完整",
                ac38_ok,
                {"probe": probe_score, "screenshot": screenshots.get("03-score-dimensions-and-explain", "")},
            )
        )

        # AC-39
        ac39_ok = bool(
            int(probe_score.get("score_low_with_explain_count") or 0) >= 1
            or int(probe_score.get("score_manual_review_count") or 0) >= 1
        )
        results.append(
            (
                "AC-39 扣分可追溯",
                ac39_ok,
                {"probe": probe_score, "screenshot": screenshots.get("03-score-dimensions-and-explain", "")},
            )
        )

        # AC-40
        dims_noe = no_evidence.get("score_dimensions") if isinstance(no_evidence.get("score_dimensions"), dict) else {}
        manual_review_dims = []
        for key, dim in dims_noe.items():
            if not isinstance(dim, dict):
                continue
            if bool(dim.get("manual_review_required")) and "无证据不直接扣分" in str(dim.get("deduction_reason") or ""):
                manual_review_dims.append(key)
        ac40_ok = bool(manual_review_dims) and str(no_evidence.get("clarity_gate") or "").lower() != "auto"
        results.append(
            (
                "AC-40 无证据不扣分",
                ac40_ok,
                {
                    "manual_review_dims": manual_review_dims,
                    "agent_gate": no_evidence.get("clarity_gate"),
                    "agent": no_evidence,
                    "probe": probe_no_evidence,
                },
            )
        )

        # AC-41
        ac41_ok = bool(probe_gate_expanded.get("modal_gate_open")) and bool(probe_gate_expanded.get("gate_fields_complete"))
        results.append(
            (
                "AC-41 门禁与来源完整保留",
                ac41_ok,
                {"probe": probe_gate_expanded, "screenshot": screenshots.get("05-gate-expanded", "")},
            )
        )

        # AC-42
        ready_dims = ready.get("score_dimensions") if isinstance(ready.get("score_dimensions"), dict) else {}
        ac42_ok = str(ready.get("score_model") or "") == "v2" and len(ready_dims.keys()) >= 6
        cache_score_model = ""
        db_path = runtime_root / "state" / "workflow.db"
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "SELECT policy_payload_json FROM agent_policy_cache WHERE agent_path LIKE ? LIMIT 1",
                    ("%v2-ready-agent/AGENTS.md",),
                ).fetchone()
                if row:
                    payload_json = json.loads(str(row["policy_payload_json"] or "{}"))
                    cache_score_model = str(payload_json.get("score_model") or "")
            finally:
                conn.close()
        ac42_ok = ac42_ok and cache_score_model == "v2"
        results.append(
            (
                "AC-42 评分版本可追溯",
                ac42_ok,
                {"ready_agent_score_model": ready.get("score_model"), "cache_score_model": cache_score_model, "agent": ready},
            )
        )

        # AC-43
        cst = conflict.get("constraints") if isinstance(conflict.get("constraints"), dict) else {}
        ac43_ok = (
            int(len(cst.get("must") or [])) > 0
            and int(len(cst.get("must_not") or [])) > 0
            and int(len(cst.get("preconditions") or [])) > 0
            and str(conflict.get("clarity_gate") or "").lower() != "auto"
        )
        results.append(
            (
                "AC-43 职责边界门禁联动",
                ac43_ok,
                {
                    "constraints_counts": {
                        "must": len(cst.get("must") or []),
                        "must_not": len(cst.get("must_not") or []),
                        "preconditions": len(cst.get("preconditions") or []),
                    },
                    "clarity_gate": conflict.get("clarity_gate"),
                    "agent": conflict,
                    "probe": probe_default,
                    "screenshot": screenshots.get("04-constraints-triple", ""),
                },
            )
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_md = out_dir / f"ac36-ac43-acceptance-{stamp}.md"
    out_json = out_dir / f"ac36-ac43-acceptance-{stamp}.json"
    payload_dump = out_dir / f"ac36-ac43-payload-sample-{stamp}.json"

    passed = sum(1 for _name, ok, _detail in results if ok)
    failed = len(results) - passed

    out_obj = {
        "ok": failed == 0,
        "passed": passed,
        "failed": failed,
        "results": [{"name": name, "ok": ok, "detail": detail} for name, ok, detail in results],
        "screenshots": screenshots,
        "probe_payloads": probe_payloads,
        "payload_samples": payload_samples,
        "runtime_root": runtime_root.as_posix(),
    }
    out_json.write_text(json.dumps(out_obj, ensure_ascii=False, indent=2), encoding="utf-8")
    payload_dump.write_text(json.dumps(payload_samples, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# AC-36 ~ AC-43 acceptance",
        "",
        f"- generated_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- runtime_root: {runtime_root.as_posix()}",
        f"- screenshots_dir: {shots_dir.as_posix()}",
        f"- passed: {passed}",
        f"- failed: {failed}",
        "",
        "## results",
        "",
    ]
    for name, ok, detail in results:
        lines.append(f"### {'PASS' if ok else 'FAIL'} - {name}")
        lines.append("```json")
        lines.append(json.dumps(detail, ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")
    lines.extend(
        [
            "## screenshots",
            "```json",
            json.dumps(screenshots, ensure_ascii=False, indent=2),
            "```",
            "",
            "## payload_samples",
            "```json",
            json.dumps(payload_samples, ensure_ascii=False, indent=2),
            "```",
            "",
            "## artifacts",
            f"- json: {out_json.as_posix()}",
            f"- payload_sample: {payload_dump.as_posix()}",
            "",
        ]
    )
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(out_md.as_posix())
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
