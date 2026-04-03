from __future__ import annotations

import re
from typing import Any

_STRONG_TERMS = (
    "bug",
    "异常",
    "报错",
    "失败",
    "无法",
    "崩溃",
    "卡死",
    "空白",
    "白屏",
    "黑屏",
    "404",
    "500",
    "回退",
    "丢失",
    "不生效",
)

_WEAK_TERMS = (
    "显示",
    "错位",
    "慢",
    "超时",
    "刷新",
    "关闭",
    "升级",
    "路径",
    "进度条",
)

_DEMAND_TERMS = (
    "需求",
    "建议",
    "优化",
    "新增",
    "希望",
    "想要",
)

_ISSUE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("wrong_or_mismatch", re.compile(r"(错了|错误|不对|不一致|有问题)")),
    ("missing_or_lost", re.compile(r"(没了|少了|缺了|缺失|缺少|丢了|不见了|消失)")),
    ("layout_or_repeat", re.compile(r"(重复|多了|多出|串了|乱了|遮挡|重叠|错位)")),
    ("cannot_operate", re.compile(r"(打不开|打开不了|进不去|点不了|没反应|无响应|无法点击|不能点击|不可点击|无法继续|无法使用|不能用|用不了)")),
    ("render_or_effect", re.compile(r"(不显示|不刷新|不更新|不生效)")),
)


def _find_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    return [token for token in terms if token and token in text]


def _find_issue_patterns(text: str) -> list[str]:
    return [label for label, pattern in _ISSUE_PATTERNS if pattern.search(text)]


def prejudge_defect_report(
    defect_summary: Any,
    report_text: Any,
    images: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    summary_text = str(defect_summary or "").strip()
    body_text = str(report_text or "").strip()
    combined_text = "\n".join(part for part in (summary_text, body_text) if part).strip()
    lowered = combined_text.lower()
    image_count = len(images or [])

    strong_hits = _find_terms(lowered, _STRONG_TERMS)
    weak_hits = _find_terms(lowered, _WEAK_TERMS)
    demand_hits = _find_terms(lowered, _DEMAND_TERMS)
    issue_hits = _find_issue_patterns(combined_text)

    has_defect_signal = bool(strong_hits or issue_hits)
    has_weak_defect_signal = bool(weak_hits) and not bool(demand_hits)
    has_evidence_only_signal = bool(image_count and combined_text and not demand_hits)
    is_defect = has_defect_signal or has_weak_defect_signal or has_evidence_only_signal

    matched_rules = strong_hits + issue_hits + weak_hits + demand_hits
    if is_defect:
        summary = (
            "命中异常、错误、缺失或不可操作类线索；即使描述较短，也先按真实缺陷进入闭环。"
        )
    else:
        summary = "更像需求或优化建议，当前分析未识别为缺陷。"

    confidence = "medium"
    if strong_hits or issue_hits:
        confidence = "high"
    elif weak_hits or image_count:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "decision_source": "fallback_rule",
        "decision": "defect" if is_defect else "not_defect",
        "title": "构成 workflow 缺陷" if is_defect else "当前不构成 workflow 缺陷",
        "summary": summary,
        "matched_rules": matched_rules,
        "confidence": confidence,
        "scored_images": image_count,
    }
