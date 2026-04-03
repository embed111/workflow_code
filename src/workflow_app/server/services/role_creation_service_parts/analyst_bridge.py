from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from workflow_app.server.services.codex_exec_monitor import resolve_codex_command, run_monitored_subprocess


ROLE_CREATION_ANALYST_AGENT_NAME = "Analyst"
ROLE_CREATION_ANALYST_PROVIDER = "codex"
ROLE_CREATION_ANALYST_STAGE_KEYS = (
    "persona_collection",
    "capability_generation",
    "review_and_alignment",
    "acceptance_confirmation",
)

def _role_creation_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(content or ""), encoding="utf-8")


def _role_creation_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _role_creation_dialogue_trace_dir(root: Path, session_id: str) -> Path:
    now_dt = now_local()
    stamp = f"{date_key(now_dt)}-{now_dt.strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}"
    session_token = safe_token(session_id, "session", 80) or "session"
    return root / "logs" / "runs" / f"role-creation-analyst-{session_token}-{stamp}"


def _resolve_role_creation_codex_bin() -> str:
    override = str(__import__("os").getenv("WORKFLOW_ROLE_CREATION_CODEX_BIN") or "").strip()
    if override:
        override_path = Path(override).expanduser()
        return override_path.as_posix() if override_path.exists() else override
    return resolve_codex_command()


def _resolve_role_creation_dialogue_agent(cfg: Any) -> dict[str, str]:
    search_root = getattr(cfg, "agent_search_root", None)
    if isinstance(search_root, Path):
        root_path = search_root.resolve(strict=False)
    elif search_root:
        root_path = Path(str(search_root)).resolve(strict=False)
    else:
        root_path = Path(cfg.root).resolve(strict=False).parent
    analyst_workspace = (root_path / ROLE_CREATION_ANALYST_AGENT_NAME).resolve(strict=False)
    if analyst_workspace.exists() and analyst_workspace.is_dir():
        return {
            "agent_name": ROLE_CREATION_ANALYST_AGENT_NAME,
            "workspace_path": analyst_workspace.as_posix(),
            "provider": ROLE_CREATION_ANALYST_PROVIDER,
            "source": "workspace_analyst",
        }
    fallback_workspace = Path(cfg.root).resolve(strict=False)
    return {
        "agent_name": fallback_workspace.name or "workflow",
        "workspace_path": fallback_workspace.as_posix(),
        "provider": ROLE_CREATION_ANALYST_PROVIDER,
        "source": "workflow_fallback",
    }


def _role_creation_extract_codex_event_text(event: dict[str, Any]) -> str:
    if not isinstance(event, dict):
        return ""
    if str(event.get("type") or "").strip() != "item.completed":
        return ""
    item = event.get("item")
    if not isinstance(item, dict):
        return ""
    if str(item.get("type") or "").strip() != "agent_message":
        return ""
    text = str(item.get("text") or "").strip()
    if text:
        return text
    content = item.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for node in content:
        if not isinstance(node, dict):
            continue
        text_part = str(node.get("text") or node.get("output_text") or "").strip()
        if text_part:
            parts.append(text_part)
    return "\n".join(parts).strip()


def _role_creation_extract_json_objects(text: str) -> list[dict[str, Any]]:
    raw = str(text or "").strip()
    if not raw:
        return []
    out: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    idx = 0
    total = len(raw)
    while idx < total:
        start = raw.find("{", idx)
        if start < 0:
            break
        try:
            value, consumed = decoder.raw_decode(raw[start:])
        except Exception:
            idx = start + 1
            continue
        idx = start + max(1, consumed)
        if isinstance(value, dict):
            out.append(value)
    return out


def _role_creation_normalize_priority_label(raw: Any, *, default: str = "P1") -> str:
    text = _normalize_text(raw, max_len=4).upper()
    if text in {"P0", "P1", "P2", "P3"}:
        return text
    if text in {"0", "1", "2", "3"}:
        return "P" + text
    return default


def _role_creation_sanitized_history(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in list(messages or [])[-24:]:
        attachments = [
            {
                "file_name": str(attachment.get("file_name") or "").strip(),
                "content_type": str(attachment.get("content_type") or "").strip(),
                "size_bytes": int(attachment.get("size_bytes") or 0),
            }
            for attachment in list(item.get("attachments") or [])
            if isinstance(attachment, dict)
        ]
        out.append(
            {
                "role": str(item.get("role") or "").strip().lower(),
                "message_type": str(item.get("message_type") or "").strip().lower(),
                "content": _normalize_text(item.get("content"), max_len=2000),
                "attachments": attachments[:6],
                "created_at": str(item.get("created_at") or "").strip(),
            }
        )
    return out


def _role_creation_sanitized_stage_snapshot(stages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for stage in list(stages or []):
        active_tasks = [
            {
                "node_id": str(task.get("node_id") or "").strip(),
                "task_name": str(task.get("task_name") or "").strip(),
                "status": str(task.get("status") or "").strip().lower(),
                "status_text": str(task.get("status_text") or "").strip(),
                "expected_artifact": str(task.get("expected_artifact") or "").strip(),
            }
            for task in list(stage.get("active_tasks") or [])[:8]
            if isinstance(task, dict)
        ]
        archived_tasks = [
            {
                "node_id": str(task.get("node_id") or "").strip(),
                "task_name": str(task.get("task_name") or "").strip(),
                "close_reason": str(task.get("close_reason") or "").strip(),
            }
            for task in list(stage.get("archived_tasks") or [])[:8]
            if isinstance(task, dict)
        ]
        out.append(
            {
                "stage_key": str(stage.get("stage_key") or "").strip(),
                "title": str(stage.get("title") or "").strip(),
                "state": str(stage.get("state") or "").strip(),
                "active_tasks": active_tasks,
                "archived_tasks": archived_tasks,
                "analyst_action": dict(stage.get("analyst_action") or {}),
            }
        )
    return out


def _build_role_creation_analyst_prompt(
    *,
    detail: dict[str, Any],
    latest_user_message: str,
    dialogue_agent: dict[str, str],
) -> str:
    session = dict(detail.get("session") or {})
    profile = dict(detail.get("profile") or {})
    role_spec = dict(detail.get("role_spec") or {})
    messages = _role_creation_sanitized_history(list(detail.get("messages") or []))
    stages = _role_creation_sanitized_stage_snapshot(list(detail.get("stages") or []))
    current_stage_key = str(session.get("current_stage_key") or "persona_collection").strip().lower()
    can_start = bool(profile.get("can_start"))
    return "\n".join(
        [
            "你正在以当前工作区的分析 agent 身份，处理 workflow 的“创建角色”对话回合。",
            "这是一条后端 JSON contract 调用，不是普通开放式聊天。",
            "不要修改任何文件，不要执行脚本，不要维护记忆，不要更新状态文档，不要创建原型或需求文档文件。",
            "你只负责：分析引导、角色画像收口、能力包/知识沉淀/首批任务收口、判断是否该建议后台任务、判断是否该建议阶段切换。",
            "若用户有明确“另起任务/后台去做/去整理并回传”之类委派语义，且当前 session_status=creating，可返回 delegate_tasks。",
            "不要把你自己在当前会话里直接完成的分析引导、追问、判断动作伪装成后台任务。",
            "不要编造已完成的任务、截图、回传结果、执行证据或验收结论。",
            "role_spec 已包含 role_profile_spec / capability_package_spec / knowledge_asset_plan / seed_delivery_plan / start_gate / recent_changes / pending_questions。",
            "不要把能力模块、默认交付策略、格式边界、知识资产、首批任务误写成只有六要素画像的追问或结论。",
            "如果 start_gate.can_start=false，优先围绕 blockers / pending_questions 继续收口，不要提前说“可以开始创建”。",
            "ready_to_start 必须尊重当前给定的 role_spec / missing_fields / can_start，不要自行放宽门槛。",
            "assistant_reply 用中文，直接对用户说话，保持分析引导口吻，简洁明确。",
            "",
            "返回格式：仅输出一个 JSON 对象，不要输出 JSON 之外的任何文字。",
            "{",
            '  "assistant_reply": "string",',
            '  "delegate_tasks": [',
            "    {",
            '      "title": "string",',
            '      "goal": "string",',
            '      "stage_key": "persona_collection|capability_generation|review_and_alignment",',
            '      "expected_artifact": "string",',
            '      "priority": "P0|P1|P2|P3"',
            "    }",
            "  ],",
            '  "suggested_stage_key": "persona_collection|capability_generation|review_and_alignment|acceptance_confirmation",',
            '  "ready_to_start": false,',
            '  "missing_fields": ["role_name"],',
            '  "reasoning_summary": "string"',
            "}",
            "",
            "上下文：",
            f"- dialogue_agent_name: {str(dialogue_agent.get('agent_name') or '').strip()}",
            f"- dialogue_agent_workspace_path: {str(dialogue_agent.get('workspace_path') or '').strip()}",
            f"- session_id: {str(session.get('session_id') or '').strip()}",
            f"- session_title: {str(session.get('session_title') or '').strip()}",
            f"- session_status: {str(session.get('status') or '').strip().lower()}",
            f"- current_stage_key: {current_stage_key}",
            f"- current_stage_title: {str(session.get('current_stage_title') or '').strip()}",
            f"- current_assignment_ticket_id: {str(session.get('assignment_ticket_id') or '').strip()}",
            f"- can_start: {json.dumps(can_start, ensure_ascii=False)}",
            f"- missing_fields: {json.dumps(list(profile.get('missing_fields') or []), ensure_ascii=False)}",
            f"- missing_labels: {json.dumps(list(profile.get('missing_labels') or []), ensure_ascii=False)}",
            f"- role_spec: {json.dumps(role_spec, ensure_ascii=False)}",
            f"- stages: {json.dumps(stages, ensure_ascii=False)}",
            f"- messages: {json.dumps(messages, ensure_ascii=False)}",
            f"- latest_user_message: {json.dumps(_normalize_text(latest_user_message, max_len=4000), ensure_ascii=False)}",
        ]
    )


def _normalize_role_creation_bridge_result(
    raw_result: dict[str, Any],
    *,
    fallback_text: str,
    detail: dict[str, Any],
    dialogue_agent: dict[str, str],
) -> dict[str, Any]:
    session = dict(detail.get("session") or {})
    profile = dict(detail.get("profile") or {})
    role_spec = dict(detail.get("role_spec") or {})
    current_stage_key = str(session.get("current_stage_key") or "persona_collection").strip().lower() or "persona_collection"
    role_name = _role_creation_title_from_spec(role_spec, session.get("session_title") or "")
    assistant_reply = _normalize_text(raw_result.get("assistant_reply"), max_len=4000) or _normalize_text(fallback_text, max_len=4000)
    delegate_tasks: list[dict[str, Any]] = []
    for item in list(raw_result.get("delegate_tasks") or [])[:3]:
        if not isinstance(item, dict):
            continue
        goal = _normalize_text(item.get("goal") or item.get("node_goal") or item.get("content"), max_len=4000)
        title = _normalize_text(item.get("title") or item.get("task_name") or item.get("node_name"), max_len=200)
        if not title and goal:
            title = _delegate_task_title(goal, role_name)
        if not goal or not title:
            continue
        stage_key = _normalize_text(item.get("stage_key"), max_len=80).lower()
        if stage_key not in {"persona_collection", "capability_generation", "review_and_alignment"}:
            stage_key = _infer_task_stage_key(goal, current_stage_key)
        delegate_tasks.append(
            {
                "title": title,
                "goal": goal,
                "stage_key": stage_key,
                "expected_artifact": _normalize_text(
                    item.get("expected_artifact"),
                    max_len=240,
                )
                or _role_creation_default_artifact_name(stage_key, title),
                "priority": _role_creation_normalize_priority_label(
                    item.get("priority"),
                    default="P0" if stage_key == "persona_collection" else "P1",
                ),
            }
        )
    suggested_stage_key = _normalize_text(raw_result.get("suggested_stage_key"), max_len=80).lower()
    if suggested_stage_key not in ROLE_CREATION_ANALYST_STAGE_KEYS:
        suggested_stage_key = current_stage_key
    missing_fields = [
        str(item).strip()
        for item in list(raw_result.get("missing_fields") or [])
        if str(item or "").strip()
    ]
    if not missing_fields:
        missing_fields = [str(item).strip() for item in list(profile.get("missing_fields") or []) if str(item).strip()]
    return {
        "assistant_reply": assistant_reply,
        "delegate_tasks": delegate_tasks,
        "suggested_stage_key": suggested_stage_key,
        "ready_to_start": _parse_bool_flag(raw_result.get("ready_to_start"), default=bool(profile.get("can_start"))),
        "missing_fields": missing_fields,
        "reasoning_summary": _normalize_text(raw_result.get("reasoning_summary"), max_len=1000),
        "dialogue_agent_name": str(dialogue_agent.get("agent_name") or "").strip(),
        "dialogue_agent_workspace_path": str(dialogue_agent.get("workspace_path") or "").strip(),
        "provider": str(dialogue_agent.get("provider") or ROLE_CREATION_ANALYST_PROVIDER).strip() or ROLE_CREATION_ANALYST_PROVIDER,
        "contract_has_json": bool(raw_result),
    }


def _role_creation_dialogue_error_reply(error_code: str, dialogue_agent: dict[str, str]) -> str:
    code = str(error_code or "").strip().lower()
    agent_name = str(dialogue_agent.get("agent_name") or "分析师").strip() or "分析师"
    if code == "analyst_workspace_not_found":
        return f"当前没有找到 {agent_name} 工作区，这轮还没法切到真实分析对话。请先检查对话分析师路径配置。"
    if code == "codex_command_not_found":
        return f"当前环境没有可用的 codex 命令，{agent_name} 这轮还没真正接上。请先检查服务端 codex 安装。"
    if code == "codex_exec_timeout":
        return f"{agent_name} 这轮分析超时了，我还没有拿到可用回复。请稍后重试，或把本轮需求拆短一点再发。"
    if code.startswith("codex_exec_failed_exit_"):
        return f"{agent_name} 这轮执行异常退出了，我还没有拿到可用回复。请稍后重试。"
    if code == "codex_output_invalid_json":
        return f"{agent_name} 已返回内容，但没有产出可解析的结构化结果，这轮暂时无法自动创建后台任务。请直接重试一次。"
    return f"{agent_name} 这轮暂时不可用，我还没有拿到可继续推进的分析结果。请稍后重试。"


def run_role_creation_analyst_dialogue(
    cfg: Any,
    *,
    detail: dict[str, Any],
    latest_user_message: str,
    operator: str,
) -> dict[str, Any]:
    session = dict(detail.get("session") or {})
    session_id = str(session.get("session_id") or "").strip()
    dialogue_agent = _resolve_role_creation_dialogue_agent(cfg)
    workspace_path = Path(str(dialogue_agent.get("workspace_path") or "").strip()).resolve(strict=False)
    trace_dir = _role_creation_dialogue_trace_dir(Path(cfg.root).resolve(strict=False), session_id or "session")
    prompt_path = trace_dir / "prompt.txt"
    stdout_path = trace_dir / "stdout.txt"
    stderr_path = trace_dir / "stderr.txt"
    result_path = trace_dir / "result.json"
    meta_path = trace_dir / "meta.json"
    prompt_text = _build_role_creation_analyst_prompt(
        detail=detail,
        latest_user_message=latest_user_message,
        dialogue_agent=dialogue_agent,
    )
    _role_creation_write_text(prompt_path, prompt_text)
    meta_payload = {
        "session_id": session_id,
        "operator": str(operator or "").strip(),
        "dialogue_agent": dialogue_agent,
        "monitor_mode": "no_total_timeout",
        "result_exit_grace_s": 8,
    }
    _role_creation_write_json(meta_path, meta_payload)
    trace_ref = relative_to_root(Path(cfg.root).resolve(strict=False), trace_dir)
    if not workspace_path.exists() or not workspace_path.is_dir():
        result = {
            "ok": False,
            "error": "analyst_workspace_not_found",
            "trace_ref": trace_ref,
            "dialogue_agent_name": str(dialogue_agent.get("agent_name") or "").strip(),
            "dialogue_agent_workspace_path": str(dialogue_agent.get("workspace_path") or "").strip(),
            "provider": str(dialogue_agent.get("provider") or ROLE_CREATION_ANALYST_PROVIDER).strip() or ROLE_CREATION_ANALYST_PROVIDER,
            "assistant_reply": _role_creation_dialogue_error_reply("analyst_workspace_not_found", dialogue_agent),
            "delegate_tasks": [],
            "suggested_stage_key": str(session.get("current_stage_key") or "persona_collection").strip().lower() or "persona_collection",
            "ready_to_start": bool((detail.get("profile") or {}).get("can_start")),
            "missing_fields": list((detail.get("profile") or {}).get("missing_fields") or []),
        }
        _role_creation_write_json(result_path, result)
        return result
    codex_bin = _resolve_role_creation_codex_bin()
    if not codex_bin:
        result = {
            "ok": False,
            "error": "codex_command_not_found",
            "trace_ref": trace_ref,
            "dialogue_agent_name": str(dialogue_agent.get("agent_name") or "").strip(),
            "dialogue_agent_workspace_path": str(dialogue_agent.get("workspace_path") or "").strip(),
            "provider": str(dialogue_agent.get("provider") or ROLE_CREATION_ANALYST_PROVIDER).strip() or ROLE_CREATION_ANALYST_PROVIDER,
            "assistant_reply": _role_creation_dialogue_error_reply("codex_command_not_found", dialogue_agent),
            "delegate_tasks": [],
            "suggested_stage_key": str(session.get("current_stage_key") or "persona_collection").strip().lower() or "persona_collection",
            "ready_to_start": bool((detail.get("profile") or {}).get("can_start")),
            "missing_fields": list((detail.get("profile") or {}).get("missing_fields") or []),
        }
        _role_creation_write_json(result_path, result)
        return result
    command = [
        codex_bin,
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--json",
        "--skip-git-repo-check",
        "--add-dir",
        workspace_path.as_posix(),
        "-C",
        workspace_path.as_posix(),
        "-",
    ]
    stdout_text = ""
    stderr_text = ""
    error_code = ""
    monitor_info: dict[str, Any] = {}
    try:
        completion_state = {"ready": False}

        def _observe_stdout(line: str) -> None:
            cleaned = str(line or "").strip()
            if not cleaned:
                return
            try:
                event = json.loads(cleaned)
            except Exception:
                return
            if not isinstance(event, dict):
                return
            if str(event.get("type") or "").strip() == "turn.completed":
                completion_state["ready"] = True
                return
            text = _role_creation_extract_codex_event_text(event)
            if text and _role_creation_extract_json_objects(text):
                completion_state["ready"] = True

        result = run_monitored_subprocess(
            command=command,
            cwd=workspace_path,
            stdin_text=prompt_text,
            on_stdout_line=_observe_stdout,
            completion_checker=lambda: bool(completion_state["ready"]),
        )
        stdout_text = result.stdout_text
        stderr_text = result.stderr_text
        monitor_info = dict(result.monitor or {})
        if int(result.exit_code or 0) != 0:
            error_code = f"codex_exec_failed_exit_{int(result.exit_code or 0)}"
    except Exception:
        error_code = "codex_exec_exception"
    _role_creation_write_text(stdout_path, stdout_text)
    _role_creation_write_text(stderr_path, stderr_text)
    message_texts: list[str] = []
    for line in stdout_text.splitlines():
        cleaned = str(line or "").strip()
        if not cleaned:
            continue
        try:
            event = json.loads(cleaned)
        except Exception:
            continue
        if isinstance(event, dict):
            text = _role_creation_extract_codex_event_text(event)
            if text:
                message_texts.append(text)
    json_candidates: list[dict[str, Any]] = []
    for text in message_texts:
        json_candidates.extend(_role_creation_extract_json_objects(text))
    if not json_candidates:
        json_candidates.extend(_role_creation_extract_json_objects(stdout_text))
    raw_result = json_candidates[-1] if json_candidates else {}
    fallback_text = _normalize_text(message_texts[-1] if message_texts else "", max_len=4000)
    normalized = _normalize_role_creation_bridge_result(
        raw_result,
        fallback_text=fallback_text,
        detail=detail,
        dialogue_agent=dialogue_agent,
    )
    if not raw_result and not normalized["assistant_reply"] and not error_code:
        error_code = "codex_output_invalid_json"
    if error_code and not normalized["assistant_reply"]:
        normalized["assistant_reply"] = _role_creation_dialogue_error_reply(error_code, dialogue_agent)
    normalized["ok"] = bool(normalized["assistant_reply"])
    normalized["error"] = error_code
    normalized["trace_ref"] = trace_ref
    _role_creation_write_json(
        result_path,
        {
            **normalized,
            "command": command,
            "monitor": monitor_info,
            "stdout_path": relative_to_root(Path(cfg.root).resolve(strict=False), stdout_path),
            "stderr_path": relative_to_root(Path(cfg.root).resolve(strict=False), stderr_path),
            "prompt_path": relative_to_root(Path(cfg.root).resolve(strict=False), prompt_path),
        },
    )
    return normalized


def _create_role_creation_tasks_from_intents(
    cfg: Any,
    *,
    session_summary: dict[str, Any],
    task_refs: list[dict[str, Any]],
    task_intents: list[dict[str, Any]],
    operator: str,
) -> list[dict[str, Any]]:
    if _normalize_session_status(session_summary.get("status")) != "creating":
        return []
    created_tasks: list[dict[str, Any]] = []
    known_refs = list(task_refs)
    for intent in list(task_intents or [])[:3]:
        if not isinstance(intent, dict):
            continue
        stage_key = _normalize_text(intent.get("stage_key"), max_len=80).lower()
        if stage_key not in {"persona_collection", "capability_generation", "review_and_alignment"}:
            stage_key = _infer_task_stage_key(
                str(intent.get("goal") or intent.get("title") or ""),
                str(session_summary.get("current_stage_key") or "persona_collection"),
            )
        node_name = _normalize_text(intent.get("title"), max_len=200)
        node_goal = _normalize_text(intent.get("goal"), max_len=4000)
        if not node_name or not node_goal:
            continue
        expected_artifact = _normalize_text(intent.get("expected_artifact"), max_len=240) or _role_creation_default_artifact_name(stage_key, node_name)
        task = _create_role_creation_task_internal(
            cfg,
            session_summary=session_summary,
            task_refs=known_refs,
            stage_key=stage_key,
            node_name=node_name,
            node_goal=node_goal,
            expected_artifact=expected_artifact,
            operator=operator,
            priority=_role_creation_normalize_priority_label(
                intent.get("priority"),
                default="P0" if stage_key == "persona_collection" else "P1",
            ),
        )
        created_tasks.append(task)
        known_refs.append(
            {
                "session_id": str(session_summary.get("session_id") or "").strip(),
                "ticket_id": str(task.get("ticket_id") or "").strip(),
                "node_id": str(task.get("node_id") or "").strip(),
                "stage_key": stage_key,
                "stage_index": int(task.get("stage_index") or 0),
                "relation_state": "active",
                "close_reason": "",
            }
        )
        session_summary["current_stage_key"] = stage_key
        session_summary["current_stage_index"] = int(task.get("stage_index") or 0)
    return created_tasks
