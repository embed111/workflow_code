def _append_message(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    role: str,
    content: str,
    attachments: list[dict[str, Any]] | None = None,
    message_type: str = "chat",
    meta: dict[str, Any] | None = None,
    created_at: str = "",
) -> dict[str, Any]:
    ts = created_at or _tc_now_text()
    payload = {
        "message_id": _role_creation_message_id(),
        "session_id": session_id,
        "role": str(role or "assistant").strip().lower() or "assistant",
        "content": str(content or ""),
        "attachments": list(attachments or []),
        "message_type": _normalize_message_type(message_type),
        "meta": dict(meta or {}),
        "created_at": ts,
    }
    conn.execute(
        """
        INSERT INTO role_creation_messages (
            message_id,session_id,role,content,attachments_json,message_type,meta_json,created_at
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            payload["message_id"],
            session_id,
            payload["role"],
            payload["content"],
            _json_dumps(payload["attachments"]),
            payload["message_type"],
            _json_dumps(payload["meta"]),
            payload["created_at"],
        ),
    )
    preview = _message_preview(payload["content"], payload["attachments"])
    conn.execute(
        """
        UPDATE role_creation_sessions
        SET last_message_preview=?,last_message_at=?,updated_at=?
        WHERE session_id=?
        """,
        (preview, payload["created_at"], payload["created_at"], session_id),
    )
    return payload


def _session_messages_texts(messages: list[dict[str, Any]], *, role: str) -> list[str]:
    return [
        str(item.get("content") or "")
        for item in messages
        if str(item.get("role") or "").strip().lower() == role and str(item.get("content") or "").strip()
    ]


def _extract_labeled_values(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {
        "role_name": [],
        "role_goal": [],
        "core_capabilities": [],
        "boundaries": [],
        "applicable_scenarios": [],
        "collaboration_style": [],
    }
    for segment in _role_creation_labeled_segments(text):
        field_key = str(segment.get("field_key") or "").strip()
        if field_key not in out:
            continue
        value_text = _normalize_text(segment.get("value"), max_len=400)
        if value_text:
            out[field_key].append(value_text)
    return out


def _extract_natural_language_values(text: str) -> dict[str, list[str]]:
    sentence_prefix = r"(?:^|[。\n！？!?；;])\s*"
    patterns = {
        "role_name": (
            sentence_prefix + r"(?:角色名|角色名称|名字)\s*(?:是|叫|为|[:：=])\s*([^\n，,。.!！？；;]{2,40})",
            sentence_prefix + r"(?:让它叫|就叫)\s*([^\n，,。.!！？；;]{2,40})",
        ),
        "role_goal": (
            sentence_prefix + r"(?:角色目标|目标|职责)\s*(?:是|为|[:：=])\s*([^\n。！？!?]{2,280})",
        ),
        "core_capabilities": (
            sentence_prefix + r"(?:核心能力|能力|擅长)\s*(?:有|是|为|包括|包含|[:：=])\s*([^\n。！？!?]{2,400})",
        ),
        "boundaries": (
            sentence_prefix + r"(?:边界|约束)\s*(?:是|为|[:：=])\s*([^\n。！？!?]{2,280})",
            sentence_prefix + r"((?:不要|不能|禁止|避免|别)[^\n。！？!?]{1,280})",
        ),
        "applicable_scenarios": (
            sentence_prefix + r"(?:适用场景|场景|适用)\s*(?:是|为|[:：=])\s*([^\n。！？!?]{2,280})",
        ),
        "collaboration_style": (
            sentence_prefix + r"(?:协作方式|输出风格|协作|风格)\s*(?:是|为|[:：=])\s*([^\n。！？!?]{2,280})",
        ),
    }
    out: dict[str, list[str]] = {key: [] for key in patterns}
    for field, field_patterns in patterns.items():
        for pattern in field_patterns:
            for match in re.finditer(pattern, str(text or ""), flags=re.IGNORECASE):
                candidate = _normalize_text(match.group(1), max_len=400)
                if candidate:
                    out[field].append(candidate)
    return out


def _normalize_role_name_candidate(text: str) -> str:
    candidate = _normalize_text(text, max_len=40).strip().strip("`'\"“”‘’[]()（）{}")
    if not candidate:
        return ""
    lowered = candidate.lower()
    invalid_exact = {
        "agent",
        "assistant",
        "role",
        "一个",
        "一个agent",
        "一位",
        "一位agent",
        "角色",
        "助手",
        "草稿",
        "当前不构成缺陷",
        "不构成缺陷",
    }
    if lowered in invalid_exact or candidate in invalid_exact:
        return ""
    if re.fullmatch(r"(?:一个|一位|这个|那个|该)(?:agent|助手|角色)?", candidate, flags=re.IGNORECASE):
        return ""
    if re.fullmatch(r"(?:当前)?(?:不构成)?缺陷", candidate, flags=re.IGNORECASE):
        return ""
    return candidate


def _guess_role_name(texts: list[str]) -> str:
    patterns = (
        re.compile(r"(?:创建|做|想要|需要)(?:一个|一位|个)?([^\n，,。.!！？]{2,32}?)(?:角色|助手|agent)", re.IGNORECASE),
        re.compile(r"(?:角色名|角色名称|名字)\s*(?:是|叫|为|[:：=])\s*([^\n，,。.!！？]{2,32})", re.IGNORECASE),
        re.compile(r"(?:让它叫|就叫)\s*([^\n，,。.!！？]{2,32})", re.IGNORECASE),
    )
    for text in texts:
        for pattern in patterns:
            match = pattern.search(text)
            if not match:
                continue
            candidate = _normalize_role_name_candidate(match.group(1))
            if candidate:
                return candidate
    return ""


def _guess_role_name_from_assistant_suggestions(texts: list[str]) -> str:
    cue_words = ("角色名", "名字", "命名", "收口", "建议", "先用", "叫", "英文名")
    patterns = (
        re.compile(r"`([^`\n]{2,40})`"),
        re.compile(r"「([^」\n]{2,40})」"),
        re.compile(r"“([^”\n]{2,40})”"),
    )
    for text in reversed(list(texts or [])):
        content = str(text or "")
        for pattern in patterns:
            for match in pattern.finditer(content):
                context = content[max(0, match.start() - 24) : min(len(content), match.end() + 24)]
                if not any(cue in context for cue in cue_words):
                    continue
                candidate = _normalize_role_name_candidate(match.group(1))
                if candidate:
                    return candidate
    return ""


def _collect_sentence_items(texts: list[str], keywords: tuple[str, ...], *, limit: int = 8) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for part in re.split(r"[。\n！？!?]", str(text or "")):
            sentence = _normalize_text(part, max_len=240)
            if not sentence:
                continue
            if not any(keyword in sentence for keyword in keywords):
                continue
            key = sentence.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(sentence)
            if len(out) >= limit:
                return out
    return out


def _role_creation_source_ref(message: dict[str, Any]) -> dict[str, str]:
    item = message if isinstance(message, dict) else {}
    return {
        "message_id": str(item.get("message_id") or "").strip(),
        "created_at": str(item.get("created_at") or "").strip(),
        "content_preview": _message_preview(item.get("content"), list(item.get("attachments") or [])),
    }


def _role_creation_user_chat_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in list(messages or [])
        if str(item.get("role") or "").strip().lower() == "user"
        and _normalize_message_type(item.get("message_type")) == "chat"
    ]


def _role_creation_text_fragments(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fragments: list[dict[str, Any]] = []
    for message in _role_creation_user_chat_messages(messages):
        content = _normalize_text(message.get("content"), max_len=4000)
        if not content:
            continue
        fragments.append(
            {
                "text": content,
                "source": _role_creation_source_ref(message),
            }
        )
    return fragments


_ROLE_CREATION_STRUCTURED_LABELS = {
    "role_name": ("角色名称", "角色名", "名字"),
    "role_goal": ("角色目标", "目标", "职责"),
    "core_capabilities": ("核心能力", "能力"),
    "boundaries": ("边界", "约束"),
    "applicable_scenarios": ("适用场景", "适用", "场景"),
    "collaboration_style": ("协作方式", "输出风格", "协作", "风格"),
    "capability_modules": ("能力模块", "能力包", "模块拆分"),
    "default_delivery_policy": ("默认交付策略", "默认交付", "交付策略", "默认输出", "默认交付粒度", "交付粒度"),
    "format_strategy": ("格式边界", "格式策略", "输出格式"),
    "knowledge_assets": ("知识沉淀", "知识资产", "知识文件", "沉淀资产"),
    "seed_tasks": ("首批任务", "首批能力", "首批工作集"),
    "priority_order": ("首批优先顺序", "首批优先级", "优先顺序", "优先级"),
}


def _role_creation_labeled_segments(text: str) -> list[dict[str, str]]:
    content = _normalize_text(text, max_len=4000)
    if not content:
        return []
    alias_pairs: list[tuple[str, str]] = []
    alias_to_field: dict[str, str] = {}
    for field_key, labels in _ROLE_CREATION_STRUCTURED_LABELS.items():
        for label in labels:
            label_text = str(label or "").strip()
            if not label_text:
                continue
            alias_pairs.append((label_text, field_key))
            alias_to_field[label_text.lower()] = field_key
    alias_pairs.sort(key=lambda item: len(item[0]), reverse=True)
    alias_pattern = "|".join(re.escape(label) for label, _field_key in alias_pairs)
    if not alias_pattern:
        return []
    matcher = re.compile(
        r"(?P<label>" + alias_pattern + r")\s*(?:是|为|有|叫|包括|包含|[:：=])\s*",
        flags=re.IGNORECASE,
    )
    matches = list(matcher.finditer(content))
    segments: list[dict[str, str]] = []
    for index, match in enumerate(matches):
        label_text = str(match.group("label") or "").strip()
        field_key = alias_to_field.get(label_text.lower(), "")
        if not field_key:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        raw_value = content[start:end]
        if index + 1 >= len(matches):
            raw_value = re.split(r"[。\n！？!?]", raw_value, maxsplit=1)[0]
        value = _normalize_text(raw_value, max_len=400).strip(" ，,；;。")
        if not value:
            continue
        segments.append(
            {
                "field_key": field_key,
                "label": label_text,
                "value": value,
            }
        )
    return segments


def _role_creation_labeled_entries(
    fragments: list[dict[str, Any]],
    field_keys: tuple[str, ...],
    *,
    limit: int = 12,
    max_len: int = 240,
) -> list[dict[str, Any]]:
    expected = {str(item or "").strip() for item in list(field_keys or []) if str(item or "").strip()}
    rows: list[dict[str, Any]] = []
    for fragment in list(fragments or []):
        source = fragment.get("source") if isinstance(fragment.get("source"), dict) else {}
        for segment in _role_creation_labeled_segments(str(fragment.get("text") or "")):
            if str(segment.get("field_key") or "").strip() not in expected:
                continue
            rows.append(
                {
                    "text": _normalize_text(segment.get("value"), max_len=max_len),
                    "source": source,
                }
            )
    return _role_creation_unique_texts(rows, limit=limit, max_len=max_len)


def _role_creation_entry_source(entry: dict[str, Any]) -> dict[str, str]:
    message_ids = [str(item).strip() for item in list(entry.get("source_message_ids") or []) if str(item).strip()]
    return {
        "message_id": message_ids[0] if message_ids else "",
        "created_at": str(entry.get("last_updated_at") or "").strip(),
        "content_preview": str(entry.get("source_preview") or "").strip(),
    }


def _role_creation_split_named_items(value: Any, *, limit: int = 12, split_slash: bool = False) -> list[str]:
    text = str(value or "")
    if split_slash:
        text = re.sub(r"\s*/\s*", "，", text)
    return _split_items(text, limit=limit)


def _role_creation_is_knowledge_asset_candidate(text: str) -> bool:
    candidate = _normalize_text(text, max_len=160)
    if not candidate:
        return False
    if any(token in candidate for token in ("默认交付", "交付策略", "格式边界", "优先顺序", "首批任务", "角色名")):
        return False
    return any(token in candidate for token in ("方法", "技法", "模板", "示例", "反例", "验收", "清单", "文档"))


def _role_creation_unique_texts(entries: list[dict[str, Any]], *, limit: int = 12, max_len: int = 240) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in list(entries or []):
        text = _normalize_text((entry or {}).get("text"), max_len=max_len)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        source = (entry or {}).get("source") if isinstance((entry or {}).get("source"), dict) else {}
        out.append(
            {
                "text": text,
                "source_message_ids": [str(source.get("message_id") or "").strip()] if str(source.get("message_id") or "").strip() else [],
                "last_updated_at": str(source.get("created_at") or "").strip(),
                "source_preview": str(source.get("content_preview") or "").strip(),
            }
        )
        if len(out) >= max(1, int(limit)):
            break
    return out


def _role_creation_candidate_name(raw: Any) -> str:
    text = _normalize_text(raw, max_len=120)
    if not text:
        return ""
    text = re.sub(
        r"^(?:能力模块|能力包|模块拆分|模块|能力|默认交付策略|默认交付|交付策略|格式边界|格式策略|知识沉淀|知识资产|首批任务|首批能力|优先顺序|优先级)\s*(?:包括|为|是|[:：=])?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"^(?:要覆盖|覆盖|需要覆盖|先补|先做|首批|默认)\s*", "", text)
    text = text.strip().strip("，,。；;：:()（）[]【】")
    if len(text) < 2:
        return ""
    stop_words = {
        "能力包",
        "能力模块",
        "模块",
        "交付策略",
        "格式边界",
        "知识沉淀",
        "知识资产",
        "首批任务",
        "首批能力",
        "优先顺序",
    }
    if text in stop_words:
        return ""
    return text


def _role_creation_sentence_entries(fragments: list[dict[str, Any]], keywords: tuple[str, ...], *, limit: int = 12) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for fragment in list(fragments or []):
        source = fragment.get("source") if isinstance(fragment.get("source"), dict) else {}
        for part in re.split(r"[。\n！？!?；;]", str(fragment.get("text") or "")):
            sentence = _normalize_text(part, max_len=240)
            if not sentence:
                continue
            if not any(keyword in sentence for keyword in keywords):
                continue
            rows.append({"text": sentence, "source": source})
            if len(rows) >= max(1, int(limit)):
                return _role_creation_unique_texts(rows, limit=limit)
    return _role_creation_unique_texts(rows, limit=limit)


def _role_creation_pick_latest_source(entries: list[dict[str, Any]]) -> dict[str, Any]:
    latest_entry: dict[str, Any] = {}
    latest_key = ""
    message_ids: list[str] = []
    for entry in list(entries or []):
        current_key = str(entry.get("last_updated_at") or "").strip() or str(entry.get("source_preview") or "").strip()
        if current_key >= latest_key:
            latest_key = current_key
            latest_entry = dict(entry)
        for message_id in list(entry.get("source_message_ids") or []):
            text = str(message_id or "").strip()
            if text and text not in message_ids:
                message_ids.append(text)
    return {
        "source_message_ids": message_ids,
        "last_updated_at": str(latest_entry.get("last_updated_at") or "").strip(),
        "source_preview": str(latest_entry.get("source_preview") or "").strip(),
    }


def _role_creation_confirmation_status(*, item_count: int = 0, required_count: int = 1, pending_items: list[str] | None = None) -> str:
    pending = [str(item).strip() for item in list(pending_items or []) if str(item).strip()]
    if item_count <= 0:
        return "missing"
    if pending:
        return "partial"
    if item_count >= max(1, int(required_count)):
        return "ready"
    return "partial"


def _role_creation_field_status(value: Any) -> str:
    if isinstance(value, list):
        return "confirmed" if any(_normalize_text(item, max_len=200) for item in value) else "missing"
    return "confirmed" if _normalize_text(value, max_len=280) else "missing"


def _role_creation_role_profile_spec(
    role_name: str,
    role_goal: str,
    core_capabilities: list[str],
    boundaries: list[str],
    applicable_scenarios: list[str],
    collaboration_style: str,
    attachments: list[dict[str, Any]],
    fragments: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    missing_fields: list[str] = []
    fields = {
        "role_name": role_name,
        "role_goal": role_goal,
        "core_capabilities": core_capabilities,
        "boundaries": boundaries,
        "applicable_scenarios": applicable_scenarios,
        "collaboration_style": collaboration_style,
        "example_assets": attachments[:6],
    }
    field_labels = {
        "role_name": "角色名",
        "role_goal": "角色目标",
        "core_capabilities": "核心能力",
        "boundaries": "边界",
        "applicable_scenarios": "适用场景",
        "collaboration_style": "协作方式",
    }
    field_statuses = {}
    for field_key, field_value in fields.items():
        if field_key == "example_assets":
            continue
        status = _role_creation_field_status(field_value)
        field_statuses[field_key] = status
        if status != "confirmed":
            missing_fields.append(field_key)
    source = _role_creation_pick_latest_source(
        _role_creation_unique_texts(
            [{"text": str(fragment.get("text") or ""), "source": fragment.get("source")} for fragment in list(fragments or [])],
            limit=8,
            max_len=240,
        )
    )
    pending_items = [field_labels.get(field_key, field_key) for field_key in missing_fields]
    layer = {
        "layer_key": "role_profile_spec",
        "layer_label": "角色画像",
        "confirmation_status": _role_creation_confirmation_status(
            item_count=sum(1 for field_key in field_statuses if field_statuses[field_key] == "confirmed"),
            required_count=6,
            pending_items=pending_items,
        ),
        "current_value": {
            "role_name": role_name,
            "role_goal": role_goal,
            "core_capabilities": list(core_capabilities or []),
            "boundaries": list(boundaries or []),
            "applicable_scenarios": list(applicable_scenarios or []),
            "collaboration_style": collaboration_style,
            "example_assets": attachments[:6],
        },
        "field_statuses": field_statuses,
        "pending_items": pending_items,
        "current_value_count": sum(1 for field_key in field_statuses if field_statuses[field_key] == "confirmed"),
        **source,
    }
    return layer, missing_fields


def _role_creation_module_outputs(module_name: str) -> list[str]:
    text = str(module_name or "")
    if "判断" in text:
        return ["判断结果", "选型说明"]
    if "抽取" in text or "拆解" in text:
        return ["结构化拆解清单", "关键信息提纲"]
    if "模板" in text or "示例" in text or "反例" in text:
        return ["模板草案", "示例清单"]
    if "验收" in text or "检查" in text:
        return ["验收清单", "通过/阻塞规则"]
    if "技法" in text or "SVG" in text or "Mermaid" in text or "PlantUML" in text:
        return ["格式规则", "交付示例"]
    return ["结构化产物", "执行说明"]


def _role_creation_module_dependencies(module_name: str) -> list[str]:
    text = str(module_name or "")
    if "图" in text or "SVG" in text or "Mermaid" in text or "PlantUML" in text:
        return ["场景约束", "输入材料"]
    if "验收" in text or "检查" in text:
        return ["交付结果", "验收标准"]
    return ["角色目标", "边界约束"]


def _role_creation_capability_modules(
    role_spec: dict[str, Any],
    fragments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in _role_creation_labeled_entries(
        fragments,
        ("capability_modules",),
        limit=6,
        max_len=280,
    ):
        source = _role_creation_entry_source(entry)
        for item in _role_creation_split_named_items(entry.get("text"), limit=8, split_slash=True):
            candidate = _role_creation_candidate_name(item)
            if not candidate:
                continue
            rows.append({"text": candidate, "source": source})
    if not rows:
        for capability in list(role_spec.get("core_capabilities") or []):
            candidate = _role_creation_candidate_name(capability)
            if candidate:
                rows.append({"text": candidate, "source": {}})
    unique_rows = _role_creation_unique_texts(rows, limit=8, max_len=80)
    modules: list[dict[str, Any]] = []
    for index, item in enumerate(unique_rows, start=1):
        module_name = str(item.get("text") or "").strip()
        if not module_name:
            continue
        modules.append(
            {
                "module_id": safe_token(module_name, f"module-{index}", 80) or f"module-{index}",
                "module_name": module_name,
                "module_goal": f"围绕“{module_name}”形成可复用的方法、步骤和交付规则。",
                "module_outputs": _role_creation_module_outputs(module_name),
                "dependencies": _role_creation_module_dependencies(module_name),
                "confirmation_status": "ready",
                "source_message_ids": list(item.get("source_message_ids") or []),
                "last_updated_at": str(item.get("last_updated_at") or "").strip(),
                "source_preview": str(item.get("source_preview") or "").strip(),
            }
        )
    return modules


def _role_creation_summary_from_entries(entries: list[dict[str, Any]], *, limit: int = 2, max_len: int = 280) -> str:
    lines = [str(item.get("text") or "").strip() for item in list(entries or []) if str(item.get("text") or "").strip()]
    if not lines:
        return ""
    return "；".join(lines[: max(1, int(limit))])[:max_len]


def _role_creation_format_strategy(fragments: list[dict[str, Any]]) -> dict[str, Any]:
    format_tokens = ("SVG", "Mermaid", "PlantUML", "Markdown", "HTML", "JSON", "YAML")
    preferred: list[str] = []
    allowed: list[str] = []
    avoided: list[str] = []
    rows: list[dict[str, Any]] = []
    explicit_rows = _role_creation_labeled_entries(
        fragments,
        ("format_strategy",),
        limit=4,
        max_len=240,
    )
    if explicit_rows:
        for entry in explicit_rows:
            rows.append(
                {
                    "text": _normalize_text(entry.get("text"), max_len=240),
                    "source": _role_creation_entry_source(entry),
                }
            )
    for fragment in list(fragments or []):
        text = str(fragment.get("text") or "")
        source = fragment.get("source") if isinstance(fragment.get("source"), dict) else {}
        if explicit_rows:
            break
        if not any(token.lower() in text.lower() for token in format_tokens):
            continue
        rows.append({"text": _normalize_text(text, max_len=240), "source": source})
    unique_rows = _role_creation_unique_texts(rows, limit=4, max_len=240)
    for item in unique_rows:
        text = str(item.get("text") or "")
        for token in format_tokens:
            if token.lower() not in text.lower():
                continue
            if re.search(re.escape(token) + r"\s*(?:为主|优先|默认)", text, flags=re.IGNORECASE):
                if token not in preferred:
                    preferred.append(token)
            if re.search(r"(?:不输出|不要|避免|禁止|禁用).{0,12}" + re.escape(token), text, flags=re.IGNORECASE):
                if token not in avoided:
                    avoided.append(token)
                    continue
            if token not in allowed:
                allowed.append(token)
    allowed = [token for token in allowed if token not in avoided]
    preferred = [token for token in preferred if token in allowed]
    source = _role_creation_pick_latest_source(unique_rows)
    summary = _role_creation_summary_from_entries(unique_rows, limit=2, max_len=280)
    pending_items: list[str] = []
    if not summary and not allowed:
        pending_items.append("补充格式边界")
    return {
        "preferred_formats": preferred,
        "allowed_formats": allowed,
        "avoided_formats": avoided,
        "summary": summary,
        "confirmation_status": _role_creation_confirmation_status(
            item_count=len(allowed) or (1 if summary else 0),
            required_count=1,
            pending_items=pending_items,
        ),
        "pending_items": pending_items,
        **source,
    }


def _role_creation_default_delivery_policy(fragments: list[dict[str, Any]], collaboration_style: str) -> dict[str, Any]:
    rows = _role_creation_labeled_entries(
        fragments,
        ("default_delivery_policy",),
        limit=4,
        max_len=240,
    )
    if not rows:
        rows = _role_creation_sentence_entries(
            fragments,
            ("默认交付", "交付策略", "交付粒度", "默认输出", "先给", "先出", "回传", "输出格式"),
            limit=4,
        )
    if not rows and collaboration_style and any(token in collaboration_style for token in ("输出", "交付", "回传")):
        rows = [
            {
                "text": _normalize_text(collaboration_style, max_len=240),
                "source_message_ids": [],
                "last_updated_at": "",
                "source_preview": "",
            }
        ]
    source = _role_creation_pick_latest_source(rows)
    summary = _role_creation_summary_from_entries(rows, limit=2, max_len=280)
    pending_items: list[str] = []
    if not summary:
        pending_items.append("补充默认交付策略")
    return {
        "summary": summary,
        "delivery_mode": "structured_bundle" if summary else "",
        "confirmation_status": _role_creation_confirmation_status(
            item_count=1 if summary else 0,
            required_count=1,
            pending_items=pending_items,
        ),
        "pending_items": pending_items,
        **source,
    }


def _role_creation_decision_rules(fragments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = _role_creation_sentence_entries(
        fragments,
        ("优先", "先", "如果", "当", "根据", "遇到", "需要"),
        limit=6,
    )
    out: list[dict[str, Any]] = []
    for index, item in enumerate(rows, start=1):
        text = str(item.get("text") or "").strip()
        if len(text) < 6:
            continue
        out.append(
            {
                "rule_id": safe_token(text, f"rule-{index}", 80) or f"rule-{index}",
                "rule_text": text,
                "source_message_ids": list(item.get("source_message_ids") or []),
                "last_updated_at": str(item.get("last_updated_at") or "").strip(),
                "source_preview": str(item.get("source_preview") or "").strip(),
            }
        )
    return out[:5]


def _role_creation_priority_scenarios(role_spec: dict[str, Any], fragments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = _role_creation_labeled_entries(
        fragments,
        ("priority_order", "applicable_scenarios"),
        limit=5,
        max_len=240,
    )
    if not rows:
        rows = _role_creation_unique_texts(
            [{"text": item, "source": {}} for item in list(role_spec.get("applicable_scenarios") or [])],
            limit=4,
            max_len=120,
        )
    out: list[dict[str, Any]] = []
    for index, item in enumerate(rows, start=1):
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        out.append(
            {
                "scenario_id": safe_token(text, f"scenario-{index}", 80) or f"scenario-{index}",
                "scenario_text": text,
                "priority": "P0" if index == 1 else "P1",
                "source_message_ids": list(item.get("source_message_ids") or []),
                "last_updated_at": str(item.get("last_updated_at") or "").strip(),
                "source_preview": str(item.get("source_preview") or "").strip(),
            }
        )
    return out[:4]


def _role_creation_capability_package_spec(role_spec: dict[str, Any], fragments: list[dict[str, Any]]) -> dict[str, Any]:
    modules = _role_creation_capability_modules(role_spec, fragments)
    decision_rules = _role_creation_decision_rules(fragments)
    default_delivery_policy = _role_creation_default_delivery_policy(fragments, str(role_spec.get("collaboration_style") or ""))
    format_strategy = _role_creation_format_strategy(fragments)
    priority_scenarios = _role_creation_priority_scenarios(role_spec, fragments)
    pending_items: list[str] = []
    if not modules:
        pending_items.append("至少补 1 个能力模块")
    if not default_delivery_policy.get("summary"):
        pending_items.append("补充默认交付策略")
    if not format_strategy.get("summary") and not list(format_strategy.get("allowed_formats") or []):
        pending_items.append("补充格式边界")
    if not priority_scenarios:
        pending_items.append("补充首批优先场景或顺序")
    source = _role_creation_pick_latest_source(
        modules
        + decision_rules
        + [default_delivery_policy, format_strategy]
        + priority_scenarios
    )
    return {
        "layer_key": "capability_package_spec",
        "layer_label": "能力包",
        "confirmation_status": _role_creation_confirmation_status(
            item_count=len(modules) + (1 if default_delivery_policy.get("summary") else 0) + (1 if format_strategy.get("summary") or list(format_strategy.get("allowed_formats") or []) else 0),
            required_count=3,
            pending_items=pending_items,
        ),
        "capability_modules": modules,
        "decision_rules": decision_rules,
        "default_delivery_policy": default_delivery_policy,
        "format_strategy": format_strategy,
        "priority_scenarios": priority_scenarios,
        "pending_items": pending_items,
        **source,
    }


def _role_creation_asset_path(asset_type: str, topic: str, index: int) -> str:
    slug = safe_token(topic, f"asset-{index}", 80).replace("_", "-").strip("-") or f"asset-{index}"
    mapping = {
        "方法说明": f"knowledge/methods/{slug}.md",
        "技法说明": f"knowledge/techniques/{slug}.md",
        "模板": f"knowledge/templates/{slug}.md",
        "最小示例": f"knowledge/examples/minimal-{slug}.md",
        "中等复杂度示例": f"knowledge/examples/medium-{slug}.md",
        "反例 / 失败示例": f"knowledge/anti-patterns/{slug}.md",
        "验收清单": f"knowledge/checklists/{slug}.md",
    }
    return mapping.get(asset_type, f"knowledge/assets/{slug}.md")


def _role_creation_asset_type_from_text(text: str) -> str:
    lowered = str(text or "").lower()
    if "反例" in text or "失败示例" in text:
        return "反例 / 失败示例"
    if "验收" in text or "检查清单" in text or "checklist" in lowered:
        return "验收清单"
    if "中等" in text or "复杂" in text:
        return "中等复杂度示例"
    if "示例" in text or "例子" in text or "样例" in text:
        return "最小示例"
    if "模板" in text:
        return "模板"
    if "技法" in text or "svg" in lowered or "mermaid" in lowered or "plantuml" in lowered:
        return "技法说明"
    return "方法说明"


def _role_creation_asset_priority(index: int, text: str) -> str:
    if index == 1 or any(token in str(text or "") for token in ("首批", "优先", "先做")):
        return "P0"
    if index <= 3:
        return "P1"
    return "P2"


def _role_creation_knowledge_asset_plan(
    capability_package_spec: dict[str, Any],
    fragments: list[dict[str, Any]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    explicit_entries = _role_creation_labeled_entries(
        fragments,
        ("knowledge_assets",),
        limit=6,
        max_len=280,
    )
    for entry in explicit_entries:
        source = _role_creation_entry_source(entry)
        for item in _role_creation_split_named_items(entry.get("text"), limit=10, split_slash=True):
            candidate = _role_creation_candidate_name(item)
            if not _role_creation_is_knowledge_asset_candidate(candidate):
                continue
            rows.append({"text": candidate, "source": source})
    if not rows:
        for module in list(capability_package_spec.get("capability_modules") or [])[:4]:
            module_name = str(module.get("module_name") or "").strip()
            if not _role_creation_is_knowledge_asset_candidate(module_name):
                continue
            rows.append(
                {
                    "text": module_name,
                    "source_message_ids": list(module.get("source_message_ids") or []),
                    "last_updated_at": str(module.get("last_updated_at") or "").strip(),
                    "source_preview": str(module.get("source_preview") or "").strip(),
                }
            )
    if not rows:
        fallback_rows = _role_creation_sentence_entries(
            fragments,
            ("知识沉淀", "知识资产", "沉淀", "模板", "示例", "反例", "验收清单", "文档"),
            limit=6,
        )
        for item in fallback_rows:
            candidate = _role_creation_candidate_name(item.get("text")) or _normalize_text(item.get("text"), max_len=120)
            if not _role_creation_is_knowledge_asset_candidate(candidate):
                continue
            rows.append(
                {
                    "text": candidate,
                    "source_message_ids": list(item.get("source_message_ids") or []),
                    "last_updated_at": str(item.get("last_updated_at") or "").strip(),
                    "source_preview": str(item.get("source_preview") or "").strip(),
                }
            )
    assets: list[dict[str, Any]] = []
    for index, item in enumerate(rows, start=1):
        topic = _role_creation_candidate_name(item.get("text")) or _normalize_text(item.get("text"), max_len=120)
        if not topic:
            continue
        asset_type = _role_creation_asset_type_from_text(topic)
        assets.append(
            {
                "asset_id": safe_token(topic + "-" + asset_type, f"asset-{index}", 80) or f"asset-{index}",
                "asset_type": asset_type,
                "asset_topic": topic,
                "recommended_path": _role_creation_asset_path(asset_type, topic, index),
                "status": "planned",
                "priority": _role_creation_asset_priority(index, topic),
                "confirmation_status": "ready",
                "source_message_ids": list(item.get("source_message_ids") or []),
                "last_updated_at": str(item.get("last_updated_at") or "").strip(),
                "source_preview": str(item.get("source_preview") or "").strip(),
            }
        )
    unique_assets: list[dict[str, Any]] = []
    seen_asset_keys: set[str] = set()
    for asset in assets:
        key = (str(asset.get("asset_type") or "") + "|" + str(asset.get("asset_topic") or "")).lower()
        if key in seen_asset_keys:
            continue
        seen_asset_keys.add(key)
        unique_assets.append(asset)
    pending_items: list[str] = []
    if not unique_assets:
        pending_items.append("补充至少 1 类知识沉淀资产")
    source = _role_creation_pick_latest_source(unique_assets)
    return {
        "layer_key": "knowledge_asset_plan",
        "layer_label": "知识沉淀",
        "confirmation_status": _role_creation_confirmation_status(
            item_count=len(unique_assets),
            required_count=1,
            pending_items=pending_items,
        ),
        "assets": unique_assets[:6],
        "pending_items": pending_items,
        **source,
    }


def _role_creation_seed_task_name_for_asset(asset: dict[str, Any]) -> str:
    topic = str(asset.get("asset_topic") or "").strip()
    asset_type = str(asset.get("asset_type") or "").strip()
    if topic and asset_type and asset_type in topic:
        return f"沉淀{topic}"
    return f"沉淀{topic}{asset_type}".strip()


def _role_creation_seed_delivery_plan(
    capability_package_spec: dict[str, Any],
    knowledge_asset_plan: dict[str, Any],
) -> dict[str, Any]:
    capability_objects: list[dict[str, Any]] = []
    for index, module in enumerate(list(capability_package_spec.get("capability_modules") or [])[:4], start=1):
        module_name = str(module.get("module_name") or "").strip()
        if not module_name:
            continue
        capability_objects.append(
            {
                "capability_id": safe_token(module_name, f"seed-capability-{index}", 80) or f"seed-capability-{index}",
                "capability_name": module_name,
                "capability_goal": str(module.get("module_goal") or "").strip(),
                "source_module": module_name,
                "acceptance_hint": "至少产出 1 份结构化结果，并能说明该能力的适用条件与边界。",
                "current_status": "draft",
                "source_message_ids": list(module.get("source_message_ids") or []),
                "last_updated_at": str(module.get("last_updated_at") or "").strip(),
                "source_preview": str(module.get("source_preview") or "").strip(),
            }
        )
    task_suggestions: list[dict[str, Any]] = []
    for index, capability in enumerate(capability_objects[:3], start=1):
        task_suggestions.append(
            {
                "task_id": safe_token(str(capability.get("capability_name") or ""), f"seed-task-{index}", 80) or f"seed-task-{index}",
                "task_name": f"生成{str(capability.get('capability_name') or '').strip()}能力对象",
                "linked_target": str(capability.get("capability_name") or "").strip(),
                "task_type": "capability_object",
                "stage_key": "capability_generation",
                "should_enter_task_center": True,
                "priority": "P0" if index == 1 else "P1",
                "source_message_ids": list(capability.get("source_message_ids") or []),
                "last_updated_at": str(capability.get("last_updated_at") or "").strip(),
                "source_preview": str(capability.get("source_preview") or "").strip(),
            }
        )
    for index, asset in enumerate(list(knowledge_asset_plan.get("assets") or [])[:2], start=1):
        task_suggestions.append(
            {
                "task_id": safe_token(str(asset.get("asset_topic") or ""), f"knowledge-task-{index}", 80) or f"knowledge-task-{index}",
                "task_name": _role_creation_seed_task_name_for_asset(asset),
                "linked_target": str(asset.get("asset_topic") or "").strip(),
                "task_type": "knowledge_asset",
                "stage_key": "persona_collection",
                "should_enter_task_center": True,
                "priority": "P0" if index == 1 else "P1",
                "source_message_ids": list(asset.get("source_message_ids") or []),
                "last_updated_at": str(asset.get("last_updated_at") or "").strip(),
                "source_preview": str(asset.get("source_preview") or "").strip(),
            }
        )
    priority_order = [
        str(item.get("task_name") or item.get("capability_name") or "").strip()
        for item in list(task_suggestions or [])[:4]
        if str(item.get("task_name") or item.get("capability_name") or "").strip()
    ]
    pending_items: list[str] = []
    if not capability_objects:
        pending_items.append("至少形成 1 个首批能力对象")
    if not task_suggestions:
        pending_items.append("至少形成 1 条首批任务建议")
    source = _role_creation_pick_latest_source(capability_objects + task_suggestions)
    return {
        "layer_key": "seed_delivery_plan",
        "layer_label": "首批任务",
        "confirmation_status": _role_creation_confirmation_status(
            item_count=len(capability_objects) + len(task_suggestions),
            required_count=2,
            pending_items=pending_items,
        ),
        "capability_objects": capability_objects,
        "task_suggestions": task_suggestions,
        "priority_order": priority_order,
        "pending_items": pending_items,
        **source,
    }


def _role_creation_start_gate(role_profile_spec: dict[str, Any], capability_package_spec: dict[str, Any], knowledge_asset_plan: dict[str, Any], seed_delivery_plan: dict[str, Any]) -> dict[str, Any]:
    profile_ready = str(role_profile_spec.get("confirmation_status") or "") == "ready"
    capability_ready = (
        len(list(capability_package_spec.get("capability_modules") or [])) >= 1
        and bool((capability_package_spec.get("default_delivery_policy") or {}).get("summary"))
        and (
            bool((capability_package_spec.get("format_strategy") or {}).get("summary"))
            or bool(list((capability_package_spec.get("format_strategy") or {}).get("allowed_formats") or []))
        )
    )
    knowledge_ready = len(list(knowledge_asset_plan.get("assets") or [])) >= 1
    seed_ready = len(list(seed_delivery_plan.get("capability_objects") or [])) >= 1 and len(list(seed_delivery_plan.get("task_suggestions") or [])) >= 1
    blockers: list[str] = []
    if not profile_ready:
        blockers.append("角色画像仍有待确认项")
    if not capability_ready:
        blockers.append("能力包还缺模块/交付策略/格式边界中的关键信息")
    if not knowledge_ready:
        blockers.append("知识沉淀计划尚未形成")
    if not seed_ready:
        blockers.append("首批能力对象或首批任务建议尚未形成")
    return {
        "profile_ready": bool(profile_ready),
        "capability_package_ready": bool(capability_ready),
        "knowledge_asset_ready": bool(knowledge_ready),
        "seed_delivery_ready": bool(seed_ready),
        "can_start": not blockers,
        "blockers": blockers,
    }

def _role_creation_compose_spec(messages: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    user_messages = _role_creation_user_chat_messages(messages)
    assistant_messages = [item for item in messages if str(item.get("role") or "").strip().lower() == "assistant"]
    user_texts = _session_messages_texts(user_messages, role="user")
    assistant_texts = _session_messages_texts(assistant_messages, role="assistant")
    fragments = _role_creation_text_fragments(user_messages)
    labeled: dict[str, list[str]] = {key: [] for key in ROLE_CREATION_ALL_FIELDS if key != "example_assets"}
    for text in user_texts:
        extracted = _extract_labeled_values(text)
        natural = _extract_natural_language_values(text)
        for key, items in extracted.items():
            labeled.setdefault(key, []).extend(items)
        for key, items in natural.items():
            labeled.setdefault(key, []).extend(items)
    attachments: list[dict[str, Any]] = []
    for message in user_messages:
        for item in list(message.get("attachments") or []):
            if not isinstance(item, dict):
                continue
            attachments.append(
                {
                    "attachment_id": str(item.get("attachment_id") or "").strip(),
                    "file_name": str(item.get("file_name") or "").strip(),
                    "content_type": str(item.get("content_type") or "").strip(),
                    "size_bytes": int(item.get("size_bytes") or 0),
                    "data_url": str(item.get("data_url") or ""),
                }
            )
    role_name = _normalize_role_name_candidate((labeled.get("role_name") or [""])[-1])
    if not role_name:
        role_name = _guess_role_name(user_texts)
    if not role_name:
        role_name = _guess_role_name_from_assistant_suggestions(assistant_texts)
    role_goal = _normalize_text((labeled.get("role_goal") or [""])[-1], max_len=280)
    if not role_goal:
        guesses = _collect_sentence_items(user_texts, ("目标", "职责", "负责", "帮助", "用于", "希望它", "用来"), limit=3)
        role_goal = "；".join(guesses[:2])[:280]
    core_capabilities = _split_items(labeled.get("core_capabilities") or [], limit=12)
    if not core_capabilities:
        guesses = _collect_sentence_items(
            user_texts,
            ("能力", "擅长", "会", "生成", "整理", "拆解", "诊断", "设计", "沉淀"),
            limit=6,
        )
        core_capabilities = _split_items(guesses, limit=12)
    boundaries = _split_items(labeled.get("boundaries") or [], limit=10)
    if not boundaries:
        boundaries = _split_items(
            _collect_sentence_items(user_texts, ("边界", "约束", "不要", "不能", "禁止", "避免", "别"), limit=6),
            limit=10,
        )
    applicable_scenarios = _split_items(labeled.get("applicable_scenarios") or [], limit=10)
    if not applicable_scenarios:
        applicable_scenarios = _split_items(
            _collect_sentence_items(user_texts, ("场景", "适用", "用于", "面向"), limit=6),
            limit=10,
        )
    collaboration_style = _normalize_text((labeled.get("collaboration_style") or [""])[-1], max_len=280)
    if not collaboration_style:
        guesses = _collect_sentence_items(user_texts, ("协作", "风格", "输出", "语气", "回传"), limit=3)
        collaboration_style = "；".join(guesses[:2])[:280]
    role_profile_spec, missing_fields = _role_creation_role_profile_spec(
        role_name,
        role_goal,
        core_capabilities,
        boundaries,
        applicable_scenarios,
        collaboration_style,
        attachments,
        fragments,
    )
    role_spec = {
        "role_name": role_name,
        "role_goal": role_goal,
        "core_capabilities": core_capabilities,
        "boundaries": boundaries,
        "applicable_scenarios": applicable_scenarios,
        "collaboration_style": collaboration_style,
        "example_assets": attachments[:6],
        "role_profile_spec": role_profile_spec,
    }
    capability_package_spec = _role_creation_capability_package_spec(role_spec, fragments)
    knowledge_asset_plan = _role_creation_knowledge_asset_plan(capability_package_spec, fragments)
    seed_delivery_plan = _role_creation_seed_delivery_plan(capability_package_spec, knowledge_asset_plan)
    start_gate = _role_creation_start_gate(role_profile_spec, capability_package_spec, knowledge_asset_plan, seed_delivery_plan)
    role_spec.update(
        {
            "capability_package_spec": capability_package_spec,
            "knowledge_asset_plan": knowledge_asset_plan,
            "seed_delivery_plan": seed_delivery_plan,
            "start_gate": start_gate,
        }
    )
    return role_spec, missing_fields


def _role_creation_recent_changes(current_spec: dict[str, Any], previous_spec: dict[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    field_labels = {
        "role_name": "角色名",
        "role_goal": "角色目标",
        "core_capabilities": "核心能力",
        "boundaries": "边界",
        "applicable_scenarios": "适用场景",
        "collaboration_style": "协作方式",
    }
    for field_key, field_label in field_labels.items():
        current_value = current_spec.get(field_key)
        previous_value = previous_spec.get(field_key)
        if current_value == previous_value:
            continue
        if isinstance(current_value, list):
            current_text = "；".join([str(item).strip() for item in list(current_value or []) if str(item).strip()][:3])
        else:
            current_text = _normalize_text(current_value, max_len=80)
        if not current_text:
            continue
        changes.append(
            {
                "layer_key": "role_profile_spec",
                "layer_label": "角色画像",
                "item_label": field_label,
                "change_type": "updated" if previous_value else "added",
                "summary": f"{field_label}已更新：{current_text}",
            }
        )
    current_modules = {
        str(item.get("module_name") or "").strip()
        for item in list((current_spec.get("capability_package_spec") or {}).get("capability_modules") or [])
        if str(item.get("module_name") or "").strip()
    }
    previous_modules = {
        str(item.get("module_name") or "").strip()
        for item in list((previous_spec.get("capability_package_spec") or {}).get("capability_modules") or [])
        if str(item.get("module_name") or "").strip()
    }
    added_modules = [item for item in current_modules if item not in previous_modules]
    if added_modules:
        changes.append(
            {
                "layer_key": "capability_package_spec",
                "layer_label": "能力包",
                "item_label": "能力模块",
                "change_type": "added",
                "summary": "新增能力模块：" + " / ".join(added_modules[:4]),
            }
        )
    current_delivery_summary = _normalize_text(
        ((current_spec.get("capability_package_spec") or {}).get("default_delivery_policy") or {}).get("summary"),
        max_len=160,
    )
    previous_delivery_summary = _normalize_text(
        ((previous_spec.get("capability_package_spec") or {}).get("default_delivery_policy") or {}).get("summary"),
        max_len=160,
    )
    if current_delivery_summary and current_delivery_summary != previous_delivery_summary:
        changes.append(
            {
                "layer_key": "capability_package_spec",
                "layer_label": "能力包",
                "item_label": "默认交付策略",
                "change_type": "updated" if previous_delivery_summary else "added",
                "summary": "默认交付策略已更新：" + current_delivery_summary,
            }
        )
    current_format_strategy = (current_spec.get("capability_package_spec") or {}).get("format_strategy") or {}
    previous_format_strategy = (previous_spec.get("capability_package_spec") or {}).get("format_strategy") or {}
    current_format_summary = _normalize_text(current_format_strategy.get("summary"), max_len=160)
    previous_format_summary = _normalize_text(previous_format_strategy.get("summary"), max_len=160)
    if current_format_summary and current_format_summary != previous_format_summary:
        changes.append(
            {
                "layer_key": "capability_package_spec",
                "layer_label": "能力包",
                "item_label": "格式边界",
                "change_type": "updated" if previous_format_summary else "added",
                "summary": "格式边界已更新：" + current_format_summary,
            }
        )
    current_priority_order = [
        str(item).strip()
        for item in list((current_spec.get("seed_delivery_plan") or {}).get("priority_order") or [])
        if str(item).strip()
    ]
    previous_priority_order = [
        str(item).strip()
        for item in list((previous_spec.get("seed_delivery_plan") or {}).get("priority_order") or [])
        if str(item).strip()
    ]
    if current_priority_order and current_priority_order != previous_priority_order:
        changes.append(
            {
                "layer_key": "seed_delivery_plan",
                "layer_label": "首批任务",
                "item_label": "优先顺序",
                "change_type": "updated" if previous_priority_order else "added",
                "summary": "首批任务优先顺序：" + " / ".join(current_priority_order[:4]),
            }
        )
    current_assets = {
        str(item.get("asset_topic") or "").strip()
        for item in list((current_spec.get("knowledge_asset_plan") or {}).get("assets") or [])
        if str(item.get("asset_topic") or "").strip()
    }
    previous_assets = {
        str(item.get("asset_topic") or "").strip()
        for item in list((previous_spec.get("knowledge_asset_plan") or {}).get("assets") or [])
        if str(item.get("asset_topic") or "").strip()
    }
    added_assets = [item for item in current_assets if item not in previous_assets]
    if added_assets:
        changes.append(
            {
                "layer_key": "knowledge_asset_plan",
                "layer_label": "知识沉淀",
                "item_label": "知识资产",
                "change_type": "added",
                "summary": "新增知识沉淀：" + " / ".join(added_assets[:4]),
            }
        )
    current_seed = {
        str(item.get("capability_name") or item.get("task_name") or "").strip()
        for item in list((current_spec.get("seed_delivery_plan") or {}).get("capability_objects") or [])
        + list((current_spec.get("seed_delivery_plan") or {}).get("task_suggestions") or [])
        if str(item.get("capability_name") or item.get("task_name") or "").strip()
    }
    previous_seed = {
        str(item.get("capability_name") or item.get("task_name") or "").strip()
        for item in list((previous_spec.get("seed_delivery_plan") or {}).get("capability_objects") or [])
        + list((previous_spec.get("seed_delivery_plan") or {}).get("task_suggestions") or [])
        if str(item.get("capability_name") or item.get("task_name") or "").strip()
    }
    added_seed = [item for item in current_seed if item not in previous_seed]
    if added_seed:
        changes.append(
            {
                "layer_key": "seed_delivery_plan",
                "layer_label": "首批任务",
                "item_label": "首批对象",
                "change_type": "added",
                "summary": "新增首批对象/任务：" + " / ".join(added_seed[:4]),
            }
        )
    return changes[:6]


def _role_creation_pending_questions(role_spec: dict[str, Any]) -> list[str]:
    pending: list[str] = []
    for layer_key in ("role_profile_spec", "capability_package_spec", "knowledge_asset_plan", "seed_delivery_plan"):
        layer = role_spec.get(layer_key) if isinstance(role_spec.get(layer_key), dict) else {}
        for item in list(layer.get("pending_items") or []):
            text = str(item or "").strip()
            if text and text not in pending:
                pending.append(text)
    return pending[:8]


def _build_role_spec(messages: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    current_spec, missing_fields = _role_creation_compose_spec(messages)
    previous_messages = list(messages or [])
    last_user_index = -1
    for index in range(len(previous_messages) - 1, -1, -1):
        item = previous_messages[index]
        if str(item.get("role") or "").strip().lower() == "user" and _normalize_message_type(item.get("message_type")) == "chat":
            last_user_index = index
            break
    previous_spec = {}
    if last_user_index > 0:
        previous_spec, _ignored = _role_creation_compose_spec(previous_messages[:last_user_index])
    current_spec["recent_changes"] = _role_creation_recent_changes(current_spec, previous_spec)
    current_spec["pending_questions"] = _role_creation_pending_questions(current_spec)
    return current_spec, missing_fields


def _session_can_start(role_spec: dict[str, Any]) -> bool:
    start_gate = role_spec.get("start_gate") if isinstance(role_spec.get("start_gate"), dict) else {}
    if start_gate:
        return bool(start_gate.get("can_start"))
    for key in ROLE_CREATION_REQUIRED_FIELDS:
        value = role_spec.get(key)
        if isinstance(value, list):
            if not value:
                return False
            continue
        if not str(value or "").strip():
            return False
    return True


def _role_creation_title_from_spec(role_spec: dict[str, Any], fallback: str = "") -> str:
    role_name = _normalize_text(role_spec.get("role_name"), max_len=40)
    if role_name:
        return role_name
    return _normalize_text(fallback, max_len=40) or "未命名角色草稿"


def _missing_field_labels(missing_fields: list[str]) -> list[str]:
    mapping = {
        "role_name": "角色名",
        "role_goal": "角色目标",
        "core_capabilities": "核心能力",
        "boundaries": "禁止边界",
        "applicable_scenarios": "适用场景",
        "collaboration_style": "协作方式",
        "example_assets": "示例图片",
    }
    return [mapping.get(item, item) for item in missing_fields]


def _build_assistant_reply(
    *,
    session_summary: dict[str, Any],
    role_spec: dict[str, Any],
    missing_fields: list[str],
    created_tasks: list[dict[str, Any]],
) -> str:
    title = _role_creation_title_from_spec(role_spec, session_summary.get("session_title") or "")
    missing_labels = _missing_field_labels(missing_fields)
    start_gate = role_spec.get("start_gate") if isinstance(role_spec.get("start_gate"), dict) else {}
    start_blockers = [str(item).strip() for item in list(start_gate.get("blockers") or []) if str(item).strip()]
    pending_questions = [str(item).strip() for item in list(role_spec.get("pending_questions") or []) if str(item).strip()]
    can_start = _session_can_start(role_spec)
    capability_lines = _split_items(role_spec.get("core_capabilities") or [], limit=4)
    if created_tasks:
        names = [str(item.get("task_name") or item.get("node_name") or "").strip() for item in created_tasks]
        names = [item for item in names if item]
        task_line = "；".join(names[:3])
        return (
            f"已按你的委派新建后台任务：{task_line}。"
            "右侧阶段图已经改成真实任务引用，我会继续在当前会话里帮你收口画像和验收。"
        )
    if session_summary.get("status") == "creating":
        if missing_labels:
            return (
                f"我已经把「{title}」的草案继续收口。"
                f"当前还建议补这几项：{'、'.join(missing_labels[:4])}。"
                "如果你想把某项工作单独丢到后台，直接说“另起一个任务去……”。"
            )
        if capability_lines:
            return (
                f"「{title}」当前核心能力已聚焦在：{' / '.join(capability_lines[:3])}。"
                "你可以继续补充方向，也可以把当前轮推到验收。"
            )
        return f"我会继续围绕「{title}」推进创建流程。"
    if can_start:
        return f"「{title}」已经形成角色画像、能力包、知识沉淀和首批任务建议，可以直接点“开始创建”。"
    if start_blockers:
        return (
            f"我先把「{title}」收口成结构化草案了。"
            f"当前还差：{'；'.join(start_blockers[:3])}。"
        )
    if pending_questions:
        return (
            f"我先把「{title}」收口成结构化草案了。"
            f"下一步优先确认：{'、'.join(pending_questions[:3])}。"
        )
    if missing_labels:
        return (
            f"我先按当前描述把「{title}」收口成草案了。"
            f"开始创建前最好再补：{'、'.join(missing_labels[:4])}。"
        )
    return f"我先继续围绕「{title}」补齐能力包和知识沉淀，再进入开始创建。"


def _delegate_requests_from_text(text: str) -> list[str]:
    content = _normalize_text(text, max_len=4000)
    if not content or not ROLE_CREATION_DELEGATE_PATTERN.search(content):
        return []
    clauses = re.split(r"[。！？!?]\s*", content)
    return [
        _normalize_text(clause, max_len=400)
        for clause in clauses
        if _normalize_text(clause, max_len=400) and ROLE_CREATION_DELEGATE_PATTERN.search(clause)
    ][:3]


def _infer_task_stage_key(text: str, current_stage_key: str) -> str:
    content = str(text or "")
    if any(token in content for token in ("回传", "预览", "截图", "回看")):
        return "review_and_alignment"
    if any(token in content for token in ("生成", "样例", "草案", "模板", "页面", "html")):
        return "capability_generation"
    if any(token in content for token in ("资料", "案例", "调研", "画像", "整理", "收集")):
        return "persona_collection"
    if current_stage_key in {"persona_collection", "capability_generation", "review_and_alignment"}:
        return current_stage_key
    return "persona_collection"


def _delegate_task_title(text: str, role_name: str) -> str:
    content = _normalize_text(text, max_len=200)
    content = ROLE_CREATION_DELEGATE_PATTERN.sub("", content, count=1).strip("，,。.!！？；;：: ")
    content = re.sub(r"^(请|帮我|帮忙|先|再|就)\s*", "", content)
    content = re.sub(r"(然后|并且|并)\s*回传.*$", "", content)
    content = re.sub(r"(回头|之后|最后).*$", "", content)
    content = _normalize_text(content, max_len=60)
    if not content:
        return f"补充{role_name or '新角色'}后台任务"
    if re.match(r"^(收集|整理|生成|沉淀|补|回传|分析)", content):
        return content
    return "处理" + content
