from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PM_DAILY_TASK_RELATIVE_PATH = Path("pm") / "PM每日任务清单.md"
PM_DAILY_HISTORY_RELATIVE_PATH = Path("pm") / "daily-execution-history"
PM_DAILY_LEARNING_RELATIVE_PATH = Path("pm") / "daily-learning-reports"
DEFAULT_PM_DAILY_KEEP_COUNT = 7
DEFAULT_PM_DAILY_BASE_URL = "http://127.0.0.1:8090"
CORE_PM_LEARNING_AGENTS = (
    "workflow",
    "workflow_devmate",
    "workflow_testmate",
    "workflow_qualitymate",
    "workflow_bugmate",
)
_DATED_FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
_DATED_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_STATUS_RE = re.compile(r"^\s*-\s*status:\s*`([^`]+)`", re.MULTILINE)


def _path_candidates(root: Path | None, relative_path: Path) -> list[Path]:
    anchor = root.resolve(strict=False) if isinstance(root, Path) else Path(".").resolve(strict=False)
    candidates: list[Path] = []
    seen: set[str] = set()
    for base in [anchor, *anchor.parents]:
        candidate = (base / relative_path).resolve(strict=False)
        key = candidate.as_posix()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
    return candidates


def resolve_pm_root(root: Path | None = None) -> Path | None:
    for candidate in _path_candidates(root, PM_DAILY_TASK_RELATIVE_PATH):
        if candidate.exists() and candidate.is_file():
            return candidate.parent
    return None


def _normalize_report_date(report_date: date | str | None = None) -> date:
    if isinstance(report_date, date):
        return report_date
    if isinstance(report_date, str) and str(report_date).strip():
        return date.fromisoformat(str(report_date).strip())
    return date.today()


def _dated_history_files(history_root: Path) -> list[Path]:
    if not history_root.exists() or not history_root.is_dir():
        return []
    return sorted(
        path for path in history_root.iterdir() if path.is_file() and _DATED_FILE_RE.fullmatch(path.name)
    )


def _dated_learning_dirs(learning_root: Path) -> list[Path]:
    if not learning_root.exists() or not learning_root.is_dir():
        return []
    return sorted(
        path for path in learning_root.iterdir() if path.is_dir() and _DATED_DIR_RE.fullmatch(path.name)
    )


def _cleanup_candidates(items: list[Path], keep_count: int) -> list[Path]:
    safe_keep = max(1, int(keep_count or DEFAULT_PM_DAILY_KEEP_COUNT))
    if len(items) <= safe_keep:
        return []
    return items[: len(items) - safe_keep]


def _read_json_url(base_url: str, path: str) -> dict[str, Any]:
    req = Request(str(base_url or "").rstrip("/") + path, method="GET")
    try:
        with urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8")
    except HTTPError as exc:  # pragma: no cover - defensive path
        body = exc.read().decode("utf-8")
        raise RuntimeError(f"request failed: {path} -> {exc.code} {body}") from exc
    except URLError as exc:  # pragma: no cover - defensive path
        raise RuntimeError(f"request failed: {path} -> {exc}") from exc
    payload = json.loads(body) if body else {}
    if not isinstance(payload, dict):
        raise RuntimeError(f"unexpected payload type for {path}: {type(payload).__name__}")
    return payload


def _payload_or_fetch(
    *,
    payload: dict[str, Any] | None,
    base_url: str,
    path: str,
) -> dict[str, Any]:
    if isinstance(payload, dict):
        return dict(payload)
    return _read_json_url(base_url, path)


def _extract_markdown_status(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return ""
    matched = _STATUS_RE.search(text)
    return str(matched.group(1) or "").strip() if matched else ""


def _relative_to(base: Path, target: Path) -> str:
    try:
        return target.relative_to(base).as_posix()
    except Exception:
        return target.as_posix()


def load_pm_daily_governance_status(
    root: Path | None = None,
    *,
    report_date: date | str | None = None,
    required_agents: Iterable[str] = CORE_PM_LEARNING_AGENTS,
    keep_count: int = DEFAULT_PM_DAILY_KEEP_COUNT,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": False,
        "date": "",
        "status": "missing",
        "daily_history_exists": False,
        "daily_history_status": "",
        "daily_history_path": "",
        "learning_report_dir": "",
        "existing_learning_reports": [],
        "missing_learning_reports": [],
        "history_cleanup_candidates": [],
        "learning_cleanup_candidates": [],
        "retention_limit": int(keep_count or DEFAULT_PM_DAILY_KEEP_COUNT),
    }
    pm_root = resolve_pm_root(root)
    if not isinstance(pm_root, Path):
        return payload
    target_date = _normalize_report_date(report_date)
    date_text = target_date.isoformat()
    history_root = pm_root / "daily-execution-history"
    learning_root = pm_root / "daily-learning-reports"
    daily_history_path = history_root / f"{date_text}.md"
    learning_dir = learning_root / date_text
    existing_learning_reports = sorted(
        path.stem for path in learning_dir.glob("*.md") if path.is_file()
    ) if learning_dir.exists() else []
    required_agent_ids = [str(agent_id).strip() for agent_id in required_agents if str(agent_id).strip()]
    missing_learning_reports = [
        agent_id for agent_id in required_agent_ids if agent_id not in existing_learning_reports
    ]
    daily_history_status = _extract_markdown_status(daily_history_path)
    history_files = _dated_history_files(history_root)
    learning_dirs = _dated_learning_dirs(learning_root)
    status = "missing"
    if daily_history_path.exists() and not missing_learning_reports:
        status = "completed"
    elif daily_history_path.exists():
        status = "in_progress"
    elif existing_learning_reports:
        status = "learning_only"
    payload.update(
        {
            "ok": True,
            "date": date_text,
            "status": status,
            "daily_history_exists": daily_history_path.exists(),
            "daily_history_status": daily_history_status,
            "daily_history_path": _relative_to(pm_root.parent, daily_history_path),
            "learning_report_dir": _relative_to(pm_root.parent, learning_dir),
            "existing_learning_reports": existing_learning_reports,
            "missing_learning_reports": missing_learning_reports,
            "history_cleanup_candidates": [
                _relative_to(pm_root.parent, path)
                for path in _cleanup_candidates(history_files, keep_count)
            ],
            "learning_cleanup_candidates": [
                _relative_to(pm_root.parent, path)
                for path in _cleanup_candidates(learning_dirs, keep_count)
            ],
            "retention_limit": max(1, int(keep_count or DEFAULT_PM_DAILY_KEEP_COUNT)),
        }
    )
    return payload


def _schedule_item(items: list[dict[str, Any]], schedule_name: str) -> dict[str, Any]:
    for item in list(items or []):
        if str(item.get("schedule_name") or "").strip() == schedule_name:
            return dict(item)
    return {}


def _ops_conclusion(status_payload: dict[str, Any], runtime_upgrade_payload: dict[str, Any]) -> str:
    if not bool(status_payload.get("ok")):
        return "需要关注"
    if int(status_payload.get("truth_mismatch_count") or 0) > 0:
        return "需要关注"
    if not bool(runtime_upgrade_payload.get("ok")):
        return "需要关注"
    return "继续推进"


def _learning_prompt_line(agent_id: str, governance_status: dict[str, Any]) -> str:
    existing = set(governance_status.get("existing_learning_reports") or [])
    missing = set(governance_status.get("missing_learning_reports") or [])
    normalized_agent_id = "workflow" if agent_id == "workflow(pm)" else agent_id
    if normalized_agent_id in existing:
        return f"- `{agent_id}`: 今日真实学习报告已存在，后续继续把新增经验补到同一份报告或下一轮实战任务里。"
    if normalized_agent_id == "workflow":
        return "- `workflow(pm)`: 补写今日真实学习报告，聚焦 active 版本的当前最高价值切片和这轮治理判断。"
    if normalized_agent_id in missing:
        return f"- `{agent_id}`: 补写今日真实学习报告，聚焦自己负责泳道的最新实战观察、方法提炼和下一步动作。"
    return f"- `{agent_id}`: 继续围绕当前 active 版本补齐自己的真实学习报告和后续实战切片。"


def _schedule_next_text(item: dict[str, Any]) -> str:
    if not isinstance(item, dict) or not item:
        return "-"
    next_trigger = str(item.get("next_trigger_text") or item.get("next_trigger_at") or "").strip()
    last_node_id = str(item.get("last_result_node_id") or "").strip()
    last_status = str(item.get("last_result_status_text") or item.get("last_result_status") or "").strip()
    if next_trigger and last_node_id:
        return f"{last_node_id} / {next_trigger} / {last_status or '待执行'}"
    if next_trigger:
        return next_trigger
    return last_node_id or "-"


def render_pm_daily_execution_history(
    *,
    report_date: date | str | None,
    governance_status: dict[str, Any],
    healthz_payload: dict[str, Any],
    status_payload: dict[str, Any],
    schedules_payload: dict[str, Any],
    runtime_upgrade_payload: dict[str, Any],
    required_agents: Iterable[str] = CORE_PM_LEARNING_AGENTS,
) -> str:
    target_date = _normalize_report_date(report_date)
    date_text = target_date.isoformat()
    conclusion = _ops_conclusion(status_payload, runtime_upgrade_payload)
    execution_status = "completed" if not list(governance_status.get("missing_learning_reports") or []) else "in_progress"
    pm_version_status = dict(status_payload.get("pm_version_status") or {})
    mainline_item = _schedule_item(list(schedules_payload.get("items") or []), "[持续迭代] workflow")
    patrol_item = _schedule_item(list(schedules_payload.get("items") or []), "pm持续唤醒 - workflow 主线巡检")
    missing_learning_reports = ", ".join(list(governance_status.get("missing_learning_reports") or [])) or "-"
    history_cleanup_candidates = ", ".join(list(governance_status.get("history_cleanup_candidates") or [])) or "-"
    learning_cleanup_candidates = ", ".join(list(governance_status.get("learning_cleanup_candidates") or [])) or "-"
    summary_lines = [
        f"- `/healthz={'ok' if bool(healthz_payload.get('ok')) else 'not_ok'}`",
        (
            "- `/api/status` 当前为 "
            f"`running_task_count={int(status_payload.get('running_task_count') or 0)} / "
            f"queued_task_count={int(status_payload.get('queued_task_count') or 0)} / "
            f"truth_mismatch_count={int(status_payload.get('truth_mismatch_count') or 0)} / "
            f"active_version={str(status_payload.get('active_version') or '').strip() or '-'} / "
            f"lane={str(pm_version_status.get('lane') or '').strip() or '-'} / "
            f"baseline={str(pm_version_status.get('baseline') or '').strip() or '-'} / "
            f"workflow_mainline_starvation_state={str(status_payload.get('workflow_mainline_starvation_state') or '').strip() or '-'}"
            "`"
        ),
        (
            "- `/api/runtime-upgrade/status` 当前为 "
            f"`current_version={str(runtime_upgrade_payload.get('current_version') or '').strip() or '-'} / "
            f"candidate_version={str(runtime_upgrade_payload.get('candidate_version') or '').strip() or '-'} / "
            f"candidate_is_newer={str(runtime_upgrade_payload.get('candidate_is_newer')).lower()} / "
            f"can_upgrade={str(runtime_upgrade_payload.get('can_upgrade')).lower()} / "
            f"running_task_count={int(runtime_upgrade_payload.get('running_task_count') or 0)}`"
        ),
        (
            "- `/api/schedules` 当前为 "
            f"`total={int(schedules_payload.get('total') or 0)} / "
            f"mainline_next={_schedule_next_text(mainline_item)} / "
            f"patrol_next={_schedule_next_text(patrol_item)}`"
        ),
        f"- 今日学习报告缺口：`{missing_learning_reports}`",
        f"- 当前历史清理候选：`history={history_cleanup_candidates} / learning={learning_cleanup_candidates}`",
    ]
    learning_lines = [
        _learning_prompt_line(agent_id, governance_status)
        for agent_id in [f"workflow(pm)"] + [agent_id for agent_id in required_agents if agent_id != "workflow"]
    ]
    next_lines = [
        f"- daily_history_path: `{str(governance_status.get('daily_history_path') or '')}`",
        f"- learning_report_dir: `{str(governance_status.get('learning_report_dir') or '')}`",
        f"- missing_learning_reports: `{missing_learning_reports}`",
        f"- history_cleanup_candidates: `{history_cleanup_candidates}`",
        f"- learning_cleanup_candidates: `{learning_cleanup_candidates}`",
        f"- mainline_next: `{_schedule_next_text(mainline_item)}`",
        f"- patrol_next: `{_schedule_next_text(patrol_item)}`",
    ]
    return "\n".join(
        [
            f"# PM 每日执行结果 {date_text}",
            "",
            f"- date: `{date_text}`",
            "- source_tasks: `pm/PM每日任务清单.md`",
            f"- status: `{execution_status}`",
            "- auto_generated: `true`",
            "",
            "## system_ops_check",
            f"- executed_at: `{datetime.now().astimezone().isoformat(timespec='seconds')}`",
            f"- conclusion: `{conclusion}`",
            "- summary:",
            *summary_lines,
            "- evidence_ref: `auto-generated from /healthz /api/status /api/runtime-upgrade/status /api/schedules`",
            "",
            "## learning_prompt",
            *learning_lines,
            "",
            "## next",
            *next_lines,
            "",
        ]
    )


def _delete_paths(paths: Iterable[Path]) -> list[str]:
    deleted: list[str] = []
    for path in list(paths):
        try:
            if path.is_dir():
                for child in sorted(path.rglob("*"), reverse=True):
                    if child.is_file():
                        child.unlink()
                    elif child.is_dir():
                        child.rmdir()
                path.rmdir()
            elif path.exists():
                path.unlink()
            deleted.append(path.as_posix())
        except FileNotFoundError:
            continue
    return deleted


def run_pm_daily_governance(
    root: Path | None = None,
    *,
    report_date: date | str | None = None,
    base_url: str = DEFAULT_PM_DAILY_BASE_URL,
    keep_count: int = DEFAULT_PM_DAILY_KEEP_COUNT,
    required_agents: Iterable[str] = CORE_PM_LEARNING_AGENTS,
    overwrite_existing: bool = False,
    healthz_payload: dict[str, Any] | None = None,
    status_payload: dict[str, Any] | None = None,
    schedules_payload: dict[str, Any] | None = None,
    runtime_upgrade_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pm_root = resolve_pm_root(root)
    if not isinstance(pm_root, Path):
        return {"ok": False, "error": "pm_root_not_found"}
    target_date = _normalize_report_date(report_date)
    history_root = (pm_root / "daily-execution-history").resolve(strict=False)
    learning_root = (pm_root / "daily-learning-reports").resolve(strict=False)
    history_root.mkdir(parents=True, exist_ok=True)
    learning_root.mkdir(parents=True, exist_ok=True)
    history_path = history_root / f"{target_date.isoformat()}.md"
    learning_dir = learning_root / target_date.isoformat()
    learning_dir.mkdir(parents=True, exist_ok=True)

    pre_status = load_pm_daily_governance_status(
        pm_root.parent,
        report_date=target_date,
        required_agents=required_agents,
        keep_count=keep_count,
    )
    daily_history_action = "kept_existing"
    history_existed = history_path.exists()
    if overwrite_existing or not history_path.exists():
        loaded_healthz = _payload_or_fetch(payload=healthz_payload, base_url=base_url, path="/healthz")
        loaded_status = _payload_or_fetch(payload=status_payload, base_url=base_url, path="/api/status")
        loaded_schedules = _payload_or_fetch(payload=schedules_payload, base_url=base_url, path="/api/schedules")
        loaded_runtime_upgrade = _payload_or_fetch(
            payload=runtime_upgrade_payload,
            base_url=base_url,
            path="/api/runtime-upgrade/status",
        )
        history_content = render_pm_daily_execution_history(
            report_date=target_date,
            governance_status=pre_status,
            healthz_payload=loaded_healthz,
            status_payload=loaded_status,
            schedules_payload=loaded_schedules,
            runtime_upgrade_payload=loaded_runtime_upgrade,
            required_agents=required_agents,
        )
        history_path.write_text(history_content, encoding="utf-8")
        daily_history_action = "updated" if history_existed else "created"

    history_files = _dated_history_files(history_root)
    learning_dirs = _dated_learning_dirs(learning_root)
    deleted_history = _delete_paths(_cleanup_candidates(history_files, keep_count))
    deleted_learning_dirs = _delete_paths(_cleanup_candidates(learning_dirs, keep_count))
    post_status = load_pm_daily_governance_status(
        pm_root.parent,
        report_date=target_date,
        required_agents=required_agents,
        keep_count=keep_count,
    )
    return {
        "ok": True,
        "date": target_date.isoformat(),
        "pm_root": pm_root.as_posix(),
        "daily_history_action": daily_history_action,
        "daily_history_path": post_status.get("daily_history_path"),
        "learning_report_dir": post_status.get("learning_report_dir"),
        "deleted_history": [
            _relative_to(pm_root.parent, Path(path)) for path in deleted_history
        ],
        "deleted_learning_dirs": [
            _relative_to(pm_root.parent, Path(path)) for path in deleted_learning_dirs
        ],
        "missing_learning_reports": list(post_status.get("missing_learning_reports") or []),
        "status": str(post_status.get("status") or "").strip(),
        "retention_limit": int(post_status.get("retention_limit") or keep_count),
    }
