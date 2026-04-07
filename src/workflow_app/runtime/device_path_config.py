from __future__ import annotations

import csv
import io
import json
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any


DEVICE_PATH_CONFIGS_KEY = "device_path_configs"
DEVICE_PATH_KEYS = (
    "agent_search_root",
    "artifact_root",
    "task_artifact_root",
    "development_workspace_root",
    "agent_runtime_root",
)
DEVICE_ID_ENV_KEYS = ("WORKFLOW_DEVICE_ID", "WORKFLOW_DEVICE_IDS")

_HEX_ONLY_RE = re.compile(r"[^0-9A-Fa-f]+")
_LIST_SPLIT_RE = re.compile(r"[\s,;|]+")
_DEVICE_ID_CACHE: list[str] | None = None


def normalize_device_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    compact = _HEX_ONLY_RE.sub("", text)
    if len(compact) == 12:
        compact = compact.upper()
        return "-".join(compact[idx : idx + 2] for idx in range(0, 12, 2))
    return text.upper()


def _append_device_id(out: list[str], seen: set[str], raw: Any) -> None:
    token = normalize_device_id(raw)
    if not token or token in seen:
        return
    seen.add(token)
    out.append(token)


def _merge_device_ids(primary: list[str], secondary: list[str]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for raw in [*primary, *secondary]:
        _append_device_id(values, seen, raw)
    return values


def _detect_fast_device_ids() -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for env_name in DEVICE_ID_ENV_KEYS:
        raw = str(os.getenv(env_name) or "").strip()
        if not raw:
            continue
        for part in _LIST_SPLIT_RE.split(raw):
            _append_device_id(values, seen, part)
    try:
        node_value = int(uuid.getnode())
        if node_value >= 0:
            _append_device_id(values, seen, f"{node_value:012X}")
    except Exception:
        pass
    return values


def detect_current_device_ids(*, include_getmac: bool = True, force_refresh: bool = False) -> list[str]:
    fast_values = _detect_fast_device_ids()
    if not include_getmac or os.name != "nt":
        return list(fast_values)
    global _DEVICE_ID_CACHE
    if not force_refresh and _DEVICE_ID_CACHE is not None:
        return _merge_device_ids(fast_values, _DEVICE_ID_CACHE)
    slow_values: list[str] = []
    slow_seen: set[str] = set()
    try:
        proc = subprocess.run(
            ["getmac", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=1.5,
        )
        if proc.returncode == 0:
            reader = csv.reader(io.StringIO(str(proc.stdout or "")))
            for row in reader:
                if not row:
                    continue
                _append_device_id(slow_values, slow_seen, row[0])
    except Exception:
        pass
    _DEVICE_ID_CACHE = list(slow_values)
    return _merge_device_ids(fast_values, slow_values)


def load_runtime_config_payload(path: Path) -> Any:
    if not path.exists() or not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_runtime_config_payload(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _absolute_path_text(raw: Any, *, base: Path) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    candidate_text = os.path.expanduser(text)
    base_text = os.path.abspath(os.path.expanduser(str(base)))
    if not os.path.isabs(candidate_text):
        candidate_text = os.path.join(base_text, candidate_text)
    return Path(os.path.abspath(candidate_text)).as_posix()


def _path_text(path: Path) -> str:
    return Path(os.path.abspath(os.path.expanduser(str(path)))).as_posix()


def derive_runtime_path_fields(root: Path, values: dict[str, Any]) -> dict[str, str]:
    payload = values if isinstance(values, dict) else {}
    workspace_root_text = _absolute_path_text(payload.get("agent_search_root"), base=root)
    workspace_root = Path(workspace_root_text) if workspace_root_text else None

    artifact_seed = payload.get("task_artifact_root")
    if not str(artifact_seed or "").strip():
        artifact_seed = payload.get("artifact_root")
    artifact_base = workspace_root or root
    artifact_root_text = _absolute_path_text(artifact_seed, base=artifact_base)
    if not artifact_root_text and workspace_root is not None:
        artifact_root_text = _path_text(workspace_root / ".output")
    artifact_root = Path(artifact_root_text) if artifact_root_text else None

    development_workspace_root_text = _absolute_path_text(
        payload.get("development_workspace_root"),
        base=workspace_root or artifact_root or root,
    )
    if not development_workspace_root_text and workspace_root is not None:
        development_workspace_root_text = _path_text(workspace_root / "workflow" / ".repository")

    agent_runtime_root_text = _absolute_path_text(
        payload.get("agent_runtime_root"),
        base=artifact_root or workspace_root or root,
    )
    if not agent_runtime_root_text and artifact_root is not None:
        agent_runtime_root_text = _path_text(artifact_root / "agent-runtime")

    out: dict[str, str] = {}
    if workspace_root_text:
        out["agent_search_root"] = workspace_root_text
    if artifact_root_text:
        out["artifact_root"] = artifact_root_text
        out["task_artifact_root"] = artifact_root_text
    if development_workspace_root_text:
        out["development_workspace_root"] = development_workspace_root_text
    if agent_runtime_root_text:
        out["agent_runtime_root"] = agent_runtime_root_text
    return out


def _device_configs(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = payload.get(DEVICE_PATH_CONFIGS_KEY)
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        text = str(key or "").strip()
        if not text:
            continue
        out[text] = dict(value)
    return out


def match_device_config(
    payload: dict[str, Any],
    *,
    device_ids: list[str] | None = None,
) -> tuple[str, dict[str, Any], list[str]]:
    configs = _device_configs(payload if isinstance(payload, dict) else {})
    normalized: dict[str, tuple[str, dict[str, Any]]] = {}
    for raw_key, value in configs.items():
        key = normalize_device_id(raw_key)
        if not key:
            continue
        normalized[key] = (raw_key, value)
    candidates = [
        token
        for token in (device_ids if device_ids is not None else detect_current_device_ids(include_getmac=False))
        if token
    ]
    for candidate in candidates:
        matched = normalized.get(normalize_device_id(candidate))
        if matched:
            return matched[0], dict(matched[1]), candidates
    if not normalized or device_ids is not None:
        return "", {}, candidates
    full_candidates = [token for token in detect_current_device_ids() if token]
    if full_candidates != candidates:
        for candidate in full_candidates:
            matched = normalized.get(normalize_device_id(candidate))
            if matched:
                return matched[0], dict(matched[1]), full_candidates
        candidates = full_candidates
    return "", {}, candidates


def resolve_runtime_config(
    root: Path,
    payload: dict[str, Any],
    *,
    device_ids: list[str] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw = dict(payload or {}) if isinstance(payload, dict) else {}
    matched_key, matched_entry, candidates = match_device_config(raw, device_ids=device_ids)
    effective = dict(raw)
    derived_from: dict[str, Any]
    if matched_entry:
        effective.update(matched_entry)
        derived_from = matched_entry
    else:
        derived_from = effective
    derived_fields = derive_runtime_path_fields(root, derived_from)
    for key, value in derived_fields.items():
        if matched_entry:
            if str(matched_entry.get(key) or "").strip():
                continue
            effective[key] = value
            continue
        if not str(effective.get(key) or "").strip():
            effective[key] = value
    if isinstance(meta, dict):
        meta.clear()
        meta.update(
            {
                "device_ids": list(candidates),
                "matched_device_id": matched_key,
                "matched": bool(matched_key),
            }
        )
    return effective


def _split_patch_fields(patch: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    path_patch = {key: value for key, value in (patch or {}).items() if key in DEVICE_PATH_KEYS}
    if "artifact_root" in path_patch and "task_artifact_root" not in path_patch:
        path_patch["task_artifact_root"] = path_patch["artifact_root"]
    if "task_artifact_root" in path_patch and "artifact_root" not in path_patch:
        path_patch["artifact_root"] = path_patch["task_artifact_root"]
    other_patch = {key: value for key, value in (patch or {}).items() if key not in DEVICE_PATH_KEYS}
    return path_patch, other_patch


def _recompute_runtime_path_source(
    entry: dict[str, Any],
    path_patch: dict[str, Any],
) -> dict[str, Any]:
    source = dict(entry or {})
    if "agent_search_root" in path_patch:
        for key in (
            "artifact_root",
            "task_artifact_root",
            "development_workspace_root",
            "agent_runtime_root",
        ):
            if key not in path_patch:
                source.pop(key, None)
        return source
    if "artifact_root" in path_patch or "task_artifact_root" in path_patch:
        if "agent_runtime_root" not in path_patch:
            source.pop("agent_runtime_root", None)
    return source


def apply_runtime_config_patch(
    root: Path,
    payload: dict[str, Any],
    patch: dict[str, Any],
    *,
    device_ids: list[str] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw = dict(payload or {}) if isinstance(payload, dict) else {}
    path_patch, other_patch = _split_patch_fields(patch or {})
    raw.update(other_patch)
    existing_device_configs = _device_configs(raw)
    allow_device_slot_write = bool(existing_device_configs)
    matched_key, matched_entry, candidates = match_device_config(raw, device_ids=device_ids)
    target_device_key = matched_key or (candidates[0] if allow_device_slot_write and candidates else "")
    if path_patch:
        if target_device_key:
            device_configs = dict(existing_device_configs)
            entry = dict(matched_entry)
            entry.update(path_patch)
            recompute_source = _recompute_runtime_path_source(entry, path_patch)
            derived_entry = derive_runtime_path_fields(root, recompute_source)
            for key, value in derived_entry.items():
                if key in path_patch:
                    continue
                entry[key] = value
            device_configs[target_device_key] = entry
            raw[DEVICE_PATH_CONFIGS_KEY] = device_configs
        else:
            raw.update(path_patch)
    if isinstance(meta, dict):
        meta.clear()
        meta.update(
            {
                "device_ids": list(candidates),
                "target_device_id": target_device_key,
                "wrote_device_entry": bool(allow_device_slot_write and target_device_key and path_patch),
            }
        )
    return raw
