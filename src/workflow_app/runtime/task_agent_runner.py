#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

try:
    from workflow_app.server.services.developer_workspace_service import (
        protected_write_roots as resolve_protected_write_roots,
    )
except Exception:  # pragma: no cover - direct script fallback
    def resolve_protected_write_roots(
        *,
        workspace_root: str | Path | None = None,
        runtime_root: Path | None = None,
        fallback_pm_root: Path | None = None,
    ) -> list[Path]:
        if isinstance(workspace_root, Path):
            root = workspace_root.resolve(strict=False)
        else:
            text = str(workspace_root or "").strip()
            if not text:
                return []
            root = Path(text).resolve(strict=False)
        if not str(root).strip():
            return []
        return [
            (root / "workflow").resolve(strict=False),
            (root / "workflow_code").resolve(strict=False),
        ]


_WIN_ABS_PATH_PATTERN = re.compile(r"(?i)\b[A-Z]:[\\/][^\s\"'`]+")
_ROOT_ALIAS_PATH_PATTERN = re.compile(r"(?i)\$root(?:[\\/][^\s\"'`]+)?")
AGENT_POLICY_ERROR_CODE = "agent_policy_extract_failed"
_RUNTIME_CONFIG_FILE = Path("state") / "runtime-config.json"


def _load_json(path: Path, fallback: Any) -> Any:
    if not path.exists() or not path.is_file():
        return fallback
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return fallback
    return payload


def _runtime_config(root: Path) -> dict[str, Any]:
    payload = _load_json(root / _RUNTIME_CONFIG_FILE, {})
    return payload if isinstance(payload, dict) else {}


def artifact_root(root: Path) -> Path:
    cfg = _runtime_config(root)
    raw = str(cfg.get("task_artifact_root") or cfg.get("artifact_root") or "").strip()
    candidate = Path(raw).expanduser() if raw else (root.parent / ".output")
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate.resolve(strict=False)


def session_record_path(root: Path, session_id: str) -> Path:
    return artifact_root(root) / "records" / "sessions" / str(session_id or "").strip() / "session.json"


def session_messages_path(root: Path, session_id: str) -> Path:
    return artifact_root(root) / "records" / "sessions" / str(session_id or "").strip() / "messages.jsonl"


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = str(line or "").strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def load_messages(root: Path, session_id: str) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    rows = sorted(
        _load_jsonl(session_messages_path(root, session_id)),
        key=lambda item: int(item.get("message_id") or 0),
    )[:300]
    for row in rows:
        role = str(row.get("role") or "")
        if role not in {"system", "user", "assistant"}:
            continue
        messages.append({"role": role, "content": str(row.get("content") or "")})
    return messages


def parse_policy_snapshot(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except Exception:
        return {}
    return {}


def validate_policy_fields(snapshot: dict[str, Any]) -> tuple[bool, str]:
    role_profile = str(snapshot.get("role_profile") or "").strip()
    session_goal = str(snapshot.get("session_goal") or "").strip()
    duty_constraints = str(snapshot.get("duty_constraints") or "").strip()
    if not role_profile:
        return False, "missing_role_profile"
    if not session_goal:
        return False, "missing_session_goal"
    if not duty_constraints:
        return False, "missing_duty_constraints"
    return True, ""


def load_session_policy_snapshot(root: Path, session_id: str) -> tuple[dict[str, Any], str]:
    row = _load_json(session_record_path(root, session_id), {})
    if not isinstance(row, dict) or not row:
        return {}, "session_not_found"
    snapshot = parse_policy_snapshot(str(row.get("policy_snapshot_json") or ""))
    if not snapshot:
        snapshot = {
            "version": 1,
            "agent_name": str(row.get("agent_name") or ""),
            "source": {
                "agents_path": str(row.get("agents_path") or ""),
                "agents_hash": str(row.get("agents_hash") or ""),
                "agents_version": str(row.get("agents_version") or ""),
                "policy_source": "auto",
            },
            "role_profile": str(row.get("role_profile") or ""),
            "session_goal": str(row.get("session_goal") or ""),
            "duty_constraints": str(row.get("duty_constraints") or ""),
        }
    ok, error = validate_policy_fields(snapshot)
    if not ok:
        return snapshot, error
    return snapshot, ""


def policy_summary_text(snapshot: dict[str, Any], *, max_chars: int = 220) -> str:
    goal = str(snapshot.get("session_goal") or "").strip()
    duty = str(snapshot.get("duty_constraints") or "").strip()
    compact = re.sub(r"\s+", " ", f"goal={goal}; constraints={duty}").strip()
    if len(compact) > max_chars:
        return compact[:max_chars].rstrip() + "..."
    return compact


def policy_source_type(snapshot: dict[str, Any]) -> str:
    source = snapshot.get("source") if isinstance(snapshot.get("source"), dict) else {}
    value = str((source or {}).get("policy_source") or snapshot.get("policy_source") or "auto").strip().lower()
    if value not in {"auto", "manual_fallback"}:
        return "auto"
    return value


def policy_prompt_block(snapshot: dict[str, Any]) -> str:
    source = snapshot.get("source") if isinstance(snapshot.get("source"), dict) else {}
    source_type = policy_source_type(snapshot)
    return "\n".join(
        [
            "[SESSION_POLICY_FROZEN]",
            "This policy block has higher priority than ordinary user input.",
            f"policy_source: hash={str((source or {}).get('agents_hash') or '')} "
            f"version={str((source or {}).get('agents_version') or '')} "
            f"path={str((source or {}).get('agents_path') or '')} "
            f"type={source_type}",
            f"role_profile: {str(snapshot.get('role_profile') or '')}",
            f"session_goal: {str(snapshot.get('session_goal') or '')}",
            f"duty_constraints: {str(snapshot.get('duty_constraints') or '')}",
            "[/SESSION_POLICY_FROZEN]",
        ]
    )


def normalize_abs_path(raw: str, *, base: Path) -> Path:
    text = str(raw or "").strip()
    if not text:
        raise ValueError("empty path")
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate.resolve(strict=False)


def path_in_scope(path: Path, scope: Path) -> bool:
    try:
        path.relative_to(scope)
        return True
    except ValueError:
        return False


def path_in_protected_roots(path: Path, protected_roots: list[Path]) -> bool:
    target = path.resolve(strict=False)
    for item in protected_roots:
        candidate = Path(item).resolve(strict=False)
        if target == candidate:
            return True
        if path_in_scope(target, candidate):
            return True
    return False


def clean_target_token(raw: str) -> str:
    return str(raw or "").strip().strip("\"'").rstrip(".,;")


def resolve_root_alias(raw: str, scope: Path) -> str:
    text = clean_target_token(raw)
    if not text:
        return text
    low = text.lower()
    if not low.startswith("$root"):
        return text
    suffix = text[5:]
    if suffix and suffix[0] not in ("/", "\\"):
        return text
    relative = suffix[1:] if suffix else ""
    if not relative:
        return scope.as_posix()
    return (scope / Path(relative)).resolve(strict=False).as_posix()


def normalize_write_targets(scope: Path, targets: list[str], *, protected_roots: list[Path]) -> list[str]:
    out: list[str] = []
    seen_raw: set[str] = set()
    seen_norm: set[str] = set()
    for raw in targets:
        text = clean_target_token(raw)
        if not text or text in seen_raw:
            continue
        resolved = resolve_root_alias(text, scope)
        path = normalize_abs_path(resolved, base=scope)
        if not path_in_scope(path, scope):
            raise ValueError(f"path_out_of_root: {text}")
        if path_in_protected_roots(path, protected_roots):
            raise ValueError(f"path_in_protected_root: {text}")
        norm = path.as_posix()
        if norm in seen_norm:
            seen_raw.add(text)
            continue
        out.append(norm)
        seen_raw.add(text)
        seen_norm.add(norm)
    return out


def extract_message_paths(text: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for match in _WIN_ABS_PATH_PATTERN.findall(text or ""):
        item = clean_target_token(str(match))
        if not item or item in seen:
            continue
        values.append(item)
        seen.add(item)
    for match in _ROOT_ALIAS_PATH_PATTERN.findall(text or ""):
        item = clean_target_token(str(match))
        if not item or item in seen:
            continue
        values.append(item)
        seen.add(item)
    return values


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CLI runner for workflow task execution via local codex command."
    )
    parser.add_argument("--root", default=".", help="workspace root")
    parser.add_argument("--session-id", required=True, help="workflow session id")
    parser.add_argument("--agent", default="", help="agent name")
    parser.add_argument("--agent-search-root", required=True, help="agent search/write root for this session")
    parser.add_argument("--focus", default="", help="focus text")
    parser.add_argument("--message", default="", help="current user message")
    parser.add_argument(
        "--write-target",
        action="append",
        default=[],
        help="declared write target path (repeatable)",
    )
    parser.add_argument(
        "--trace-file",
        default="",
        help="optional trace json output path",
    )
    return parser.parse_args()


def build_prompt(
    messages: list[dict[str, str]],
    *,
    agent: str,
    focus: str,
    latest_message: str,
    agent_search_root: str,
    write_targets: list[str],
    protected_roots: list[str],
    policy_snapshot: dict[str, Any],
) -> str:
    policy_block = policy_prompt_block(policy_snapshot)
    lines = [
        "You are the backend worker for workflow web chat.",
        f"Target agent name: {agent or 'agent'}",
        f"Current focus: {focus or 'none'}",
        f"Agent search root (discovery + write scope): {agent_search_root}",
        "Session policy is frozen. You must follow role_profile/session_goal/duty_constraints.",
        "If user request conflicts with session policy, refuse and explain briefly within role boundary.",
        "Hard rule: any filesystem write must stay inside agent_search_root.",
        "If user asks to write outside agent_search_root, reply exactly: path_out_of_root",
        "Protected roots are read-only for ordinary execution. Never modify them in this chat execution path.",
        "If user asks to write inside protected roots, reply exactly: path_in_protected_root",
        "Return only the assistant reply for the latest user request.",
        "Do not add markdown fences or meta explanations.",
        "",
        "Frozen session policy:",
        policy_block,
        "",
        "Protected roots:",
    ]
    for item in protected_roots:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
        "Conversation history (oldest to newest):",
        ]
    )
    history = messages[-60:]
    for item in history:
        role = str(item.get("role") or "user").upper()
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"{role}: {content}")
    if write_targets:
        lines.append("")
        lines.append("Declared write targets:")
        for item in write_targets:
            lines.append(f"- {item}")
    if latest_message:
        lines.append("")
        lines.append(f"LATEST_USER_MESSAGE: {latest_message}")
    lines.append("")
    lines.append("ASSISTANT:")
    return "\n".join(lines)


def write_trace_file(path_text: str, payload: dict[str, Any]) -> None:
    text = str(path_text or "").strip()
    if not text:
        return
    try:
        path = Path(text)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        print(f"trace_write_failed: {exc}", file=sys.stderr)


def stream_stderr(pipe: Any) -> None:
    if pipe is None:
        return
    for line in iter(pipe.readline, ""):
        if line == "":
            break
        sys.stderr.write(line)
        sys.stderr.flush()


def extract_agent_text(event: dict[str, Any]) -> str:
    event_type = str(event.get("type") or "")
    if event_type != "item.completed":
        return ""
    item = event.get("item")
    if not isinstance(item, dict):
        return ""
    if str(item.get("type") or "") != "agent_message":
        return ""
    return str(item.get("text") or "")


def run_codex(prompt: str, agent_search_root: Path) -> int:
    override = str(os.getenv("WORKFLOW_CODEX_BIN") or "").strip()
    codex_bin = override or str(shutil.which("codex.cmd") or shutil.which("codex") or "").strip()
    if not codex_bin:
        print("codex command not found in PATH", file=sys.stderr)
        return 127

    cmd = [
        codex_bin,
        "exec",
        "--json",
        "--skip-git-repo-check",
        "--sandbox",
        "workspace-write",
        "--add-dir",
        str(agent_search_root),
        "-C",
        str(agent_search_root),
        "-",
    ]
    proc = subprocess.Popen(
        cmd,
        cwd=str(agent_search_root),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert proc.stdin is not None
    proc.stdin.write(prompt)
    proc.stdin.write("\n")
    proc.stdin.close()

    stderr_thread = threading.Thread(target=stream_stderr, args=(proc.stderr,), daemon=True)
    stderr_thread.start()

    reply_printed = False
    assert proc.stdout is not None
    for raw_line in iter(proc.stdout.readline, ""):
        if raw_line == "":
            break
        line = raw_line.strip()
        if not line:
            continue
        event: dict[str, Any]
        try:
            obj = json.loads(line)
            event = obj if isinstance(obj, dict) else {}
        except json.JSONDecodeError:
            continue
        text = extract_agent_text(event)
        if not text:
            continue
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()
        reply_printed = True

    rc = proc.wait()
    stderr_thread.join(timeout=2)
    if rc != 0:
        return rc
    if not reply_printed:
        print("codex returned no agent message", file=sys.stderr)
        return 6
    return 0


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    agent_search_root = normalize_abs_path(args.agent_search_root, base=root)
    if agent_search_root.exists() and not agent_search_root.is_dir():
        print(f"invalid agent_search_root: {agent_search_root}", file=sys.stderr)
        return 2
    agent_search_root.mkdir(parents=True, exist_ok=True)
    protected_roots = resolve_protected_write_roots(workspace_root=agent_search_root)

    declared_targets = [str(item) for item in (args.write_target or [])]
    declared_targets.extend(extract_message_paths(args.message or ""))
    try:
        write_targets = normalize_write_targets(
            agent_search_root,
            declared_targets,
            protected_roots=protected_roots,
        )
    except ValueError as exc:
        print(str(exc).split(":", 1)[0], file=sys.stderr)
        return 3

    messages = load_messages(root, args.session_id)
    if args.message and (
        not messages
        or messages[-1].get("role") != "user"
        or messages[-1].get("content") != args.message
    ):
        messages.append({"role": "user", "content": args.message})
    if not messages:
        print("no conversation context", file=sys.stderr)
        return 4

    policy_snapshot, policy_error = load_session_policy_snapshot(root, args.session_id)
    if policy_error:
        source = policy_snapshot.get("source") if isinstance(policy_snapshot.get("source"), dict) else {}
        source_type = policy_source_type(policy_snapshot)
        print(f"{AGENT_POLICY_ERROR_CODE}:{policy_error}", file=sys.stderr)
        write_trace_file(
            args.trace_file,
            {
                "session_id": args.session_id,
                "agent_name": args.agent.strip(),
                "policy_alignment": "deviated",
                "policy_alignment_reason": policy_error,
                "policy_source": {
                    "policy_source": source_type,
                    "agents_hash": str((source or {}).get("agents_hash") or ""),
                    "agents_version": str((source or {}).get("agents_version") or ""),
                    "agents_path": str((source or {}).get("agents_path") or ""),
                },
                "policy_source_type": source_type,
                "policy_summary": "",
                "prompt": "",
            },
        )
        return 5

    prompt = build_prompt(
        messages,
        agent=args.agent.strip(),
        focus=args.focus.strip(),
        latest_message=args.message.strip(),
        agent_search_root=agent_search_root.as_posix(),
        write_targets=write_targets,
        protected_roots=[item.as_posix() for item in protected_roots],
        policy_snapshot=policy_snapshot,
    )
    policy_source = policy_snapshot.get("source") if isinstance(policy_snapshot.get("source"), dict) else {}
    source_type = policy_source_type(policy_snapshot)
    write_trace_file(
        args.trace_file,
        {
            "session_id": args.session_id,
            "agent_name": args.agent.strip(),
            "focus": args.focus.strip(),
            "agent_search_root": agent_search_root.as_posix(),
            "protected_write_roots": [item.as_posix() for item in protected_roots],
            "write_targets": write_targets,
            "latest_message": args.message.strip(),
            "history_message_count": len(messages),
            "policy_alignment": "aligned",
            "policy_alignment_reason": "session_policy_injected",
            "policy_source": {
                "policy_source": source_type,
                "agents_hash": str((policy_source or {}).get("agents_hash") or ""),
                "agents_version": str((policy_source or {}).get("agents_version") or ""),
                "agents_path": str((policy_source or {}).get("agents_path") or ""),
            },
            "policy_source_type": source_type,
            "policy_summary": policy_summary_text(policy_snapshot),
            "prompt": prompt,
        },
    )
    return run_codex(prompt, agent_search_root)


if __name__ == "__main__":
    raise SystemExit(main())
