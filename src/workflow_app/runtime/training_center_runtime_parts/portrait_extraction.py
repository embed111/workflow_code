

def _extract_json_object_candidates(raw_text: str) -> list[dict[str, Any]]:
    text = str(raw_text or "")
    candidates: list[dict[str, Any]] = []
    direct_text = text.strip()
    if direct_text.startswith("{") and direct_text.endswith("}"):
        try:
            payload = json.loads(direct_text)
            if isinstance(payload, dict):
                candidates.append(payload)
        except Exception:
            pass
    lines = text.splitlines()
    inside_json_fence = False
    block_lines: list[str] = []
    for line in lines:
        marker = str(line or "").strip().lower()
        if not inside_json_fence:
            if marker.startswith("```json"):
                inside_json_fence = True
                block_lines = []
            continue
        if marker.startswith("```"):
            block_text = "\n".join(block_lines).strip()
            if block_text:
                try:
                    payload = json.loads(block_text)
                    if isinstance(payload, dict):
                        candidates.append(payload)
                except Exception:
                    pass
            inside_json_fence = False
            block_lines = []
            continue
        block_lines.append(str(line or ""))
    return candidates


def _extract_portrait_fields_from_text(raw_text: str) -> dict[str, Any]:
    text = str(raw_text or "")
    parsed: dict[str, Any] = {key: "" for key in _PORTRAIT_FIELDS}
    parsed["skills"] = []
    parsed["skill_profiles"] = []

    json_candidates = _extract_json_object_candidates(text)
    for payload in json_candidates:
        for key, value in payload.items():
            canonical = _PORTRAIT_KEY_LOOKUP.get(_normalize_portrait_key(str(key or "")))
            if not canonical:
                continue
            if canonical == "skills":
                skill_profiles = _skill_profiles_list(value)
                if skill_profiles:
                    parsed["skill_profiles"] = skill_profiles
                skills = _skills_list(value)
                if skills:
                    parsed["skills"] = skills
            elif canonical == "skill_profiles":
                skill_profiles = _skill_profiles_list(value)
                if skill_profiles:
                    parsed["skill_profiles"] = skill_profiles
                    parsed["skills"] = [str(item.get("name") or "").strip() for item in skill_profiles]
            else:
                value_text = str(value or "").strip()
                if value_text:
                    parsed[canonical] = value_text

    for raw_line in text.splitlines():
        line = str(raw_line or "").strip()
        if not line:
            continue
        line = re.sub(r"^[\-\*\+\d\.\)\s]+", "", line).strip()
        line = re.sub(r"^\*\*(.+?)\*\*$", r"\1", line).strip()
        sep_idx = -1
        sep = ""
        for candidate in ("：", ":", "="):
            idx = line.find(candidate)
            if idx <= 0:
                continue
            if sep_idx < 0 or idx < sep_idx:
                sep_idx = idx
                sep = candidate
        if sep_idx <= 0 or not sep:
            continue
        key_text = line[:sep_idx].strip()
        value_text = line[sep_idx + 1 :].strip()
        canonical = _PORTRAIT_KEY_LOOKUP.get(_normalize_portrait_key(key_text))
        if not canonical or not value_text:
            continue
        if canonical == "skills":
            if parsed.get("skills"):
                continue
            skill_profiles = _skill_profiles_list(value_text)
            if skill_profiles:
                parsed["skill_profiles"] = skill_profiles
            skills = _skills_list(value_text)
            if skills:
                parsed["skills"] = skills
        elif canonical == "skill_profiles":
            if parsed.get("skill_profiles"):
                continue
            try:
                decoded = json.loads(value_text)
            except Exception:
                decoded = value_text
            skill_profiles = _skill_profiles_list(decoded)
            if skill_profiles:
                parsed["skill_profiles"] = skill_profiles
                parsed["skills"] = [str(item.get("name") or "").strip() for item in skill_profiles]
        elif not parsed.get(canonical):
            parsed[canonical] = value_text
    parsed["capability_summary"] = _short_text(str(parsed.get("capability_summary") or ""), 280)
    parsed["knowledge_scope"] = _short_text(str(parsed.get("knowledge_scope") or ""), 280)
    parsed["applicable_scenarios"] = _short_text(str(parsed.get("applicable_scenarios") or ""), 280)
    parsed["version_notes"] = _short_text(str(parsed.get("version_notes") or ""), 280)
    parsed["skills"] = [_short_text(str(item), 80) for item in _skills_list(parsed.get("skills"))][:12]
    parsed["skill_profiles"] = _skill_profiles_list(parsed.get("skill_profiles") or parsed.get("skills"))[:12]
    return parsed


def parse_release_portrait_fields(release_notes: str) -> dict[str, Any]:
    parsed = _extract_portrait_fields_from_text(release_notes)
    return {
        "capability_summary": str(parsed.get("capability_summary") or "").strip(),
        "knowledge_scope": str(parsed.get("knowledge_scope") or "").strip(),
        "skills": _skills_list(parsed.get("skills")),
        "skill_profiles": _skill_profiles_list(parsed.get("skill_profiles") or parsed.get("skills")),
        "applicable_scenarios": str(parsed.get("applicable_scenarios") or "").strip(),
        "version_notes": str(parsed.get("version_notes") or "").strip(),
    }


def validate_release_portrait_fields(payload: dict[str, Any]) -> tuple[bool, list[str]]:
    data = payload if isinstance(payload, dict) else {}
    checks = (
        ("capability_summary", str(data.get("capability_summary") or "").strip()),
        ("knowledge_scope", str(data.get("knowledge_scope") or "").strip()),
        ("skills", _skills_list(data.get("skills"))),
        ("applicable_scenarios", str(data.get("applicable_scenarios") or "").strip()),
        ("version_notes", str(data.get("version_notes") or "").strip()),
    )
    invalid: list[str] = []
    for key, value in checks:
        if key == "skills":
            if not value:
                invalid.append("missing_skills")
            continue
        if not value:
            invalid.append(f"missing_{key}")
    return (len(invalid) == 0, invalid)


def extract_agent_role_portrait(agents_md_path: Path) -> dict[str, Any]:
    path = agents_md_path.resolve(strict=False)
    if not path.exists() or not path.is_file():
        return {
            "capability_summary": "",
            "knowledge_scope": "",
            "skills": [],
            "skill_profiles": [],
            "applicable_scenarios": "",
            "version_notes": "",
        }
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return {
            "capability_summary": "",
            "knowledge_scope": "",
            "skills": [],
            "skill_profiles": [],
            "applicable_scenarios": "",
            "version_notes": "",
        }
    parsed = _extract_portrait_fields_from_text(raw)
    return {
        "capability_summary": str(parsed.get("capability_summary") or "").strip(),
        "knowledge_scope": str(parsed.get("knowledge_scope") or "").strip(),
        "skills": _skills_list(parsed.get("skills")),
        "skill_profiles": _skill_profiles_list(parsed.get("skill_profiles") or parsed.get("skills")),
        "applicable_scenarios": str(parsed.get("applicable_scenarios") or "").strip(),
        "version_notes": str(parsed.get("version_notes") or "").strip(),
    }


def extract_core_capability_summary(agents_md_path: Path) -> str:
    portrait = extract_agent_role_portrait(agents_md_path)
    chunks: list[str] = []
    capability_summary = str(portrait.get("capability_summary") or "").strip()
    knowledge_scope = str(portrait.get("knowledge_scope") or "").strip()
    skills = _skills_list(portrait.get("skills"))
    if capability_summary:
        chunks.append(f"能力:{_short_text(capability_summary, 80)}")
    if knowledge_scope:
        chunks.append(f"知识:{_short_text(knowledge_scope, 80)}")
    if skills:
        chunks.append("技能:" + " / ".join([_short_text(item, 24) for item in skills[:3]]))
    return " | ".join(chunks)


def append_training_center_audit(
    root: Path,
    *,
    action: str,
    operator: str,
    target_id: str,
    detail: dict[str, Any] | None = None,
) -> str:
    ts = now_local()
    audit_id = training_audit_id()
    payload = detail if isinstance(detail, dict) else {}
    conn = connect_db(root)
    try:
        conn.execute(
            """
            INSERT INTO training_audit_log (
                audit_id,action,operator,target_id,detail_json,created_at
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                audit_id,
                str(action or "").strip(),
                safe_token(str(operator or "web-user"), "web-user", 80),
                str(target_id or "").strip(),
                json.dumps(payload, ensure_ascii=False),
                iso_ts(ts),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    ref = relative_to_root(root, event_file(root))
    persist_event(
        root,
        {
            "event_id": event_id(),
            "timestamp": iso_ts(ts),
            "session_id": "sess-training-center",
            "actor": "workflow",
            "stage": "training_center",
            "action": str(action or "").strip() or "unknown",
            "status": "success",
            "latency_ms": 0,
            "task_id": str(target_id or "").strip(),
            "reason_tags": ["training_center_audit"],
            "ref": ref,
        },
    )
    return audit_id



# Training center domain logic is split into service modules.
from ..server.services import trainer_assignment_service as _trainer_assignment_service
from ..server.services import training_registry_service as _training_registry_service
from ..server.services import release_management_service as _release_management_service
from ..server.services import training_plan_service as _training_plan_service
from ..server.services import training_loop_service as _training_loop_service
from ..server.services import role_creation_service as _role_creation_service

_TRAINING_CENTER_MODULES = (
    _trainer_assignment_service,
    _training_registry_service,
    _release_management_service,
    _training_plan_service,
    _training_loop_service,
    _role_creation_service,
)

for _module in _TRAINING_CENTER_MODULES:
    _module.bind_runtime_symbols(globals())

for _module in _TRAINING_CENTER_MODULES:
    for _name, _value in _module.__dict__.items():
        if _name.startswith("__") or _name == "bind_runtime_symbols":
            continue
        globals()[_name] = _value

# Re-bind once after exports so cross-module function references are visible.
for _module in _TRAINING_CENTER_MODULES:
    _module.bind_runtime_symbols(globals())

del _module, _name, _value
