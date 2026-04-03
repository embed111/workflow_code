from __future__ import annotations


def bind_runtime_symbols(symbols: dict[str, object]) -> None:
    globals().update(symbols)


def parse_markdown_sections(markdown_text: str) -> list[tuple[str, int, str]]:
    text = str(markdown_text or "")
    if not text.strip():
        return []
    lines = text.splitlines()
    heading_re = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")
    headings: list[tuple[int, int, str]] = []
    for idx, raw in enumerate(lines):
        line = raw.rstrip("\n")
        matched = heading_re.match(line)
        if not matched:
            continue
        level = int(len(matched.group(1)))
        title = matched.group(2).strip()
        if not title:
            continue
        headings.append((idx, level, title))
    sections: list[tuple[str, int, str]] = []
    for idx, (line_no, level, title) in enumerate(headings):
        end_line = len(lines)
        for next_line_no, next_level, _next_title in headings[idx + 1 :]:
            if next_level <= level:
                end_line = next_line_no
                break
        block = "\n".join(lines[line_no + 1 : end_line]).strip()
        sections.append((title, level, block))
    return sections


def policy_text_compact(text: str, *, max_chars: int) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    if len(value) > max_chars:
        return value[:max_chars].rstrip() + "\n...(已截断)"
    return value


def normalize_heading_title(title: str) -> str:
    value = str(title or "").strip().lower()
    value = value.replace(" ", "")
    value = re.sub(r"[`~!@#$%^&*()_+\-=\[\]{};:'\",.<>/?\\|，。！？；：（）【】《》、]", "", value)
    return value


def heading_matches(title: str, anchor: str) -> bool:
    norm_title = normalize_heading_title(title)
    norm_anchor = normalize_heading_title(anchor)
    return bool(norm_anchor and norm_title.startswith(norm_anchor))


def find_first_section_by_headings(
    sections: list[tuple[str, int, str]],
    headings: tuple[str, ...],
) -> tuple[str, int, str] | None:
    for anchor in headings:
        for section in sections:
            title, _level, _content = section
            if heading_matches(title, anchor):
                return section
    return None


def find_sections_by_headings(
    sections: list[tuple[str, int, str]],
    headings: tuple[str, ...],
    *,
    limit: int,
) -> list[tuple[str, int, str]]:
    picked: list[tuple[str, int, str]] = []
    seen_titles: set[str] = set()
    for anchor in headings:
        for section in sections:
            title, _level, _content = section
            key = normalize_heading_title(title)
            if key in seen_titles:
                continue
            if heading_matches(title, anchor):
                picked.append(section)
                seen_titles.add(key)
            if len(picked) >= max(1, limit):
                return picked
    return picked


def heading_contains(title: str, anchor: str) -> bool:
    norm_title = normalize_heading_title(title)
    norm_anchor = normalize_heading_title(anchor)
    return bool(norm_anchor and norm_anchor in norm_title)


def find_sections_by_heading_contains(
    sections: list[tuple[str, int, str]],
    headings: tuple[str, ...],
    *,
    limit: int,
) -> list[tuple[str, int, str]]:
    picked: list[tuple[str, int, str]] = []
    seen_titles: set[str] = set()
    for section in sections:
        title, _level, _content = section
        key = normalize_heading_title(title)
        if key in seen_titles:
            continue
        if any(heading_contains(title, anchor) for anchor in headings):
            picked.append(section)
            seen_titles.add(key)
            if len(picked) >= max(1, limit):
                break
    return picked


def line_clean_for_summary(text: str) -> str:
    value = str(text or "").strip()
    value = re.sub(r"^\s*(?:[-*+]|[0-9]+[.)]|[（(]?[0-9]+[）)])\s*", "", value)
    return value.strip()


def summarize_section_content(
    text: str,
    *,
    max_chars: int,
    max_lines: int,
) -> str:
    lines = []
    for raw in str(text or "").splitlines():
        item = line_clean_for_summary(raw)
        if not item:
            continue
        lines.append(item)
        if len(lines) >= max(1, max_lines):
            break
    if not lines:
        return ""
    merged = " ".join(lines)
    return policy_text_compact(merged, max_chars=max_chars)


def extract_list_items_from_text(
    text: str,
    *,
    max_items: int = 12,
) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    bullet_re = re.compile(r"^\s*(?:[-*+]|[0-9]+[.)]|[（(]?[0-9]+[）)])\s*(.+?)\s*$")
    for raw in str(text or "").splitlines():
        matched = bullet_re.match(raw)
        if not matched:
            continue
        value = line_clean_for_summary(matched.group(1))
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        items.append(value)
        seen.add(key)
        if len(items) >= max(1, max_items):
            return items
    if items:
        return items
    for raw in str(text or "").splitlines():
        value = line_clean_for_summary(raw)
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        items.append(value)
        seen.add(key)
        if len(items) >= max(1, max_items):
            break
    return items


def constraint_text_key(text: str) -> str:
    value = str(text or "").strip().lower()
    value = re.sub(r"\s+", "", value)
    value = value.replace("必须", "").replace("应当", "").replace("不得", "").replace("禁止", "")
    value = value.replace("不能", "").replace("不可", "").replace("must", "").replace("mustnot", "")
    value = re.sub(r"[`~!@#$%^&*()_+\-=\[\]{};:'\",.<>/?\\|，。！？；：（）【】《》、]", "", value)
    return value


def extract_constraint_entries_from_sections(
    sections: list[tuple[str, int, str]],
    *,
    max_items: int = 10,
) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for section in sections:
        title, _level, content = section
        for item in extract_list_items_from_text(content, max_items=max_items):
            text = policy_text_compact(str(item or "").strip(), max_chars=220)
            if not text:
                continue
            key = constraint_text_key(text)
            if key in seen:
                continue
            seen.add(key)
            entries.append(
                {
                    "text": text,
                    "evidence": policy_text_compact(f"{title}\n{text}", max_chars=260),
                    "source_title": str(title or ""),
                }
            )
            if len(entries) >= max(1, max_items):
                return entries
    return entries


def text_contains_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    value = str(text or "").strip().lower()
    if not value:
        return False
    compact = re.sub(r"\s+", "", value)
    for keyword in keywords:
        probe = str(keyword or "").strip().lower()
        if not probe:
            continue
        if probe in value:
            return True
        probe_compact = re.sub(r"\s+", "", probe)
        if probe_compact and probe_compact in compact:
            return True
    return False


def classify_constraint_kind(entry: dict[str, str]) -> str:
    title = str(entry.get("source_title") or "").strip()
    text = str(entry.get("text") or "").strip()
    combined = f"{title}\n{text}".strip()
    if title and any(heading_contains(title, anchor) for anchor in _AGENT_MUST_NOT_HEADINGS):
        return "must_not"
    if title and any(heading_contains(title, anchor) for anchor in _AGENT_PRECONDITION_HEADINGS):
        return "preconditions"
    if title and any(heading_contains(title, anchor) for anchor in _AGENT_MUST_HEADINGS):
        return "must"
    if text_contains_any_keyword(combined, _CONSTRAINT_MUST_NOT_TERMS):
        return "must_not"
    if text_contains_any_keyword(combined, _CONSTRAINT_PRECONDITION_TERMS):
        return "preconditions"
    if re.search(r"在.{0,12}前", combined):
        return "preconditions"
    if text_contains_any_keyword(combined, _CONSTRAINT_MUST_TERMS):
        return "must"
    return ""


def classify_constraint_entries(
    entries: list[dict[str, str]],
    *,
    max_items: int = 10,
) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {
        "must": [],
        "must_not": [],
        "preconditions": [],
    }
    seen_by_kind: dict[str, set[str]] = {
        "must": set(),
        "must_not": set(),
        "preconditions": set(),
    }
    for raw in entries:
        if not isinstance(raw, dict):
            continue
        text = policy_text_compact(str(raw.get("text") or "").strip(), max_chars=220)
        if not text:
            continue
        kind = classify_constraint_kind(raw)
        if kind not in grouped:
            continue
        key = constraint_text_key(text)
        if not key or key in seen_by_kind[kind]:
            continue
        seen_by_kind[kind].add(key)
        grouped[kind].append(
            {
                "text": text,
                "evidence": policy_text_compact(str(raw.get("evidence") or "").strip(), max_chars=260),
                "source_title": str(raw.get("source_title") or "").strip(),
            }
        )
        if len(grouped[kind]) >= max(1, max_items):
            grouped[kind] = grouped[kind][: max(1, max_items)]
    return grouped


def filter_constraint_entries_by_kind(
    entries: list[dict[str, str]],
    *,
    kind: str,
    max_items: int = 10,
) -> list[dict[str, str]]:
    picked: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in entries:
        if not isinstance(raw, dict):
            continue
        if classify_constraint_kind(raw) != kind:
            continue
        text = policy_text_compact(str(raw.get("text") or "").strip(), max_chars=220)
        if not text:
            continue
        key = constraint_text_key(text)
        if not key or key in seen:
            continue
        seen.add(key)
        picked.append(
            {
                "text": text,
                "evidence": policy_text_compact(str(raw.get("evidence") or "").strip(), max_chars=260),
                "source_title": str(raw.get("source_title") or "").strip(),
            }
        )
        if len(picked) >= max(1, max_items):
            break
    return picked


def extract_constraints_from_policy(
    *,
    sections: list[tuple[str, int, str]],
    duty_items: list[str],
) -> dict[str, Any]:
    must_sections = find_sections_by_heading_contains(sections, _AGENT_MUST_HEADINGS, limit=3)
    must_not_sections = find_sections_by_heading_contains(sections, _AGENT_MUST_NOT_HEADINGS, limit=3)
    pre_sections = find_sections_by_heading_contains(sections, _AGENT_PRECONDITION_HEADINGS, limit=3)

    limit_sections = find_sections_by_heading_contains(sections, _AGENT_LIMIT_HEADINGS, limit=3)

    must_entries = extract_constraint_entries_from_sections(must_sections, max_items=10)
    must_not_entries = extract_constraint_entries_from_sections(must_not_sections, max_items=10)
    pre_entries = extract_constraint_entries_from_sections(pre_sections, max_items=10)
    must_entries = filter_constraint_entries_by_kind(must_entries, kind="must", max_items=10)
    must_not_entries = filter_constraint_entries_by_kind(must_not_entries, kind="must_not", max_items=10)
    pre_entries = filter_constraint_entries_by_kind(pre_entries, kind="preconditions", max_items=10)

    if limit_sections and (not must_entries or not must_not_entries or not pre_entries):
        limit_entries = extract_constraint_entries_from_sections(limit_sections, max_items=24)
        grouped_from_limit = classify_constraint_entries(limit_entries, max_items=10)
        if not must_entries:
            must_entries = grouped_from_limit.get("must") or []
        if not must_not_entries:
            must_not_entries = grouped_from_limit.get("must_not") or []
        if not pre_entries:
            pre_entries = grouped_from_limit.get("preconditions") or []

    if not must_entries or not must_not_entries or not pre_entries:
        duty_raw_entries: list[dict[str, str]] = []
        for item in duty_items:
            text = str(item or "").strip()
            if not text:
                continue
            duty_raw_entries.append(
                {
                    "text": policy_text_compact(text, max_chars=220),
                    "evidence": policy_text_compact(f"职责边界\n{text}", max_chars=260),
                    "source_title": "职责边界",
                }
            )
            if len(duty_raw_entries) >= 24:
                break
        grouped_from_duty = classify_constraint_entries(duty_raw_entries, max_items=10)
        if not must_entries:
            must_entries = grouped_from_duty.get("must") or []
        if not must_not_entries:
            must_not_entries = grouped_from_duty.get("must_not") or []
        if not pre_entries:
            pre_entries = grouped_from_duty.get("preconditions") or []

    all_entries = [*must_entries, *must_not_entries, *pre_entries]
    missing_evidence_count = sum(1 for entry in all_entries if not str(entry.get("evidence") or "").strip())

    conflicts: list[str] = []
    must_core_map: dict[str, str] = {}
    for entry in must_entries:
        core = constraint_text_key(entry.get("text") or "")
        if core:
            must_core_map[core] = str(entry.get("text") or "")
    for entry in must_not_entries:
        core = constraint_text_key(entry.get("text") or "")
        if core and core in must_core_map:
            conflicts.append(
                f"必须项“{must_core_map[core]}”与禁止项“{str(entry.get('text') or '')}”存在冲突"
            )

    issues: list[dict[str, str]] = []
    total_constraints = len(all_entries)
    if total_constraints <= 0:
        issues.append({"code": "constraints_missing", "message": "职责边界缺失，需人工确认。"})
    if missing_evidence_count > 0:
        issues.append(
            {
                "code": "constraints_evidence_missing",
                "message": f"职责边界存在 {missing_evidence_count} 条无证据映射，需人工确认。",
            }
        )
    if conflicts:
        issues.append(
            {
                "code": "constraints_conflict",
                "message": "职责边界存在冲突描述，需人工确认。",
            }
        )

    return {
        "must": must_entries,
        "must_not": must_not_entries,
        "preconditions": pre_entries,
        "issues": issues,
        "conflicts": conflicts,
        "missing_evidence_count": int(missing_evidence_count),
        "total": total_constraints,
    }


def first_non_empty_sentence(text: str, *, max_chars: int = 180) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if not value:
        return ""
    for sep in ("。", ".", "；", ";", "!", "！", "?", "？"):
        pos = value.find(sep)
        if 0 < pos <= max_chars:
            return value[: pos + 1]
    if len(value) > max_chars:
        return value[:max_chars].rstrip() + "..."
    return value


def section_evidence_snippet(
    section: tuple[str, int, str] | None,
    *,
    max_lines: int = 6,
    max_chars: int = 420,
) -> str:
    if not section:
        return ""
    title, _level, content = section
    lines: list[str] = []
    for raw in str(content or "").splitlines():
        cleaned = line_clean_for_summary(raw)
        if not cleaned:
            continue
        lines.append(cleaned)
        if len(lines) >= max(1, max_lines):
            break
    body = "\n".join(lines).strip()
    if not body:
        body = policy_text_compact(str(content or ""), max_chars=max_chars)
    return policy_text_compact(f"{title}\n{body}".strip(), max_chars=max_chars)


def policy_warning_text(code: str) -> str:
    mapping = {
        "agents_md_empty": "AGENTS.md 为空",
        "missing_role_section": "未识别到角色章节",
        "missing_goal_section": "未识别到目标章节",
        "goal_inferred_from_role_profile": "目标由角色内容推断",
        "missing_duty_section": "未识别到职责章节",
        "empty_duty_constraints": "职责章节缺少清晰条目",
        "missing_required_policy_fields": "关键字段不足",
        "constraints_missing": "职责边界缺失",
        "constraints_evidence_missing": "职责边界存在无证据条目",
        "constraints_conflict": "职责边界存在冲突",
    }
    key = str(code or "").strip()
    return mapping.get(key, key)
