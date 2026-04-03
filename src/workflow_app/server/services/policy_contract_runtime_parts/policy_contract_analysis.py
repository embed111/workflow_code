

def compute_policy_clarity(
    *,
    role_profile: str,
    session_goal: str,
    duty_constraints: list[str],
    parse_status: str,
    parse_warnings: list[str],
    evidence_snippets: dict[str, str],
    constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    role_text = str(role_profile or "").strip()
    goal_text = str(session_goal or "").strip()
    duty_items = [str(item or "").strip() for item in duty_constraints if str(item or "").strip()]
    warnings = [str(item or "").strip() for item in (parse_warnings or []) if str(item or "").strip()]
    status = str(parse_status or "failed").strip().lower() or "failed"
    constraints_data = constraints if isinstance(constraints, dict) else {}
    must_items = [item for item in (constraints_data.get("must") or []) if isinstance(item, dict)]
    must_not_items = [item for item in (constraints_data.get("must_not") or []) if isinstance(item, dict)]
    pre_items = [item for item in (constraints_data.get("preconditions") or []) if isinstance(item, dict)]
    constraint_issues = [item for item in (constraints_data.get("issues") or []) if isinstance(item, dict)]
    constraint_conflicts = [str(item).strip() for item in (constraints_data.get("conflicts") or []) if str(item or "").strip()]
    missing_evidence_count = int(constraints_data.get("missing_evidence_count") or 0)
    constraint_total = int(constraints_data.get("total") or (len(must_items) + len(must_not_items) + len(pre_items)))

    role_evidence = str((evidence_snippets or {}).get("role") or "").strip()
    goal_evidence = str((evidence_snippets or {}).get("goal") or "").strip()
    duty_evidence = str((evidence_snippets or {}).get("duty") or "").strip()
    constraints_evidence = [
        str(item.get("evidence") or "").strip()
        for item in [*must_items, *must_not_items, *pre_items]
        if str(item.get("evidence") or "").strip()
    ]

    def _safe_score(value: int) -> int:
        return max(0, min(100, int(value)))

    def _dimension(
        *,
        key: str,
        label: str,
        raw_score: int,
        evidence_refs: list[dict[str, str]],
        deduction_reason: str,
        repair_suggestion: str,
        threshold: int = 80,
    ) -> dict[str, Any]:
        score = _safe_score(raw_score)
        cleaned_refs = []
        seen_refs: set[str] = set()
        for ref in evidence_refs:
            ref_id = str((ref or {}).get("ref") or "").strip()
            snippet = policy_text_compact(str((ref or {}).get("snippet") or ""), max_chars=220)
            # 证据条目必须有可读片段；仅有 ref 但无 snippet 视为无证据。
            if not snippet:
                continue
            key_ref = f"{ref_id}:{snippet}"
            if key_ref in seen_refs:
                continue
            seen_refs.add(key_ref)
            cleaned_refs.append(
                {
                    "ref": ref_id or "unknown",
                    "snippet": snippet,
                }
            )
        has_evidence = bool(cleaned_refs)
        manual_review_required = False
        status_text = "ok"
        reason_text = ""
        if not has_evidence:
            # 无证据不扣分：保持中性分，强制人工确认。
            score = 80
            manual_review_required = True
            status_text = "manual_review"
            reason_text = "证据不足，需人工确认（无证据不直接扣分）。"
        elif score < threshold:
            status_text = "low"
            reason_text = str(deduction_reason or "").strip()
        return {
            "label": label,
            "score": score,
            "weight": float(POLICY_SCORE_WEIGHTS.get(key) or 0.0),
            "status": status_text,
            "has_evidence": has_evidence,
            "manual_review_required": manual_review_required,
            "deduction_reason": reason_text,
            "evidence_map": cleaned_refs,
            "repair_suggestion": str(repair_suggestion or "").strip(),
            "threshold": int(threshold),
        }

    duty_count = len(duty_items)
    duty_blob = "\n".join(duty_items)
    vague_terms = ("帮助", "支持", "相关", "适当", "尽量", "一些", "通用", "等等", "多种")
    vague_hits = sum(1 for term in vague_terms if term in f"{role_text}\n{goal_text}\n{duty_blob}")
    open_words = ("不限", "任何请求", "任意请求", "无边界", "都可以", "全部请求")
    limit_words = ("仅", "只", "不得", "禁止", "必须", "严禁", "边界")
    conflict_hits = 0
    if any(term in duty_blob for term in open_words) and any(term in duty_blob for term in limit_words):
        conflict_hits += 1
    if constraint_conflicts:
        conflict_hits += len(constraint_conflicts)

    completeness_raw = 0
    if role_text:
        completeness_raw += 34
    if goal_text:
        completeness_raw += 33
    if duty_items:
        completeness_raw += 33
    if status == "failed":
        completeness_raw = min(completeness_raw, 35)
    elif status == "incomplete":
        completeness_raw = min(completeness_raw, 75)

    executability_raw = 25
    if must_items:
        executability_raw += 30
    if must_not_items:
        executability_raw += 30
    if pre_items:
        executability_raw += 15
    if any(term in duty_blob for term in ("边界", "仅", "只", "不得", "禁止")):
        executability_raw += 10
    if constraint_total <= 0:
        executability_raw = min(executability_raw, 45)
    if conflict_hits > 0:
        executability_raw -= 20

    consistency_raw = 88
    if not (role_text and goal_text):
        consistency_raw = min(consistency_raw, 60)
    if not duty_items:
        consistency_raw = min(consistency_raw, 55)
    if "goal_inferred_from_role_profile" in warnings:
        consistency_raw -= 12
    if conflict_hits > 0:
        consistency_raw -= min(40, 18 * conflict_hits)
    if status == "failed":
        consistency_raw = min(consistency_raw, 40)
    elif status == "incomplete":
        consistency_raw = min(consistency_raw, 70)

    evidence_count = 0
    for key in ("role", "goal", "duty"):
        if str((evidence_snippets or {}).get(key) or "").strip():
            evidence_count += 1
    base_traceability = int(round((evidence_count / 3.0) * 70))
    constraint_trace = 0
    if constraint_total > 0:
        constraint_trace = int(round((len(constraints_evidence) / max(1, constraint_total)) * 30))
    traceability_raw = base_traceability + constraint_trace
    if status == "failed":
        traceability_raw = min(traceability_raw, 40)

    risk_raw = 28
    if must_not_items:
        risk_raw += 42
        if len(must_not_items) >= 3:
            risk_raw += 10
    risk_terms = ("高风险", "敏感", "生产", "删除", "覆盖", "密钥", "权限", "安全", "泄露")
    risk_hits = sum(
        1
        for term in risk_terms
        if term in duty_blob or any(term in str(item.get("text") or "") for item in must_not_items)
    )
    risk_raw += min(20, risk_hits * 4)
    if constraint_total <= 0:
        risk_raw = min(risk_raw, 48)

    action_terms = (
        "分析",
        "拆解",
        "验证",
        "检查",
        "输出",
        "给出",
        "澄清",
        "评估",
        "记录",
        "复盘",
    )
    action_hits = sum(1 for term in action_terms if term in f"{goal_text}\n{duty_blob}")
    operability_raw = 30 + min(42, duty_count * 12) + min(20, action_hits * 3)
    if len(goal_text) >= 16:
        operability_raw += 8
    if vague_hits >= 3:
        operability_raw -= 16
    elif vague_hits >= 1:
        operability_raw -= 8

    score_dimensions = {
        "completeness": _dimension(
            key="completeness",
            label="完整性",
            raw_score=completeness_raw,
            evidence_refs=[
                {"ref": "role", "snippet": role_evidence},
                {"ref": "goal", "snippet": goal_evidence},
                {"ref": "duty", "snippet": duty_evidence},
            ],
            deduction_reason="角色/目标/职责字段不完整，信息覆盖不足。",
            repair_suggestion="补充 AGENTS.md 中“角色定位 / 会话目标 / 职责边界”三段基础内容。",
        ),
        "executability": _dimension(
            key="executability",
            label="可执行边界",
            raw_score=executability_raw,
            evidence_refs=(
                [{"ref": "must", "snippet": str(item.get("evidence") or "")} for item in must_items]
                + [{"ref": "must_not", "snippet": str(item.get("evidence") or "")} for item in must_not_items]
                + [{"ref": "preconditions", "snippet": str(item.get("evidence") or "")} for item in pre_items]
            ),
            deduction_reason="能做/不能做边界不清晰，职责边界条目不足或存在冲突。",
            repair_suggestion="在 AGENTS.md 新增/完善“职责边界（must/must_not/preconditions）”章节。",
        ),
        "consistency": _dimension(
            key="consistency",
            label="一致性",
            raw_score=consistency_raw,
            evidence_refs=[
                {"ref": "duty", "snippet": duty_evidence},
                {"ref": "constraints", "snippet": "\n".join(constraint_conflicts)},
            ],
            deduction_reason="角色、目标或职责间存在冲突描述。",
            repair_suggestion="统一 AGENTS.md 中角色目标和职责描述，删除互相矛盾条目。",
        ),
        "traceability": _dimension(
            key="traceability",
            label="可追溯性",
            raw_score=traceability_raw,
            evidence_refs=(
                [
                    {"ref": "role", "snippet": role_evidence},
                    {"ref": "goal", "snippet": goal_evidence},
                    {"ref": "duty", "snippet": duty_evidence},
                ]
                + [{"ref": "constraints", "snippet": text} for text in constraints_evidence[:4]]
            ),
            deduction_reason="评分依据无法稳定映射到 AGENTS.md 原文证据。",
            repair_suggestion="将关键限制条目改为清晰列表，并在同段补充可定位描述。",
        ),
        "risk_coverage": _dimension(
            key="risk_coverage",
            label="风险覆盖度",
            raw_score=risk_raw,
            evidence_refs=(
                [{"ref": "must_not", "snippet": str(item.get("evidence") or "")} for item in must_not_items]
                + [{"ref": "duty", "snippet": duty_evidence}]
            ),
            deduction_reason="高风险行为约束覆盖不足，禁止项不充分。",
            repair_suggestion="补充 AGENTS.md 中禁止项（must_not），明确高风险操作处理边界。",
        ),
        "operability": _dimension(
            key="operability",
            label="可操作性",
            raw_score=operability_raw,
            evidence_refs=[
                {"ref": "goal", "snippet": goal_evidence},
                {"ref": "duty", "snippet": duty_evidence},
            ],
            deduction_reason="目标和职责可执行指令不足，难以直接指导会话行为。",
            repair_suggestion="将职责边界改写为可执行动作列表（动词 + 条件 + 输出）。",
        ),
    }

    total_score = 0.0
    for key, _label in POLICY_SCORE_DIMENSION_META:
        dim = score_dimensions.get(key) or {}
        total_score += float(POLICY_SCORE_WEIGHTS.get(key) or 0.0) * float(dim.get("score") or 0.0)
    clarity_score = _safe_score(int(round(total_score)))
    if status == "incomplete":
        clarity_score = _safe_score(clarity_score - 6)
    if len(warnings) >= 2:
        clarity_score = _safe_score(clarity_score - 3)

    manual_review_required = any(
        bool((score_dimensions.get(key) or {}).get("manual_review_required"))
        for key, _label in POLICY_SCORE_DIMENSION_META
    )

    issue_codes = {
        str(item.get("code") or "").strip().lower()
        for item in constraint_issues
        if isinstance(item, dict) and str(item.get("code") or "").strip()
    }
    constraints_block_auto = bool(
        constraint_total <= 0
        or missing_evidence_count > 0
        or bool(constraint_conflicts)
        or "constraints_missing" in issue_codes
        or "constraints_evidence_missing" in issue_codes
        or "constraints_conflict" in issue_codes
    )

    if status == "failed" or clarity_score < POLICY_CLARITY_CONFIRM_THRESHOLD:
        gate = "block"
    elif status == "incomplete" or clarity_score < POLICY_CLARITY_AUTO_THRESHOLD:
        gate = "confirm"
    else:
        gate = "auto"
    if gate == "auto" and (constraints_block_auto or manual_review_required):
        gate = "confirm"

    gate_reason = ""
    if gate == "block":
        if status == "failed":
            gate_reason = "parse_failed"
        else:
            gate_reason = "score_below_60"
    elif gate == "confirm":
        if status == "incomplete":
            gate_reason = "parse_incomplete"
        elif constraints_block_auto:
            if "constraints_conflict" in issue_codes or constraint_conflicts:
                gate_reason = "constraints_conflict"
            elif "constraints_evidence_missing" in issue_codes or missing_evidence_count > 0:
                gate_reason = "constraints_evidence_missing"
            else:
                gate_reason = "constraints_missing"
        elif manual_review_required:
            gate_reason = "score_evidence_insufficient"
        else:
            gate_reason = "score_60_79"

    risk_tips: list[str] = []
    if status == "incomplete":
        risk_tips.append("策略提取不完整，存在职责漂移风险。")
    if status == "failed":
        risk_tips.append("策略提取失败，无法保证会话与训练一致约束。")
    if gate != "auto":
        risk_tips.append("清晰度不足或证据不充分，建议人工确认后再执行任务。")
    for key, label in POLICY_SCORE_DIMENSION_META:
        dim = score_dimensions.get(key) or {}
        reason_text = str(dim.get("deduction_reason") or "").strip()
        if not reason_text:
            continue
        if dim.get("status") == "low":
            risk_tips.append(f"{label}偏低：{reason_text}")
        elif dim.get("status") == "manual_review":
            risk_tips.append(f"{label}待人工确认：{reason_text}")
    for item in constraint_issues:
        message = str((item or {}).get("message") or "").strip()
        if message and message not in risk_tips:
            risk_tips.append(message)
    for conflict_text in constraint_conflicts:
        if conflict_text and conflict_text not in risk_tips:
            risk_tips.append(conflict_text)
    for code in warnings:
        text = policy_warning_text(code)
        if text and text not in risk_tips:
            risk_tips.append(text)

    completeness = int((score_dimensions.get("completeness") or {}).get("score") or 0)
    executability = int((score_dimensions.get("executability") or {}).get("score") or 0)
    consistency = int((score_dimensions.get("consistency") or {}).get("score") or 0)
    traceability = int((score_dimensions.get("traceability") or {}).get("score") or 0)
    risk_coverage = int((score_dimensions.get("risk_coverage") or {}).get("score") or 0)
    operability = int((score_dimensions.get("operability") or {}).get("score") or 0)

    return {
        "score_model": POLICY_SCORE_MODEL,
        "score_total": clarity_score,
        "score_weights": dict(POLICY_SCORE_WEIGHTS),
        "score_dimensions": score_dimensions,
        "clarity_score": clarity_score,
        "clarity_details": {
            # 兼容旧字段
            "completeness": completeness,
            "specificity": int(round((executability + operability) / 2.0)),
            "consistency": consistency,
            "traceability": traceability,
            # 新增字段
            "executability": executability,
            "risk_coverage": risk_coverage,
            "operability": operability,
        },
        "clarity_gate": gate,
        "clarity_gate_reason": gate_reason,
        "risk_tips": risk_tips,
    }


def extract_agent_policy_fields(
    markdown_text: str,
    *,
    max_chars: int = 2400,
) -> dict[str, Any]:
    text = str(markdown_text or "")
    sections = parse_markdown_sections(text)
    if not text.strip():
        clarity = compute_policy_clarity(
            role_profile="",
            session_goal="",
            duty_constraints=[],
            parse_status="failed",
            parse_warnings=["agents_md_empty"],
            evidence_snippets={"role": "", "goal": "", "duty": ""},
        )
        return {
            "role_profile": "",
            "session_goal": "",
            "duty_constraints": [],
            "duty_constraints_text": "",
            "parse_status": "failed",
            "parse_warnings": ["agents_md_empty"],
            "evidence_snippets": {"role": "", "goal": "", "duty": ""},
            **clarity,
        }

    warnings: list[str] = []
    role_section = find_first_section_by_headings(sections, _AGENT_ROLE_HEADINGS)
    goal_section = find_first_section_by_headings(sections, _AGENT_GOAL_HEADINGS)
    duty_sections = find_sections_by_headings(sections, _AGENT_DUTY_HEADINGS, limit=3)

    role_profile = ""
    if role_section:
        role_profile = summarize_section_content(
            role_section[2],
            max_chars=min(max_chars, 720),
            max_lines=4,
        )
    else:
        warnings.append("missing_role_section")

    session_goal = ""
    if goal_section:
        session_goal = summarize_section_content(
            goal_section[2],
            max_chars=min(max_chars, 520),
            max_lines=3,
        )
    else:
        warnings.append("missing_goal_section")
        if role_profile:
            inferred = first_non_empty_sentence(role_profile, max_chars=120)
            if inferred:
                session_goal = f"围绕角色定位提供需求分析与澄清能力：{inferred}"
                warnings.append("goal_inferred_from_role_profile")

    duty_items: list[str] = []
    if duty_sections:
        merged_blocks = []
        for section in duty_sections:
            merged_blocks.append(section[2])
        duty_items = extract_list_items_from_text(
            "\n".join(merged_blocks),
            max_items=12,
        )
        if not duty_items:
            warnings.append("empty_duty_constraints")
    else:
        warnings.append("missing_duty_section")

    duty_items = [policy_text_compact(item, max_chars=280) for item in duty_items if str(item or "").strip()]
    duty_text = policy_text_compact("\n".join(duty_items), max_chars=max_chars) if duty_items else ""

    has_required = bool(role_profile and session_goal and duty_items)
    if has_required:
        structural_missing = any(
            code in warnings for code in ("missing_role_section", "missing_goal_section", "missing_duty_section")
        )
        parse_status = "incomplete" if structural_missing else "ok"
    else:
        parse_status = "failed" if not (role_profile or session_goal or duty_items) else "incomplete"
        if "missing_required_policy_fields" not in warnings:
            warnings.append("missing_required_policy_fields")

    duty_evidence_parts: list[str] = []
    for section in duty_sections:
        snippet = section_evidence_snippet(section)
        if snippet:
            duty_evidence_parts.append(snippet)
    evidence_snippets = {
        "role": section_evidence_snippet(role_section),
        "goal": section_evidence_snippet(goal_section),
        "duty": policy_text_compact("\n\n".join(duty_evidence_parts), max_chars=680) if duty_evidence_parts else "",
    }
    constraints = extract_constraints_from_policy(
        sections=sections,
        duty_items=duty_items,
    )
    for issue in (constraints.get("issues") or []):
        code = str((issue or {}).get("code") or "").strip()
        if code and code not in warnings:
            warnings.append(code)
    clarity = compute_policy_clarity(
        role_profile=role_profile,
        session_goal=session_goal,
        duty_constraints=duty_items,
        parse_status=parse_status,
        parse_warnings=warnings,
        evidence_snippets=evidence_snippets,
        constraints=constraints,
    )

    return {
        "role_profile": role_profile,
        "session_goal": session_goal,
        "duty_constraints": duty_items,
        "duty_constraints_text": duty_text,
        "constraints": constraints,
        "parse_status": parse_status,
        "parse_warnings": warnings,
        "evidence_snippets": evidence_snippets,
        **clarity,
    }


def extract_agent_duty_info(
    markdown_text: str,
    *,
    max_sections: int = 2,
    max_chars: int = 2400,
) -> tuple[str, str, str, bool]:
    text = str(markdown_text or "")
    if not text.strip():
        return "", "", "", False

    sections = parse_markdown_sections(text)

    selected_indexes: list[int] = []
    for keyword in _AGENT_DUTY_KEYWORDS:
        for idx, (title, _level, content) in enumerate(sections):
            if not content:
                continue
            if keyword in title and idx not in selected_indexes:
                selected_indexes.append(idx)
    if not selected_indexes:
        for idx, (_title, _level, content) in enumerate(sections):
            if content:
                selected_indexes.append(idx)
                break

    picked = [sections[idx] for idx in selected_indexes[:max_sections] if idx < len(sections)]
    if not picked:
        fallback = re.sub(r"^\s*#\s*", "", text.strip(), count=1)
        collapsed = re.sub(r"\s+", " ", fallback).strip()
        excerpt = collapsed[:96] + ("..." if len(collapsed) > 96 else "")
        if len(fallback) > max_chars:
            return "AGENTS 摘要", excerpt, fallback[:max_chars].rstrip() + "\n...(已截断)", True
        return "AGENTS 摘要", excerpt, fallback, False

    title = " / ".join([item[0] for item in picked]).strip()
    blocks = []
    for sec_title, _sec_level, content in picked:
        blocks.append(sec_title + "\n" + content)
    full = "\n\n".join(blocks).strip()
    truncated = False
    if len(full) > max_chars:
        full = full[:max_chars].rstrip() + "\n...(已截断)"
        truncated = True
    collapsed = re.sub(r"\s+", " ", full).strip()
    excerpt = collapsed[:120] + ("..." if len(collapsed) > 120 else "")
    return title, excerpt, full, truncated


def build_agent_policy_payload_via_codex(
    *,
    runtime_root: Path,
    workspace_root: Path,
    agent_name: str,
    agents_file: Path,
    agents_hash: str,
    agents_version: str,
) -> dict[str, Any]:
    # Avoid importing from policy_analysis facade, which re-exports runtime symbols
    # and can recurse back into this function.
    from ..services.policy_fallback_service import (
        build_agent_policy_payload_via_codex as _build_agent_policy_payload_via_codex,
    )

    return _build_agent_policy_payload_via_codex(
        runtime_root=runtime_root,
        workspace_root=workspace_root,
        agent_name=agent_name,
        agents_file=agents_file,
        agents_hash=agents_hash,
        agents_version=agents_version,
    )
