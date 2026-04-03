from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import uuid
from pathlib import Path
from typing import Any

connect_db: Any = None
safe_token: Any = None
now_local: Any = None
iso_ts: Any = None
date_key: Any = None
path_in_scope: Any = None
extract_agent_policy_fields: Any = None
relative_to_root: Any = None
event_file: Any = None
persist_event: Any = None
event_id: Any = None
list_available_agents: Any = None
TRAINER_SOURCE_ROOT: Path = Path('.')
TRAINING_PRIORITY_LEVELS = ('P0', 'P1', 'P2', 'P3')
TRAINING_PRIORITY_RANK = {name: idx for idx, name in enumerate(TRAINING_PRIORITY_LEVELS)}
AGENT_LIFECYCLE_STATES = ("released", "pre_release", "unknown")
TRAINING_GATE_STATES = ("trainable", "frozen_switched")

AGENT_VECTOR_ICON_SET = (
    "persona_analyst",
    "persona_engineer",
    "persona_operator",
    "persona_architect",
    "persona_trainer",
    "persona_auditor",
)


def _normalize_path_token(value: str) -> str:
    return str(value or "").strip().lower().replace("\\", "/")


def is_system_or_test_workspace(
    workspace_path: str,
    *,
    agent_search_root: Path | None,
) -> bool:
    path = _normalize_path_token(workspace_path)
    if not path:
        return False
    root_token = _normalize_path_token(agent_search_root.as_posix() if isinstance(agent_search_root, Path) else "")
    root_is_test_runtime = "/state/test-runtime/" in root_token or "/.test/" in root_token
    if root_is_test_runtime and root_token and path.startswith(root_token):
        return False
    return (
        "/workflow/state/" in path
        or "/workflow/.runtime/" in path
        or "/state/test-runtime/" in path
        or "/test-runtime/" in path
        or "/.test/" in path
        or "/.runtime/" in path
    )


class TrainingCenterError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        message: str,
        code: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.extra = dict(extra or {})


def bind_runtime(deps: dict[str, Any]) -> None:
    if not isinstance(deps, dict):
        return
    globals().update(deps)
    modules = globals().get("_TRAINING_CENTER_MODULES")
    if isinstance(modules, tuple):
        for module in modules:
            try:
                module.bind_runtime_symbols(globals())
            except Exception:
                continue

def training_plan_id() -> str:
    ts = now_local()
    return f"plan-{date_key(ts)}-{ts.strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}"


def training_queue_task_id() -> str:
    ts = now_local()
    return f"tq-{date_key(ts)}-{ts.strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}"


def training_run_id_text() -> str:
    ts = now_local()
    return f"trun-{date_key(ts)}-{ts.strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}"


def training_audit_id() -> str:
    ts = now_local()
    return f"taud-{date_key(ts)}-{ts.strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}"


def build_agent_vector_icon(agent_name: str, agent_id: str = "") -> str:

    seed = (str(agent_id or "").strip() + "|" + str(agent_name or "").strip()).strip("|")

    if not seed:

        return AGENT_VECTOR_ICON_SET[0]

    digest = hashlib.sha1(seed.lower().encode("utf-8")).hexdigest()

    idx = int(digest[:4], 16) % len(AGENT_VECTOR_ICON_SET)

    return AGENT_VECTOR_ICON_SET[idx]


def normalize_training_priority(raw: Any, *, required: bool = True) -> str:
    text = str(raw or "").strip().upper()
    if not text:
        if required:
            raise TrainingCenterError(400, "优先级必填", "priority_required")
        return ""
    if text not in TRAINING_PRIORITY_LEVELS:
        raise TrainingCenterError(
            400,
            "优先级仅允许 P0/P1/P2/P3",
            "priority_invalid",
            {"allowed": list(TRAINING_PRIORITY_LEVELS)},
        )
    return text


def normalize_training_source(raw: Any, *, default: str = "manual") -> str:
    text = str(raw or "").strip().lower()
    if not text:
        text = default
    if text not in {"manual", "auto_analysis"}:
        text = default
    return text


def normalize_training_test_flag(raw: Any, *, default: bool = False) -> bool:
    if raw is None:
        return bool(default)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(int(raw))
    text = str(raw or "").strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return bool(default)


def normalize_lifecycle_state(raw: Any) -> str:
    value = str(raw or "").strip().lower()
    if value == "pre_release":
        return "pre_release"
    if value == "unknown":
        return "unknown"
    return "released"


def normalize_training_gate_state(raw: Any) -> str:
    value = str(raw or "").strip().lower()
    if value == "frozen_switched":
        return "frozen_switched"
    return "trainable"


def derive_training_gate_state(
    *,
    lifecycle_state: str,
    current_version: str,
    latest_release_version: str,
    parent_agent_id: str,
    preferred: str = "",
) -> str:
    lifecycle = normalize_lifecycle_state(lifecycle_state)
    if lifecycle == "pre_release":
        return "trainable"
    preferred_state = normalize_training_gate_state(preferred)
    if str(parent_agent_id or "").strip():
        # 克隆角色默认可训练，除非已显式冻结。
        if preferred_state == "frozen_switched":
            return "frozen_switched"
        return "trainable"
    current = str(current_version or "").strip()
    latest = str(latest_release_version or "").strip()
    if current and latest and current != latest:
        return "frozen_switched"
    return "trainable"


def normalize_training_tasks(raw: Any) -> list[str]:
    if isinstance(raw, list):
        out = [str(item or "").strip() for item in raw]
        return [item for item in out if item]
    text = str(raw or "").strip()
    if not text:
        return []
    parts = [part.strip() for part in re.split(r"[\r\n]+", text) if str(part or "").strip()]
    if parts:
        return parts[:50]
    return [text]


def _training_similarity_text(goal: str, tasks: list[str], criteria: str) -> str:
    parts = [
        str(goal or "").strip(),
        " | ".join([str(item or "").strip() for item in tasks if str(item or "").strip()]),
        str(criteria or "").strip(),
    ]
    joined = " ".join([part for part in parts if part]).strip().lower()
    joined = re.sub(r"\s+", " ", joined)
    return joined


def _training_similarity_tokens(text: str) -> set[str]:
    raw = str(text or "").strip().lower()
    if not raw:
        return set()
    tokens = {
        token
        for token in re.split(r"[^0-9a-zA-Z\u4e00-\u9fff]+", raw)
        if len(token) >= 2
    }
    if tokens:
        return tokens
    compact = re.sub(r"\s+", "", raw)
    if len(compact) < 2:
        return {compact} if compact else set()
    out: set[str] = set()
    for idx in range(0, len(compact) - 1):
        out.add(compact[idx : idx + 2])
    return out


def training_plan_similarity_hit(
    *,
    candidate_goal: str,
    candidate_tasks: list[str],
    candidate_criteria: str,
    existing_goal: str,
    existing_tasks: list[str],
    existing_criteria: str,
) -> bool:
    a = _training_similarity_text(candidate_goal, candidate_tasks, candidate_criteria)
    b = _training_similarity_text(existing_goal, existing_tasks, existing_criteria)
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) >= 12 and a in b:
        return True
    if len(b) >= 12 and b in a:
        return True
    tokens_a = _training_similarity_tokens(a)
    tokens_b = _training_similarity_tokens(b)
    if not tokens_a or not tokens_b:
        return False
    inter = tokens_a.intersection(tokens_b)
    if not inter:
        return False
    ratio_a = float(len(inter)) / float(max(1, len(tokens_a)))
    ratio_b = float(len(inter)) / float(max(1, len(tokens_b)))
    return ratio_a >= 0.6 or ratio_b >= 0.6


def _run_git_readonly(workspace: Path, args: list[str], *, timeout_s: int = 8) -> tuple[bool, str]:
    cmd = ["git", "-C", workspace.as_posix()] + [str(arg) for arg in args]
    try:
        proc = subprocess.run(
            cmd,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout_s,
        )
    except Exception:
        return False, ""
    if proc.returncode != 0:
        return False, ""
    return True, str(proc.stdout or "")


def _run_git_readonly_verbose(
    workspace: Path,
    args: list[str],
    *,
    timeout_s: int = 8,
) -> tuple[bool, str, str]:
    cmd = ["git", "-C", workspace.as_posix()] + [str(arg) for arg in args]
    try:
        proc = subprocess.run(
            cmd,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout_s,
        )
    except Exception as exc:
        return False, "", str(exc or "")
    return (
        proc.returncode == 0,
        str(proc.stdout or ""),
        str(proc.stderr or ""),
    )


def _git_available_in_scope(workspace: Path, scope: Path) -> bool:
    if not path_in_scope(workspace.resolve(strict=False), scope.resolve(strict=False)):
        return False
    ok, out = _run_git_readonly(workspace, ["rev-parse", "--is-inside-work-tree"])
    if not ok:
        return False
    return str(out or "").strip().lower().startswith("true")


def _list_workspace_local_skills(workspace: Path) -> list[str]:
    base = Path(str(workspace or "")).resolve(strict=False)
    skills_root = base / ".codex" / "skills"
    if not skills_root.exists() or not skills_root.is_dir():
        return []
    rows: list[str] = []
    for child in skills_root.iterdir():
        name = str(child.name or "").strip()
        if not name or name.startswith("."):
            continue
        if not child.is_dir():
            continue
        if not (child / "SKILL.md").exists():
            continue
        rows.append(name)
    rows.sort(key=lambda value: value.lower())
    return rows


def _looks_like_system_release_note(release_notes: str) -> bool:
    text = str(release_notes or "")
    if not text:
        return False
    return (
        "发布版本:" in text
        and "角色能力摘要:" in text
        and "角色知识范围:" in text
        and "技能:" in text
    )


def _parse_git_release_rows(
    workspace: Path,
    *,
    limit: int = 50,
) -> tuple[str, str, list[dict[str, str]]]:
    # 口径：基于 tag 信息判定发布格式；不合规 tag 归类为 normal_commit。
    fmt = "%(refname:short)%1f%(creatordate:iso-strict)%1f%(contents)%1f%(objectname:short)%1e"
    ok, out = _run_git_readonly(
        workspace,
        [
            "for-each-ref",
            "--sort=-creatordate",
            f"--count={max(1, int(limit))}",
            f"--format={fmt}",
            "refs/tags",
        ],
    )
    if not ok:
        return "", "", []
    current_version = ""
    last_release_at = ""
    rows: list[dict[str, str]] = []
    for raw in str(out or "").split("\x1e"):
        record = str(raw or "")
        if not record.strip():
            continue
        line = record.rstrip("\r\n\x00")
        if not line:
            continue
        parts = line.split("\x1f")
        if len(parts) < 4:
            continue
        version_label = str(parts[0] or "").strip()
        released_at = str(parts[1] or "").strip()
        release_notes = str("\x1f".join(parts[2:-1]) or "").strip()
        commit_ref = str(parts[-1] or "").strip()
        if not version_label:
            continue
        parsed = parse_release_portrait_fields(release_notes)
        parsed_skills = _skills_list(parsed.get("skills"))
        if not parsed_skills and _looks_like_system_release_note(release_notes):
            fallback_skills = _list_workspace_local_skills(workspace)
            if fallback_skills:
                parsed["skills"] = list(fallback_skills)
                parsed_skills = list(fallback_skills)
        release_valid, invalid_reasons = validate_release_portrait_fields(parsed)
        classification = "release" if release_valid else "normal_commit"
        fallback_summary = str(release_notes.splitlines()[0] if release_notes else "").strip()
        change_summary = _short_text(
            str(parsed.get("version_notes") or "").strip() or fallback_summary or version_label,
            240,
        )
        if not current_version:
            current_version = version_label
        if not last_release_at:
            last_release_at = released_at
        rows.append(
            {
                "version_label": version_label,
                "released_at": released_at,
                "change_summary": change_summary,
                "commit_ref": commit_ref,
                "capability_summary": str(parsed.get("capability_summary") or "").strip(),
                "knowledge_scope": str(parsed.get("knowledge_scope") or "").strip(),
                "skills_json": json.dumps(parsed_skills, ensure_ascii=False),
                "applicable_scenarios": str(parsed.get("applicable_scenarios") or "").strip(),
                "version_notes": str(parsed.get("version_notes") or "").strip(),
                "release_valid": 1 if release_valid else 0,
                "invalid_reasons_json": json.dumps(invalid_reasons, ensure_ascii=False),
                "classification": classification,
                "raw_notes": _short_text(release_notes, 4000),
            }
        )
    return current_version, last_release_at, rows


def choose_latest_release_version(release_rows: list[dict[str, str]]) -> str:
    rows = [
        row
        for row in release_rows
        if isinstance(row, dict)
        and str(row.get("classification") or "release").strip().lower() == "release"
    ]
    if not rows:
        return ""
    semver_ranked: list[tuple[tuple[int, int, int, str, str], str]] = []
    for row in rows:
        label = str(row.get("version_label") or "").strip()
        if not label:
            continue
        matched = re.fullmatch(r"[vV]?(\d+)\.(\d+)\.(\d+)", label)
        if not matched:
            continue
        semver_ranked.append(
            (
                (
                    int(matched.group(1)),
                    int(matched.group(2)),
                    int(matched.group(3)),
                    str(row.get("released_at") or ""),
                    label.lower(),
                ),
                label,
            )
        )
    if semver_ranked:
        semver_ranked.sort(key=lambda item: item[0], reverse=True)
        return semver_ranked[0][1]
    return str(rows[0].get("version_label") or "").strip()


def _short_text(value: str, max_len: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


_PORTRAIT_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "capability_summary": (
        "capability_summary",
        "capabilitysummary",
        "role_capability_summary",
        "角色能力摘要",
        "角色能力",
        "能力摘要",
        "能力",
    ),
    "knowledge_scope": (
        "knowledge_scope",
        "knowledgescope",
        "knowledge",
        "角色知识范围",
        "知识范围",
        "知识域",
        "知识",
    ),
    "skills": (
        "skills",
        "skill",
        "技能",
        "技能列表",
    ),
    "skill_profiles": (
        "skill_profiles",
        "skillprofiles",
        "skills_profile",
        "skills_profiles",
        "agent_skill_profiles",
        "agentskillsprofiles",
    ),
    "applicable_scenarios": (
        "applicable_scenarios",
        "applicablescenarios",
        "scenario",
        "scenarios",
        "适用场景",
        "场景",
    ),
    "version_notes": (
        "version_notes",
        "versionnotes",
        "release_notes",
        "releasenotes",
        "版本说明",
        "发布说明",
    ),
}

_PORTRAIT_FIELDS = tuple(_PORTRAIT_FIELD_ALIASES.keys())

_PORTRAIT_KEY_LOOKUP: dict[str, str] = {}
for _canonical_key, _aliases in _PORTRAIT_FIELD_ALIASES.items():
    for _alias in _aliases:
        _PORTRAIT_KEY_LOOKUP[re.sub(r"[\W_]+", "", str(_alias or "").strip().lower())] = _canonical_key
del _canonical_key, _aliases, _alias


def _normalize_portrait_key(raw: str) -> str:
    return re.sub(r"[\W_]+", "", str(raw or "").strip().lower())


_SKILL_PROFILE_NAME_ALIASES = {
    _normalize_portrait_key("name"),
    _normalize_portrait_key("skill"),
    _normalize_portrait_key("skill_name"),
    _normalize_portrait_key("title"),
    _normalize_portrait_key("label"),
    _normalize_portrait_key("技能"),
    _normalize_portrait_key("技能名"),
    _normalize_portrait_key("名称"),
}

_SKILL_PROFILE_SUMMARY_ALIASES = {
    _normalize_portrait_key("summary"),
    _normalize_portrait_key("intro"),
    _normalize_portrait_key("brief"),
    _normalize_portrait_key("description"),
    _normalize_portrait_key("简介"),
    _normalize_portrait_key("中文简介"),
    _normalize_portrait_key("简述"),
}

_SKILL_PROFILE_DETAILS_ALIASES = {
    _normalize_portrait_key("details"),
    _normalize_portrait_key("detail"),
    _normalize_portrait_key("full_description"),
    _normalize_portrait_key("full_details"),
    _normalize_portrait_key("详情"),
    _normalize_portrait_key("详情描述"),
    _normalize_portrait_key("详细描述"),
    _normalize_portrait_key("说明"),
}


def _is_placeholder_skill_name(raw: Any) -> bool:
    text = str(raw or "").strip()
    if not text:
        return True
    normalized = re.sub(r"[\s\[\]\(\)\{\}'\",]+", "", text).strip().lower()
    return not normalized or normalized in {"none", "null", "nil", "na", "n/a"}


def _skill_profile_text(value: Any, *, limit: int) -> str:
    return _short_text(str(value or "").strip(), limit)


def _skill_profile_field(payload: dict[str, Any], aliases: set[str], *, limit: int) -> str:
    for key, value in payload.items():
        if _normalize_portrait_key(str(key or "")) not in aliases:
            continue
        text = _skill_profile_text(value, limit=limit)
        if text:
            return text
    return ""


def _skill_profile_from_value(value: Any) -> dict[str, str] | None:
    if isinstance(value, dict):
        name = _skill_profile_field(value, _SKILL_PROFILE_NAME_ALIASES, limit=80)
        summary = _skill_profile_field(value, _SKILL_PROFILE_SUMMARY_ALIASES, limit=120)
        details = _skill_profile_field(value, _SKILL_PROFILE_DETAILS_ALIASES, limit=800)
        if not name and len(value) == 1:
            only_key, only_value = next(iter(value.items()))
            only_key_text = _skill_profile_text(only_key, limit=80)
            if isinstance(only_value, dict):
                nested = dict(only_value)
                if only_key_text and not _skill_profile_field(nested, _SKILL_PROFILE_NAME_ALIASES, limit=80):
                    nested["name"] = only_key_text
                return _skill_profile_from_value(nested)
            if only_key_text:
                name = only_key_text
                summary = _skill_profile_text(only_value, limit=120)
        if not name:
            return None
        if _is_placeholder_skill_name(name):
            return None
        return {
            "name": name,
            "summary": summary,
            "details": details,
        }
    text = str(value or "").strip()
    if not text:
        return None
    parts = [str(item or "").strip() for item in re.split(r"\s*[|｜]\s*", text, maxsplit=2)]
    if parts and parts[0] and not _is_placeholder_skill_name(parts[0]):
        return {
            "name": _short_text(parts[0], 80),
            "summary": _short_text(parts[1], 120) if len(parts) > 1 else "",
            "details": _short_text(parts[2], 800) if len(parts) > 2 else "",
        }
    return None


def _skill_profiles_list(value: Any) -> list[dict[str, str]]:
    items: list[Any]
    if isinstance(value, list):
        items = list(value)
    elif isinstance(value, dict):
        keys = {_normalize_portrait_key(str(key or "")) for key in value.keys()}
        profile_aliases = (
            _SKILL_PROFILE_NAME_ALIASES
            | _SKILL_PROFILE_SUMMARY_ALIASES
            | _SKILL_PROFILE_DETAILS_ALIASES
        )
        if keys & profile_aliases:
            items = [value]
        else:
            items = []
            for key, nested in value.items():
                key_text = _skill_profile_text(key, limit=80)
                if not key_text:
                    continue
                if isinstance(nested, dict):
                    merged = dict(nested)
                    if not _skill_profile_field(merged, _SKILL_PROFILE_NAME_ALIASES, limit=80):
                        merged["name"] = key_text
                    items.append(merged)
                else:
                    items.append({"name": key_text, "summary": nested})
    else:
        text = str(value or "").strip()
        if not text:
            return []
        items = [str(item or "").strip() for item in re.split(r"[\r\n,，、;；/]+", text)]

    profiles: list[dict[str, str]] = []
    seen: dict[str, int] = {}
    for item in items:
        profile = _skill_profile_from_value(item)
        if profile is None:
            continue
        normalized_name = _normalize_portrait_key(profile.get("name") or "")
        if not normalized_name:
            continue
        existing_index = seen.get(normalized_name)
        if existing_index is None:
            seen[normalized_name] = len(profiles)
            profiles.append(profile)
            continue
        existing = profiles[existing_index]
        if not existing.get("summary") and profile.get("summary"):
            existing["summary"] = profile["summary"]
        if not existing.get("details") and profile.get("details"):
            existing["details"] = profile["details"]
    return profiles


def _skills_list(value: Any) -> list[str]:
    def _is_empty_skill_name(raw: Any) -> bool:
        text = str(raw or "").strip()
        if not text:
            return True
        normalized = re.sub(r"[\s\[\]\(\)\{\}'\",]+", "", text).strip().lower()
        return not normalized or normalized in {"none", "null", "nil", "na", "n/a"}

    if isinstance(value, (list, tuple, set)):
        rows: list[str] = []
        seen: set[str] = set()
        for item in value:
            for name in _skills_list(item):
                normalized_name = re.sub(r"[\s\[\]\(\)\{\}'\",]+", "", str(name or "").strip().lower())
                if not normalized_name or normalized_name in seen:
                    continue
                seen.add(normalized_name)
                rows.append(str(name or "").strip())
        return rows

    if isinstance(value, str):
        text = str(value or "").strip()
        if not text:
            return []
        decoded = None
        if text[:1] in ('[', '{', '"', "'"):
            try:
                decoded = json.loads(text)
            except Exception:
                try:
                    decoded = ast.literal_eval(text)
                except Exception:
                    decoded = None
        if decoded is not None and decoded is not value and decoded != text:
            return _skills_list(decoded)
    profiles = _skill_profiles_list(value)
    if profiles:
        return [
            str(item.get("name") or "").strip()
            for item in profiles
            if str(item.get("name") or "").strip() and not _is_empty_skill_name(item.get("name"))
        ]
    text = str(value or "").strip()
    if not text:
        return []
    rows = [
        str(item or "").strip()
        for item in re.split(r"[\r\n,，、;；|/]+", text)
    ]
    return [item for item in rows if item and not _is_empty_skill_name(item)]
