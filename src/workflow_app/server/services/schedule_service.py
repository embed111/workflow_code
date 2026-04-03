from __future__ import annotations

import calendar
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..infra.db.connection import connect_db
from . import assignment_service


def bind_runtime_symbols(symbols: dict[str, object]) -> None:
    if not isinstance(symbols, dict):
        return
    target = globals()
    module_name = str(target.get("__name__") or "")
    for key, value in symbols.items():
        if str(key).startswith("__"):
            continue
        current = target.get(key)
        if callable(current) and getattr(current, "__module__", "") == module_name:
            continue
        target[key] = value


class ScheduleCenterError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        message: str,
        code: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = int(status_code)
        self.code = str(code or "schedule_error")
        self.extra = dict(extra or {})


try:
    BEIJING_TZ = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:
    BEIJING_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")
SCHEDULE_TIMEZONE = "Asia/Shanghai"
SCHEDULE_PRIORITY_LEVELS = ("P0", "P1", "P2", "P3")
SCHEDULE_PRIORITY_VALUE = {name: idx for idx, name in enumerate(SCHEDULE_PRIORITY_LEVELS)}
SCHEDULE_PRIORITY_LABEL = {idx: name for idx, name in enumerate(SCHEDULE_PRIORITY_LEVELS)}
SCHEDULE_WEEKDAY_TEXT = {
    1: "周一",
    2: "周二",
    3: "周三",
    4: "周四",
    5: "周五",
    6: "周六",
    7: "周日",
}
SCHEDULE_RESULT_TEXT = {
    "pending": "待触发",
    "queued": "已建单待调度",
    "running": "运行中",
    "succeeded": "已成功",
    "failed": "已失败",
}
SCHEDULE_EVENT_LOG = Path("logs") / "events" / "schedules.jsonl"
SCHEDULE_ASSIGNMENT_SOURCE_WORKFLOW = "workflow-ui"
SCHEDULE_ASSIGNMENT_GRAPH_NAME = "任务中心全局主图"
SCHEDULE_ASSIGNMENT_GRAPH_REQUEST_ID = "workflow-ui-global-graph-v1"
SCHEDULE_WORKER_INTERVAL_SECONDS = 8
_SCHEDULE_WORKER_THREADS: dict[str, threading.Thread] = {}
_SCHEDULE_WORKER_LOCK = threading.Lock()


def _now_bj() -> datetime:
    return datetime.now().astimezone(BEIJING_TZ)


def _now_text() -> str:
    return _now_bj().isoformat(timespec="seconds")


def _minute_floor(dt: datetime) -> datetime:
    current = dt.astimezone(BEIJING_TZ)
    return current.replace(second=0, microsecond=0)


def _iso_minute(dt: datetime) -> str:
    return _minute_floor(dt).isoformat(timespec="seconds")


def _date_key() -> str:
    return _now_bj().strftime("%Y%m%d")


def _schedule_id() -> str:
    return f"sch-{_date_key()}-{uuid.uuid4().hex[:8]}"


def _schedule_trigger_id() -> str:
    return f"sti-{_date_key()}-{uuid.uuid4().hex[:8]}"


def _schedule_audit_id() -> str:
    return f"saud-{_date_key()}-{uuid.uuid4().hex[:8]}"


def _safe_token(value: Any, *, max_len: int = 160) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    out = []
    for ch in text[:max_len]:
        if ch.isalnum() or ch in {"-", "_", ".", ":"}:
            out.append(ch)
    return "".join(out)


def _json_dumps(value: Any, fallback: str) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return fallback


def _json_loads_dict(raw: Any) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _json_loads_list(raw: Any) -> list[Any]:
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except Exception:
        return []
    return payload if isinstance(payload, list) else []


def _normalize_text(
    value: Any,
    *,
    field: str,
    required: bool = False,
    max_len: int = 4000,
) -> str:
    text = str(value or "").strip()
    if not text:
        if required:
            raise ScheduleCenterError(400, f"{field} required", f"{field}_required")
        return ""
    if len(text) > max_len:
        raise ScheduleCenterError(400, f"{field} too long", f"{field}_too_long", {"max_len": max_len})
    return text


def _normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_priority(value: Any) -> tuple[str, int]:
    text = str(value or "P1").strip().upper()
    if text not in SCHEDULE_PRIORITY_VALUE:
        raise ScheduleCenterError(400, "priority invalid", "schedule_priority_invalid", {"allowed": list(SCHEDULE_PRIORITY_LEVELS)})
    return text, int(SCHEDULE_PRIORITY_VALUE[text])


def _priority_label(value: Any) -> str:
    try:
        number = int(value)
    except Exception:
        return "P1"
    return SCHEDULE_PRIORITY_LABEL.get(number, "P1")


def _normalize_delivery_mode(value: Any) -> str:
    text = str(value or "none").strip().lower() or "none"
    if text not in {"none", "specified"}:
        raise ScheduleCenterError(400, "delivery_mode invalid", "schedule_delivery_mode_invalid")
    return text


def _ensure_schedule_tables(root: Path) -> None:
    conn = connect_db(root)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schedule_plans (
                schedule_id TEXT PRIMARY KEY,
                schedule_name TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 0,
                assigned_agent_id TEXT NOT NULL DEFAULT '',
                assigned_agent_name TEXT NOT NULL DEFAULT '',
                launch_summary TEXT NOT NULL DEFAULT '',
                execution_checklist TEXT NOT NULL DEFAULT '',
                done_definition TEXT NOT NULL DEFAULT '',
                priority INTEGER NOT NULL DEFAULT 1,
                expected_artifact TEXT NOT NULL DEFAULT '',
                delivery_mode TEXT NOT NULL DEFAULT 'none',
                delivery_receiver_agent_id TEXT NOT NULL DEFAULT '',
                delivery_receiver_agent_name TEXT NOT NULL DEFAULT '',
                rule_sets_json TEXT NOT NULL DEFAULT '[]',
                timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
                next_trigger_at TEXT NOT NULL DEFAULT '',
                last_trigger_at TEXT NOT NULL DEFAULT '',
                last_result_status TEXT NOT NULL DEFAULT 'pending',
                last_result_ticket_id TEXT NOT NULL DEFAULT '',
                last_result_node_id TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL DEFAULT '',
                updated_by TEXT NOT NULL DEFAULT '',
                deleted_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_schedule_plans_updated ON schedule_plans(deleted_at,updated_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_schedule_plans_enabled ON schedule_plans(deleted_at,enabled,next_trigger_at)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schedule_trigger_instances (
                trigger_instance_id TEXT PRIMARY KEY,
                schedule_id TEXT NOT NULL,
                planned_trigger_at TEXT NOT NULL,
                trigger_rule_summary TEXT NOT NULL DEFAULT '',
                trigger_rule_keys_json TEXT NOT NULL DEFAULT '[]',
                merged_rule_count INTEGER NOT NULL DEFAULT 0,
                trigger_status TEXT NOT NULL DEFAULT '',
                trigger_message TEXT NOT NULL DEFAULT '',
                assignment_ticket_id TEXT NOT NULL DEFAULT '',
                assignment_node_id TEXT NOT NULL DEFAULT '',
                schedule_name_snapshot TEXT NOT NULL DEFAULT '',
                assigned_agent_id_snapshot TEXT NOT NULL DEFAULT '',
                launch_summary_snapshot TEXT NOT NULL DEFAULT '',
                execution_checklist_snapshot TEXT NOT NULL DEFAULT '',
                done_definition_snapshot TEXT NOT NULL DEFAULT '',
                expected_artifact_snapshot TEXT NOT NULL DEFAULT '',
                delivery_mode_snapshot TEXT NOT NULL DEFAULT 'none',
                delivery_receiver_agent_id_snapshot TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_schedule_trigger_unique ON schedule_trigger_instances(schedule_id,planned_trigger_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_schedule_trigger_plan_time ON schedule_trigger_instances(schedule_id,planned_trigger_at DESC)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schedule_audit_log (
                audit_id TEXT PRIMARY KEY,
                schedule_id TEXT NOT NULL DEFAULT '',
                trigger_instance_id TEXT NOT NULL DEFAULT '',
                action TEXT NOT NULL,
                operator TEXT NOT NULL DEFAULT '',
                detail_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_schedule_audit_plan_time ON schedule_audit_log(schedule_id,created_at DESC)")
        conn.commit()
    finally:
        conn.close()


def _append_schedule_event(root: Path, payload: dict[str, Any]) -> None:
    try:
        path = (root / SCHEDULE_EVENT_LOG).resolve(strict=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        return


def _append_schedule_audit(
    conn: sqlite3.Connection,
    *,
    schedule_id: str,
    trigger_instance_id: str = "",
    action: str,
    operator: str,
    detail: dict[str, Any] | None = None,
    created_at: str,
) -> str:
    audit_id = _schedule_audit_id()
    conn.execute(
        """
        INSERT INTO schedule_audit_log(audit_id,schedule_id,trigger_instance_id,action,operator,detail_json,created_at)
        VALUES (?,?,?,?,?,?,?)
        """,
        (
            audit_id,
            str(schedule_id or "").strip(),
            str(trigger_instance_id or "").strip(),
            str(action or "").strip(),
            str(operator or "").strip(),
            _json_dumps(detail or {}, "{}"),
            created_at,
        ),
    )
    return audit_id


def _load_available_agents(cfg: Any) -> list[dict[str, str]]:
    items: list[dict[str, Any]] = []
    fn = globals().get("list_available_agents")
    if callable(fn):
        try:
            items = fn(cfg, analyze_policy=False)
        except TypeError:
            try:
                items = fn(cfg)
            except Exception:
                items = []
        except Exception:
            items = []
    rows: list[dict[str, str]] = []
    for item in items:
        name = str(item.get("agent_name") or item.get("agent_id") or "").strip()
        agent_id = _safe_token(item.get("agent_id") or name, max_len=120)
        if name and agent_id:
            rows.append({"agent_id": agent_id, "agent_name": name})
    if rows:
        return rows
    conn = connect_db(Path(cfg.root))
    try:
        db_rows = conn.execute(
            """
            SELECT agent_id,agent_name,runtime_status
            FROM agent_registry
            WHERE COALESCE(runtime_status,'idle')<>'creating'
            ORDER BY updated_at DESC, agent_name ASC
            """
        ).fetchall()
        for row in db_rows:
            name = str(row["agent_name"] or row["agent_id"] or "").strip()
            agent_id = _safe_token(row["agent_id"] or name, max_len=120)
            if name and agent_id:
                rows.append({"agent_id": agent_id, "agent_name": name})
        return rows
    finally:
        conn.close()


def _resolve_agent(cfg: Any, raw: Any, *, allow_empty: bool = False) -> dict[str, str]:
    requested = str(raw or "").strip()
    if not requested:
        if allow_empty:
            return {"agent_id": "", "agent_name": ""}
        raise ScheduleCenterError(400, "assigned_agent_id required", "schedule_assigned_agent_required")
    token = _safe_token(requested, max_len=120)
    for item in _load_available_agents(cfg):
        if requested == item["agent_name"] or token == item["agent_id"]:
            return dict(item)
    raise ScheduleCenterError(
        400,
        "assigned_agent_id not found in agent pool",
        "schedule_assigned_agent_not_found",
        {"assigned_agent_id": requested},
    )


def _split_tokens(raw: Any) -> list[str]:
    if isinstance(raw, list):
        values = [str(item or "").strip() for item in raw]
    else:
        text = str(raw or "").replace("，", ",").replace("\r", "\n")
        values = []
        for chunk in text.split("\n"):
            values.extend(part.strip() for part in chunk.split(","))
    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _normalize_times(raw: Any, *, field: str) -> list[str]:
    out: list[str] = []
    for token in _split_tokens(raw):
        parts = token.split(":")
        if len(parts) != 2:
            raise ScheduleCenterError(400, f"{field} invalid", f"{field}_invalid", {"value": token})
        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except Exception as exc:
            raise ScheduleCenterError(400, f"{field} invalid", f"{field}_invalid", {"value": token}) from exc
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ScheduleCenterError(400, f"{field} invalid", f"{field}_invalid", {"value": token})
        text = f"{hour:02d}:{minute:02d}"
        if text not in out:
            out.append(text)
    return sorted(out)


def _normalize_int_list(raw: Any, *, field: str, minimum: int, maximum: int) -> list[int]:
    out: list[int] = []
    for token in _split_tokens(raw):
        try:
            value = int(token)
        except Exception as exc:
            raise ScheduleCenterError(400, f"{field} invalid", f"{field}_invalid", {"value": token}) from exc
        if value < minimum or value > maximum:
            raise ScheduleCenterError(
                400,
                f"{field} invalid",
                f"{field}_invalid",
                {"value": value, "minimum": minimum, "maximum": maximum},
            )
        if value not in out:
            out.append(value)
    return sorted(out)


def _parse_datetime_token(token: str, *, field: str) -> datetime:
    text = str(token or "").strip()
    if not text:
        raise ScheduleCenterError(400, f"{field} invalid", f"{field}_invalid")
    normalized = text.replace("/", "-").replace(" ", "T")
    try:
        dt = datetime.fromisoformat(normalized)
    except Exception as exc:
        raise ScheduleCenterError(400, f"{field} invalid", f"{field}_invalid", {"value": text}) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BEIJING_TZ)
    return _minute_floor(dt.astimezone(BEIJING_TZ))


def _normalize_once_values(raw: Any, *, field: str) -> list[str]:
    out: list[str] = []
    for token in _split_tokens(raw):
        text = _iso_minute(_parse_datetime_token(token, field=field))
        if text not in out:
            out.append(text)
    return sorted(out)


def _normalize_rule_sets(raw: Any) -> list[dict[str, Any]]:
    payload = raw if isinstance(raw, dict) else {}
    rules: list[dict[str, Any]] = []

    monthly = payload.get("monthly") if isinstance(payload.get("monthly"), dict) else {}
    if _normalize_bool(monthly.get("enabled")) or monthly.get("days") or monthly.get("days_text") or monthly.get("times") or monthly.get("times_text"):
        days = _normalize_int_list(monthly.get("days") if monthly.get("days") is not None else monthly.get("days_text"), field="monthly_days", minimum=1, maximum=31)
        times = _normalize_times(monthly.get("times") if monthly.get("times") is not None else monthly.get("times_text"), field="monthly_times")
        if not days or not times:
            raise ScheduleCenterError(400, "monthly rule incomplete", "schedule_monthly_rule_incomplete")
        rules.append({"rule_type": "monthly", "days": days, "times": times})

    weekly = payload.get("weekly") if isinstance(payload.get("weekly"), dict) else {}
    if _normalize_bool(weekly.get("enabled")) or weekly.get("weekdays") or weekly.get("times") or weekly.get("times_text"):
        weekdays = _normalize_int_list(weekly.get("weekdays"), field="weekly_weekdays", minimum=1, maximum=7)
        times = _normalize_times(weekly.get("times") if weekly.get("times") is not None else weekly.get("times_text"), field="weekly_times")
        if not weekdays or not times:
            raise ScheduleCenterError(400, "weekly rule incomplete", "schedule_weekly_rule_incomplete")
        rules.append({"rule_type": "weekly", "weekdays": weekdays, "times": times})

    daily = payload.get("daily") if isinstance(payload.get("daily"), dict) else {}
    if _normalize_bool(daily.get("enabled")) or daily.get("times") or daily.get("times_text"):
        times = _normalize_times(daily.get("times") if daily.get("times") is not None else daily.get("times_text"), field="daily_times")
        if not times:
            raise ScheduleCenterError(400, "daily rule incomplete", "schedule_daily_rule_incomplete")
        rules.append({"rule_type": "daily", "times": times})

    once = payload.get("once") if isinstance(payload.get("once"), dict) else {}
    if _normalize_bool(once.get("enabled")) or once.get("date_times") or once.get("date_times_text"):
        date_times = _normalize_once_values(
            once.get("date_times") if once.get("date_times") is not None else once.get("date_times_text"),
            field="once_date_times",
        )
        if not date_times:
            raise ScheduleCenterError(400, "once rule incomplete", "schedule_once_rule_incomplete")
        rules.append({"rule_type": "once", "date_times": date_times})

    return rules


def _rule_key(rule: dict[str, Any]) -> str:
    rule_type = str(rule.get("rule_type") or "").strip().lower()
    if rule_type == "monthly":
        return f"monthly:{','.join(str(int(item)) for item in list(rule.get('days') or []))}:{','.join(list(rule.get('times') or []))}"
    if rule_type == "weekly":
        return f"weekly:{','.join(str(int(item)) for item in list(rule.get('weekdays') or []))}:{','.join(list(rule.get('times') or []))}"
    if rule_type == "daily":
        return f"daily:{','.join(list(rule.get('times') or []))}"
    return f"once:{','.join(list(rule.get('date_times') or []))}"


def _rule_text(rule: dict[str, Any]) -> str:
    rule_type = str(rule.get("rule_type") or "").strip().lower()
    if rule_type == "monthly":
        days = " / ".join(str(int(item)) for item in list(rule.get("days") or []))
        times = " / ".join(list(rule.get("times") or []))
        return f"每月 {days} 号 {times}"
    if rule_type == "weekly":
        days = " / ".join(SCHEDULE_WEEKDAY_TEXT.get(int(item), str(item)) for item in list(rule.get("weekdays") or []))
        times = " / ".join(list(rule.get("times") or []))
        return f"每周 {days} {times}"
    if rule_type == "daily":
        return "每日 " + " / ".join(list(rule.get("times") or []))
    values = []
    for item in list(rule.get("date_times") or []):
        try:
            values.append(_parse_datetime_token(item, field="once_date_times").strftime("%Y-%m-%d %H:%M"))
        except Exception:
            values.append(str(item))
    return "定时 " + " / ".join(values)


def _editor_rule_inputs(rule_sets: list[dict[str, Any]]) -> dict[str, Any]:
    out = {
        "monthly": {"enabled": False, "days_text": "", "times_text": ""},
        "weekly": {"enabled": False, "weekdays": [], "times_text": ""},
        "daily": {"enabled": False, "times_text": ""},
        "once": {"enabled": False, "date_times_text": ""},
    }
    for rule in list(rule_sets or []):
        rule_type = str(rule.get("rule_type") or "").strip().lower()
        if rule_type == "monthly":
            out["monthly"] = {
                "enabled": True,
                "days_text": ",".join(str(int(item)) for item in list(rule.get("days") or [])),
                "times_text": ",".join(list(rule.get("times") or [])),
            }
        elif rule_type == "weekly":
            out["weekly"] = {
                "enabled": True,
                "weekdays": [int(item) for item in list(rule.get("weekdays") or [])],
                "times_text": ",".join(list(rule.get("times") or [])),
            }
        elif rule_type == "daily":
            out["daily"] = {"enabled": True, "times_text": ",".join(list(rule.get("times") or []))}
        elif rule_type == "once":
            values = []
            for item in list(rule.get("date_times") or []):
                try:
                    values.append(_parse_datetime_token(item, field="once_date_times").strftime("%Y-%m-%d %H:%M"))
                except Exception:
                    values.append(str(item))
            out["once"] = {"enabled": True, "date_times_text": "\n".join(values)}
    return out


def _iter_rule_candidates(rule: dict[str, Any], start_dt: datetime, end_dt: datetime) -> list[tuple[datetime, str, str]]:
    if end_dt < start_dt:
        return []
    start_dt = _minute_floor(start_dt)
    end_dt = _minute_floor(end_dt)
    rule_type = str(rule.get("rule_type") or "").strip().lower()
    out: list[tuple[datetime, str, str]] = []
    if rule_type == "monthly":
        cursor = datetime(start_dt.year, start_dt.month, 1, tzinfo=BEIJING_TZ)
        while cursor <= end_dt:
            day_limit = calendar.monthrange(cursor.year, cursor.month)[1]
            for day in list(rule.get("days") or []):
                if int(day) < 1 or int(day) > day_limit:
                    continue
                for time_text in list(rule.get("times") or []):
                    hour, minute = [int(part) for part in str(time_text).split(":", 1)]
                    current = datetime(cursor.year, cursor.month, int(day), hour, minute, tzinfo=BEIJING_TZ)
                    if start_dt <= current <= end_dt:
                        out.append((current, f"每月 {int(day)} 号 {time_text}", _rule_key(rule)))
            next_month = cursor.month + 1
            next_year = cursor.year + (1 if next_month > 12 else 0)
            cursor = datetime(next_year, 1 if next_month > 12 else next_month, 1, tzinfo=BEIJING_TZ)
    elif rule_type in {"weekly", "daily"}:
        current_date = start_dt.date()
        end_date = end_dt.date()
        weekdays = {int(item) for item in list(rule.get("weekdays") or [])}
        while current_date <= end_date:
            current_base = datetime(current_date.year, current_date.month, current_date.day, tzinfo=BEIJING_TZ)
            if rule_type == "weekly" and current_base.isoweekday() not in weekdays:
                current_date += timedelta(days=1)
                continue
            for time_text in list(rule.get("times") or []):
                hour, minute = [int(part) for part in str(time_text).split(":", 1)]
                current = current_base.replace(hour=hour, minute=minute)
                if start_dt <= current <= end_dt:
                    label = ("每周 " + SCHEDULE_WEEKDAY_TEXT.get(current.isoweekday(), str(current.isoweekday())) + " " + time_text) if rule_type == "weekly" else ("每日 " + time_text)
                    out.append((current, label, _rule_key(rule)))
            current_date += timedelta(days=1)
    elif rule_type == "once":
        for item in list(rule.get("date_times") or []):
            current = _parse_datetime_token(item, field="once_date_times")
            if start_dt <= current <= end_dt:
                out.append((current, "定时 " + current.strftime("%Y-%m-%d %H:%M"), _rule_key(rule)))
    return out


def _merge_candidates(candidates: list[tuple[datetime, str, str]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for current, label, rule_key in candidates:
        key = _iso_minute(current)
        bucket = merged.setdefault(
            key,
            {
                "planned_trigger_at": key,
                "rule_labels": [],
                "rule_keys": [],
            },
        )
        if label not in bucket["rule_labels"]:
            bucket["rule_labels"].append(label)
        if rule_key not in bucket["rule_keys"]:
            bucket["rule_keys"].append(rule_key)
    out = []
    for bucket in merged.values():
        out.append(
            {
                "planned_trigger_at": str(bucket["planned_trigger_at"]),
                "trigger_rule_summary": " + ".join(list(bucket["rule_labels"])),
                "trigger_rule_labels": list(bucket["rule_labels"]),
                "trigger_rule_keys": list(bucket["rule_keys"]),
                "merged_rule_count": len(list(bucket["rule_labels"])),
            }
        )
    out.sort(key=lambda item: str(item.get("planned_trigger_at") or ""))
    return out


def _future_triggers(rule_sets: list[dict[str, Any]], *, start_dt: datetime, limit: int = 8, horizon_days: int = 370) -> list[dict[str, Any]]:
    if not rule_sets:
        return []
    horizon_end = _minute_floor(start_dt) + timedelta(days=max(1, int(horizon_days)))
    merged = _merge_candidates(
        [
            item
            for rule in list(rule_sets or [])
            for item in _iter_rule_candidates(rule, start_dt, horizon_end)
        ]
    )
    return merged[: max(1, int(limit or 8))]


def _month_bounds(month_text: str | None) -> tuple[datetime, datetime, str]:
    current = _now_bj()
    raw = str(month_text or "").strip()
    if raw:
        parts = raw.split("-", 1)
        if len(parts) == 2:
            try:
                current = datetime(int(parts[0]), int(parts[1]), 1, tzinfo=BEIJING_TZ)
            except Exception:
                pass
    current = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    first_weekday = current.isoweekday()
    grid_start = current - timedelta(days=first_weekday - 1)
    day_limit = calendar.monthrange(current.year, current.month)[1]
    month_end = current.replace(day=day_limit, hour=23, minute=59, second=0, microsecond=0)
    grid_end = month_end + timedelta(days=(7 - month_end.isoweekday()))
    return grid_start, grid_end, current.strftime("%Y-%m")


def _row_to_schedule(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    item = dict(row or {})
    rule_sets = _json_loads_list(item.get("rule_sets_json"))
    return {
        "schedule_id": str(item.get("schedule_id") or "").strip(),
        "schedule_name": str(item.get("schedule_name") or "").strip(),
        "enabled": bool(item.get("enabled")),
        "assigned_agent_id": str(item.get("assigned_agent_id") or "").strip(),
        "assigned_agent_name": str(item.get("assigned_agent_name") or item.get("assigned_agent_id") or "").strip(),
        "launch_summary": str(item.get("launch_summary") or "").strip(),
        "execution_checklist": str(item.get("execution_checklist") or "").strip(),
        "done_definition": str(item.get("done_definition") or "").strip(),
        "priority": _priority_label(item.get("priority")),
        "priority_value": int(item.get("priority") or 1),
        "expected_artifact": str(item.get("expected_artifact") or "").strip(),
        "delivery_mode": str(item.get("delivery_mode") or "none").strip().lower() or "none",
        "delivery_receiver_agent_id": str(item.get("delivery_receiver_agent_id") or "").strip(),
        "delivery_receiver_agent_name": str(item.get("delivery_receiver_agent_name") or "").strip(),
        "rule_sets": rule_sets,
        "rule_labels": [_rule_text(rule) for rule in rule_sets],
        "editor_rule_inputs": _editor_rule_inputs(rule_sets),
        "timezone": str(item.get("timezone") or SCHEDULE_TIMEZONE).strip() or SCHEDULE_TIMEZONE,
        "next_trigger_at": str(item.get("next_trigger_at") or "").strip(),
        "last_trigger_at": str(item.get("last_trigger_at") or "").strip(),
        "last_result_status": str(item.get("last_result_status") or "pending").strip().lower() or "pending",
        "last_result_status_text": SCHEDULE_RESULT_TEXT.get(str(item.get("last_result_status") or "pending").strip().lower(), "待触发"),
        "last_result_ticket_id": str(item.get("last_result_ticket_id") or "").strip(),
        "last_result_node_id": str(item.get("last_result_node_id") or "").strip(),
        "created_at": str(item.get("created_at") or "").strip(),
        "updated_at": str(item.get("updated_at") or "").strip(),
        "deleted_at": str(item.get("deleted_at") or "").strip(),
    }


def _row_to_trigger(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    item = dict(row or {})
    return {
        "trigger_instance_id": str(item.get("trigger_instance_id") or "").strip(),
        "schedule_id": str(item.get("schedule_id") or "").strip(),
        "planned_trigger_at": str(item.get("planned_trigger_at") or "").strip(),
        "trigger_rule_summary": str(item.get("trigger_rule_summary") or "").strip(),
        "trigger_rule_keys": _json_loads_list(item.get("trigger_rule_keys_json")),
        "merged_rule_count": int(item.get("merged_rule_count") or 0),
        "trigger_status": str(item.get("trigger_status") or "").strip().lower(),
        "trigger_message": str(item.get("trigger_message") or "").strip(),
        "assignment_ticket_id": str(item.get("assignment_ticket_id") or "").strip(),
        "assignment_node_id": str(item.get("assignment_node_id") or "").strip(),
        "schedule_name_snapshot": str(item.get("schedule_name_snapshot") or "").strip(),
        "assigned_agent_id_snapshot": str(item.get("assigned_agent_id_snapshot") or "").strip(),
        "launch_summary_snapshot": str(item.get("launch_summary_snapshot") or "").strip(),
        "execution_checklist_snapshot": str(item.get("execution_checklist_snapshot") or "").strip(),
        "done_definition_snapshot": str(item.get("done_definition_snapshot") or "").strip(),
        "expected_artifact_snapshot": str(item.get("expected_artifact_snapshot") or "").strip(),
        "delivery_mode_snapshot": str(item.get("delivery_mode_snapshot") or "none").strip().lower() or "none",
        "delivery_receiver_agent_id_snapshot": str(item.get("delivery_receiver_agent_id_snapshot") or "").strip(),
        "created_at": str(item.get("created_at") or "").strip(),
        "updated_at": str(item.get("updated_at") or "").strip(),
        "result_status": "pending",
        "result_status_text": SCHEDULE_RESULT_TEXT["pending"],
        "assignment_status": "",
        "assignment_status_text": "",
        "assignment_graph_name": "",
        "assignment_node_name": "",
    }


def _load_plan_row(conn: sqlite3.Connection, schedule_id: str, *, allow_deleted: bool = False) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM schedule_plans WHERE schedule_id=? LIMIT 1", (schedule_id,)).fetchone()
    if row is None or ((not allow_deleted) and str(row["deleted_at"] or "").strip()):
        raise ScheduleCenterError(404, "schedule not found", "schedule_not_found")
    return row


def _assignment_runtime_status(root: Path, *, ticket_id: str, node_id: str) -> dict[str, str]:
    if not ticket_id or not node_id:
        return {}
    try:
        detail = assignment_service.get_assignment_status_detail(
            root,
            ticket_id,
            node_id_text=node_id,
            include_test_data=True,
        )
        selected = dict(detail.get("selected_node") or {})
        graph = dict(detail.get("graph") or {})
        node_status = str(selected.get("status") or "").strip().lower()
        if node_status == "running":
            result_status = "running"
        elif node_status == "succeeded":
            result_status = "succeeded"
        elif node_status == "failed":
            result_status = "failed"
        else:
            result_status = "queued"
        return {
            "assignment_status": node_status,
            "assignment_status_text": str(selected.get("status_text") or "").strip(),
            "assignment_graph_name": str(graph.get("graph_name") or "").strip(),
            "assignment_node_name": str(selected.get("node_name") or node_id).strip(),
            "result_status": result_status,
            "result_status_text": SCHEDULE_RESULT_TEXT.get(result_status, SCHEDULE_RESULT_TEXT["pending"]),
        }
    except Exception:
        return {"result_status": "queued", "result_status_text": SCHEDULE_RESULT_TEXT["queued"]}


def _enrich_trigger(root: Path, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    payload = _row_to_trigger(row)
    payload.update(_assignment_runtime_status(root, ticket_id=payload["assignment_ticket_id"], node_id=payload["assignment_node_id"]))
    if payload["trigger_status"] in {"create_failed", "dispatch_failed"} and payload.get("result_status") == "pending":
        payload["result_status"] = "failed"
        payload["result_status_text"] = SCHEDULE_RESULT_TEXT["failed"]
    return payload


def _schedule_trigger_projection(schedule: dict[str, Any]) -> dict[str, Any]:
    now_dt = _minute_floor(_now_bj())
    if not schedule.get("enabled"):
        return {"next_trigger_at": "", "next_trigger_text": "停用中"}
    next_items = _future_triggers(list(schedule.get("rule_sets") or []), start_dt=now_dt, limit=1)
    next_at = str(next_items[0]["planned_trigger_at"]) if next_items else ""
    return {"next_trigger_at": next_at, "next_trigger_text": next_at}


def list_schedules(root: Path) -> dict[str, Any]:
    _ensure_schedule_tables(root)
    conn = connect_db(root)
    try:
        rows = conn.execute(
            "SELECT * FROM schedule_plans WHERE deleted_at='' ORDER BY enabled DESC, updated_at DESC, created_at DESC"
        ).fetchall()
        latest_rows = {
            str(item["schedule_id"] or "").strip(): item
            for item in conn.execute(
                """
                SELECT t.*
                FROM schedule_trigger_instances t
                JOIN (
                    SELECT schedule_id, MAX(planned_trigger_at) AS latest_planned
                    FROM schedule_trigger_instances
                    GROUP BY schedule_id
                ) latest
                  ON latest.schedule_id=t.schedule_id AND latest.latest_planned=t.planned_trigger_at
                """
            ).fetchall()
        }
    finally:
        conn.close()
    items = []
    for row in rows:
        schedule = _row_to_schedule(row)
        schedule.update(_schedule_trigger_projection(schedule))
        latest = latest_rows.get(schedule["schedule_id"])
        enriched = _enrich_trigger(root, latest) if latest is not None else None
        if enriched:
            schedule["last_result_status"] = str(enriched.get("result_status") or "pending")
            schedule["last_result_status_text"] = str(enriched.get("result_status_text") or SCHEDULE_RESULT_TEXT["pending"])
            schedule["last_result_ticket_id"] = str(enriched.get("assignment_ticket_id") or "")
            schedule["last_result_node_id"] = str(enriched.get("assignment_node_id") or "")
            schedule["last_result_summary"] = str(enriched.get("trigger_message") or enriched.get("assignment_status_text") or "").strip()
        else:
            schedule["last_result_summary"] = ""
        items.append(schedule)
    return {"items": items, "total": len(items), "timezone": SCHEDULE_TIMEZONE}


def get_schedule_detail(root: Path, schedule_id: str) -> dict[str, Any]:
    _ensure_schedule_tables(root)
    schedule_key = _safe_token(schedule_id)
    if not schedule_key:
        raise ScheduleCenterError(400, "schedule_id required", "schedule_id_required")
    conn = connect_db(root)
    try:
        row = _load_plan_row(conn, schedule_key, allow_deleted=True)
        trigger_rows = conn.execute(
            """
            SELECT *
            FROM schedule_trigger_instances
            WHERE schedule_id=?
            ORDER BY planned_trigger_at DESC, created_at DESC
            LIMIT 20
            """,
            (schedule_key,),
        ).fetchall()
    finally:
        conn.close()
    schedule = _row_to_schedule(row)
    schedule.update(_schedule_trigger_projection(schedule))
    future = _future_triggers(list(schedule.get("rule_sets") or []), start_dt=_minute_floor(_now_bj()), limit=8)
    recent = [_enrich_trigger(root, item) for item in trigger_rows]
    return {
        "schedule": schedule,
        "future_triggers": future,
        "recent_triggers": recent[:5],
        "related_task_refs": [
            {
                "trigger_instance_id": item["trigger_instance_id"],
                "assignment_ticket_id": item["assignment_ticket_id"],
                "assignment_node_id": item["assignment_node_id"],
                "result_status": item["result_status"],
                "result_status_text": item["result_status_text"],
                "assignment_graph_name": item.get("assignment_graph_name") or "",
                "assignment_node_name": item.get("assignment_node_name") or "",
                "planned_trigger_at": item["planned_trigger_at"],
            }
            for item in recent
            if str(item.get("assignment_ticket_id") or "").strip() and str(item.get("assignment_node_id") or "").strip()
        ],
        "timezone": SCHEDULE_TIMEZONE,
    }


def get_schedule_calendar(root: Path, *, month: str = "") -> dict[str, Any]:
    _ensure_schedule_tables(root)
    start_dt, end_dt, month_key = _month_bounds(month)
    conn = connect_db(root)
    try:
        plan_rows = conn.execute(
            "SELECT * FROM schedule_plans WHERE deleted_at='' ORDER BY enabled DESC, updated_at DESC"
        ).fetchall()
        trigger_rows = conn.execute(
            """
            SELECT *
            FROM schedule_trigger_instances
            WHERE planned_trigger_at>=? AND planned_trigger_at<=?
            ORDER BY planned_trigger_at ASC, created_at ASC
            """,
            (_iso_minute(start_dt), _iso_minute(end_dt)),
        ).fetchall()
    finally:
        conn.close()
    plans_by_day: dict[str, list[dict[str, Any]]] = {}
    now_dt = _minute_floor(_now_bj())
    for row in plan_rows:
        schedule = _row_to_schedule(row)
        if not schedule.get("enabled"):
            continue
        merged = _merge_candidates(
            [
                item
                for rule in list(schedule.get("rule_sets") or [])
                for item in _iter_rule_candidates(rule, max(start_dt, now_dt), end_dt)
            ]
        )
        for item in merged:
            day_key = str(item["planned_trigger_at"])[:10]
            plans_by_day.setdefault(day_key, []).append(
                {
                    "schedule_id": schedule["schedule_id"],
                    "schedule_name": schedule["schedule_name"],
                    "planned_trigger_at": item["planned_trigger_at"],
                    "trigger_rule_summary": item["trigger_rule_summary"],
                    "merged_rule_count": int(item["merged_rule_count"] or 0),
                }
            )
    results_by_day: dict[str, list[dict[str, Any]]] = {}
    for row in trigger_rows:
        enriched = _enrich_trigger(root, row)
        results_by_day.setdefault(str(enriched["planned_trigger_at"])[:10], []).append(enriched)
    matrix: list[dict[str, Any]] = []
    cursor = start_dt
    today_key = now_dt.strftime("%Y-%m-%d")
    while cursor <= end_dt:
        day_key = cursor.strftime("%Y-%m-%d")
        matrix.append(
            {
                "date": day_key,
                "day": int(cursor.day),
                "is_current_month": cursor.strftime("%Y-%m") == month_key,
                "is_today": day_key == today_key,
                "plans": sorted(plans_by_day.get(day_key) or [], key=lambda item: str(item.get("planned_trigger_at") or "")),
                "results": sorted(results_by_day.get(day_key) or [], key=lambda item: str(item.get("planned_trigger_at") or "")),
            }
        )
        cursor += timedelta(days=1)
    selected_date = today_key if today_key.startswith(month_key) else month_key + "-01"
    month_dt = datetime.strptime(month_key + "-01", "%Y-%m-%d")
    return {
        "month": month_key,
        "month_title": f"{month_dt.year} 年 {month_dt.month} 月",
        "days": matrix,
        "timezone": SCHEDULE_TIMEZONE,
        "selected_date": selected_date,
    }


def _ensure_global_assignment_graph(cfg: Any) -> str:
    created = assignment_service.create_assignment_graph(
        cfg,
        {
            "graph_name": SCHEDULE_ASSIGNMENT_GRAPH_NAME,
            "source_workflow": SCHEDULE_ASSIGNMENT_SOURCE_WORKFLOW,
            "summary": "任务中心手动创建（全局主图）",
            "review_mode": "none",
            "external_request_id": SCHEDULE_ASSIGNMENT_GRAPH_REQUEST_ID,
            "operator": "schedule-worker",
        },
    )
    ticket_id = str(created.get("ticket_id") or "").strip()
    if not ticket_id:
        raise ScheduleCenterError(500, "global assignment graph missing", "schedule_assignment_graph_missing")
    return ticket_id


def _schedule_assignment_goal(schedule: dict[str, Any], *, planned_trigger_at: str, trigger_rule_summary: str) -> str:
    return "\n".join(
        [
            f"计划名称：{str(schedule.get('schedule_name') or '').strip()}",
            f"计划时间：{planned_trigger_at}",
            f"命中规则：{trigger_rule_summary}",
            "",
            "launch_summary",
            str(schedule.get("launch_summary") or "").strip() or "-",
            "",
            "execution_checklist",
            str(schedule.get("execution_checklist") or "").strip() or "-",
            "",
            "done_definition",
            str(schedule.get("done_definition") or "").strip() or "-",
        ]
    ).strip()


def _create_schedule_node(
    cfg: Any,
    schedule: dict[str, Any],
    *,
    trigger_instance_id: str,
    planned_trigger_at: str,
    trigger_rule_summary: str,
) -> dict[str, Any]:
    ticket_id = _ensure_global_assignment_graph(cfg)
    planned_label = planned_trigger_at.replace("T", " ").replace("+08:00", "")
    created = assignment_service.create_assignment_node(
        cfg,
        ticket_id,
        {
            "node_name": f"{str(schedule.get('schedule_name') or '').strip()} / {planned_label}",
            "assigned_agent_id": str(schedule.get("assigned_agent_id") or "").strip(),
            "priority": str(schedule.get("priority") or "P1"),
            "node_goal": _schedule_assignment_goal(
                schedule,
                planned_trigger_at=planned_trigger_at,
                trigger_rule_summary=trigger_rule_summary,
            ),
            "expected_artifact": str(schedule.get("expected_artifact") or "").strip(),
            "delivery_mode": str(schedule.get("delivery_mode") or "none").strip().lower() or "none",
            "delivery_receiver_agent_id": str(schedule.get("delivery_receiver_agent_id") or "").strip(),
            "source_schedule_id": str(schedule.get("schedule_id") or "").strip(),
            "planned_trigger_at": planned_trigger_at,
            "trigger_instance_id": trigger_instance_id,
            "trigger_rule_summary": trigger_rule_summary,
            "operator": "schedule-worker",
        },
        include_test_data=True,
    )
    node = dict(created.get("node") or {})
    node_id = str(node.get("node_id") or "").strip()
    if not node_id:
        raise ScheduleCenterError(500, "schedule assignment node missing", "schedule_assignment_node_missing")
    return {"ticket_id": ticket_id, "node_id": node_id}


def _request_assignment_dispatch(root: Path, ticket_id: str) -> dict[str, str]:
    overview = assignment_service.get_assignment_overview(root, ticket_id, include_test_data=True)
    graph = dict(overview.get("graph") or overview.get("graph_overview") or {})
    scheduler_state = str(graph.get("scheduler_state") or "").strip().lower()
    if scheduler_state == "idle":
        assignment_service.resume_assignment_scheduler(
            root,
            ticket_id_text=ticket_id,
            operator="schedule-worker",
            pause_note="schedule auto resume",
            include_test_data=True,
        )
        return {"dispatch_status": "requested", "dispatch_message": "resume_scheduler_requested"}
    assignment_service.dispatch_assignment_next(
        root,
        ticket_id_text=ticket_id,
        operator="schedule-worker",
        include_test_data=True,
    )
    return {"dispatch_status": "requested", "dispatch_message": "dispatch_requested"}


def _schedule_payload_from_body(cfg: Any, body: dict[str, Any], *, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    current = existing if isinstance(existing, dict) else {}
    enabled = _normalize_bool(body.get("enabled")) if "enabled" in body else bool(current.get("enabled"))
    assigned_agent = _resolve_agent(cfg, body.get("assigned_agent_id") if "assigned_agent_id" in body else current.get("assigned_agent_id"))
    priority_label, priority_value = _normalize_priority(body.get("priority") if "priority" in body else current.get("priority") or "P1")
    delivery_mode = _normalize_delivery_mode(body.get("delivery_mode") if "delivery_mode" in body else current.get("delivery_mode") or "none")
    receiver_meta = _resolve_agent(
        cfg,
        body.get("delivery_receiver_agent_id") if "delivery_receiver_agent_id" in body else current.get("delivery_receiver_agent_id"),
        allow_empty=delivery_mode != "specified",
    )
    if delivery_mode == "specified" and not str(receiver_meta.get("agent_id") or "").strip():
        raise ScheduleCenterError(400, "delivery_receiver_agent_id required", "schedule_delivery_receiver_required")
    if "rule_sets" in body:
        rule_sets = _normalize_rule_sets(body.get("rule_sets"))
    else:
        existing_rules = current.get("rule_sets")
        if isinstance(existing_rules, list):
            rule_sets = list(existing_rules)
        else:
            rule_sets = _normalize_rule_sets({"monthly": {}, "weekly": {}, "daily": {}, "once": {}})
    if enabled and not rule_sets:
        raise ScheduleCenterError(400, "enabled schedule requires at least one rule", "schedule_rule_required")
    payload = {
        "schedule_name": _normalize_text(body.get("schedule_name") if "schedule_name" in body else current.get("schedule_name"), field="schedule_name", required=True, max_len=200),
        "enabled": enabled,
        "assigned_agent_id": str(assigned_agent["agent_id"] or "").strip(),
        "assigned_agent_name": str(assigned_agent["agent_name"] or "").strip(),
        "launch_summary": _normalize_text(body.get("launch_summary") if "launch_summary" in body else current.get("launch_summary"), field="launch_summary", required=True, max_len=2000),
        "execution_checklist": _normalize_text(body.get("execution_checklist") if "execution_checklist" in body else current.get("execution_checklist"), field="execution_checklist", required=True, max_len=8000),
        "done_definition": _normalize_text(body.get("done_definition") if "done_definition" in body else current.get("done_definition"), field="done_definition", required=True, max_len=4000),
        "priority": priority_label,
        "priority_value": priority_value,
        "expected_artifact": _normalize_text(body.get("expected_artifact") if "expected_artifact" in body else current.get("expected_artifact"), field="expected_artifact", required=False, max_len=1000),
        "delivery_mode": delivery_mode,
        "delivery_receiver_agent_id": str(receiver_meta.get("agent_id") or "").strip(),
        "delivery_receiver_agent_name": str(receiver_meta.get("agent_name") or "").strip(),
        "rule_sets": rule_sets,
        "timezone": SCHEDULE_TIMEZONE,
    }
    payload.update(_schedule_trigger_projection(payload))
    return payload


def create_schedule(cfg: Any, body: dict[str, Any]) -> dict[str, Any]:
    _ensure_schedule_tables(cfg.root)
    operator = _normalize_text(body.get("operator") or "web-user", field="operator", required=True, max_len=120)
    now_text = _now_text()
    payload = _schedule_payload_from_body(cfg, body)
    schedule_id = _schedule_id()
    conn = connect_db(cfg.root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO schedule_plans(
                schedule_id,schedule_name,enabled,assigned_agent_id,assigned_agent_name,
                launch_summary,execution_checklist,done_definition,priority,expected_artifact,
                delivery_mode,delivery_receiver_agent_id,delivery_receiver_agent_name,
                rule_sets_json,timezone,next_trigger_at,last_trigger_at,last_result_status,
                last_result_ticket_id,last_result_node_id,created_by,updated_by,deleted_at,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                schedule_id,
                payload["schedule_name"],
                1 if payload["enabled"] else 0,
                payload["assigned_agent_id"],
                payload["assigned_agent_name"],
                payload["launch_summary"],
                payload["execution_checklist"],
                payload["done_definition"],
                int(payload["priority_value"]),
                payload["expected_artifact"],
                payload["delivery_mode"],
                payload["delivery_receiver_agent_id"],
                payload["delivery_receiver_agent_name"],
                _json_dumps(payload["rule_sets"], "[]"),
                SCHEDULE_TIMEZONE,
                payload["next_trigger_at"],
                "",
                "pending",
                "",
                "",
                operator,
                operator,
                "",
                now_text,
                now_text,
            ),
        )
        audit_id = _append_schedule_audit(
            conn,
            schedule_id=schedule_id,
            action="create_schedule",
            operator=operator,
            detail={"enabled": payload["enabled"], "rule_count": len(payload["rule_sets"]), "next_trigger_at": payload["next_trigger_at"]},
            created_at=now_text,
        )
        conn.commit()
    finally:
        conn.close()
    _append_schedule_event(cfg.root, {"created_at": now_text, "action": "create_schedule", "schedule_id": schedule_id, "operator": operator, "audit_id": audit_id})
    return {"schedule_id": schedule_id, "audit_id": audit_id, **get_schedule_detail(cfg.root, schedule_id)}


def update_schedule(cfg: Any, schedule_id: str, body: dict[str, Any]) -> dict[str, Any]:
    _ensure_schedule_tables(cfg.root)
    schedule_key = _safe_token(schedule_id)
    if not schedule_key:
        raise ScheduleCenterError(400, "schedule_id required", "schedule_id_required")
    operator = _normalize_text(body.get("operator") or "web-user", field="operator", required=True, max_len=120)
    now_text = _now_text()
    conn = connect_db(cfg.root)
    try:
        existing = _row_to_schedule(_load_plan_row(conn, schedule_key))
    finally:
        conn.close()
    payload = _schedule_payload_from_body(cfg, body, existing=existing)
    conn = connect_db(cfg.root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        _load_plan_row(conn, schedule_key)
        conn.execute(
            """
            UPDATE schedule_plans
            SET schedule_name=?,enabled=?,assigned_agent_id=?,assigned_agent_name=?,
                launch_summary=?,execution_checklist=?,done_definition=?,priority=?,expected_artifact=?,
                delivery_mode=?,delivery_receiver_agent_id=?,delivery_receiver_agent_name=?,
                rule_sets_json=?,timezone=?,next_trigger_at=?,updated_by=?,updated_at=?
            WHERE schedule_id=?
            """,
            (
                payload["schedule_name"],
                1 if payload["enabled"] else 0,
                payload["assigned_agent_id"],
                payload["assigned_agent_name"],
                payload["launch_summary"],
                payload["execution_checklist"],
                payload["done_definition"],
                int(payload["priority_value"]),
                payload["expected_artifact"],
                payload["delivery_mode"],
                payload["delivery_receiver_agent_id"],
                payload["delivery_receiver_agent_name"],
                _json_dumps(payload["rule_sets"], "[]"),
                SCHEDULE_TIMEZONE,
                payload["next_trigger_at"],
                operator,
                now_text,
                schedule_key,
            ),
        )
        audit_id = _append_schedule_audit(
            conn,
            schedule_id=schedule_key,
            action="update_schedule",
            operator=operator,
            detail={"enabled": payload["enabled"], "rule_count": len(payload["rule_sets"]), "next_trigger_at": payload["next_trigger_at"]},
            created_at=now_text,
        )
        conn.commit()
    finally:
        conn.close()
    _append_schedule_event(cfg.root, {"created_at": now_text, "action": "update_schedule", "schedule_id": schedule_key, "operator": operator, "audit_id": audit_id})
    return {"schedule_id": schedule_key, "audit_id": audit_id, **get_schedule_detail(cfg.root, schedule_key)}


def set_schedule_enabled(cfg: Any, schedule_id: str, *, enabled: bool, operator: str) -> dict[str, Any]:
    _ensure_schedule_tables(cfg.root)
    schedule_key = _safe_token(schedule_id)
    if not schedule_key:
        raise ScheduleCenterError(400, "schedule_id required", "schedule_id_required")
    operator_text = _normalize_text(operator or "web-user", field="operator", required=True, max_len=120)
    now_text = _now_text()
    conn = connect_db(cfg.root)
    try:
        current = _row_to_schedule(_load_plan_row(conn, schedule_key))
    finally:
        conn.close()
    if enabled and not list(current.get("rule_sets") or []):
        raise ScheduleCenterError(400, "enabled schedule requires at least one rule", "schedule_rule_required")
    projection = _schedule_trigger_projection({**current, "enabled": enabled})
    conn = connect_db(cfg.root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        _load_plan_row(conn, schedule_key)
        conn.execute(
            "UPDATE schedule_plans SET enabled=?,next_trigger_at=?,updated_by=?,updated_at=? WHERE schedule_id=?",
            (1 if enabled else 0, projection["next_trigger_at"], operator_text, now_text, schedule_key),
        )
        action = "enable_schedule" if enabled else "disable_schedule"
        audit_id = _append_schedule_audit(
            conn,
            schedule_id=schedule_key,
            action=action,
            operator=operator_text,
            detail={"enabled": enabled, "next_trigger_at": projection["next_trigger_at"]},
            created_at=now_text,
        )
        conn.commit()
    finally:
        conn.close()
    _append_schedule_event(cfg.root, {"created_at": now_text, "action": action, "schedule_id": schedule_key, "operator": operator_text, "audit_id": audit_id})
    return {"schedule_id": schedule_key, "audit_id": audit_id, **get_schedule_detail(cfg.root, schedule_key)}


def delete_schedule(root: Path, schedule_id: str, *, operator: str) -> dict[str, Any]:
    _ensure_schedule_tables(root)
    schedule_key = _safe_token(schedule_id)
    if not schedule_key:
        raise ScheduleCenterError(400, "schedule_id required", "schedule_id_required")
    operator_text = _normalize_text(operator or "web-user", field="operator", required=True, max_len=120)
    now_text = _now_text()
    conn = connect_db(root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        _load_plan_row(conn, schedule_key)
        conn.execute(
            "UPDATE schedule_plans SET enabled=0,deleted_at=?,updated_by=?,updated_at=? WHERE schedule_id=?",
            (now_text, operator_text, now_text, schedule_key),
        )
        audit_id = _append_schedule_audit(
            conn,
            schedule_id=schedule_key,
            action="delete_schedule",
            operator=operator_text,
            detail={"deleted_at": now_text},
            created_at=now_text,
        )
        conn.commit()
    finally:
        conn.close()
    _append_schedule_event(root, {"created_at": now_text, "action": "delete_schedule", "schedule_id": schedule_key, "operator": operator_text, "audit_id": audit_id})
    return {"schedule_id": schedule_key, "deleted_at": now_text, "audit_id": audit_id}


def run_schedule_scan(cfg: Any, *, operator: str = "schedule-worker", now_at: str = "", schedule_id: str = "") -> dict[str, Any]:
    _ensure_schedule_tables(cfg.root)
    operator_text = _normalize_text(operator or "schedule-worker", field="operator", required=True, max_len=120)
    target_minute = _parse_datetime_token(now_at, field="now_at") if str(now_at or "").strip() else _minute_floor(_now_bj())
    schedule_key = _safe_token(schedule_id)
    conn = connect_db(cfg.root)
    try:
        sql = "SELECT * FROM schedule_plans WHERE deleted_at='' AND enabled=1"
        params: list[Any] = []
        if schedule_key:
            sql += " AND schedule_id=?"
            params.append(schedule_key)
        rows = conn.execute(sql + " ORDER BY updated_at DESC", tuple(params)).fetchall()
    finally:
        conn.close()
    scanned = 0
    hits = 0
    deduped = 0
    created_nodes = 0
    items: list[dict[str, Any]] = []
    for row in rows:
        schedule = _row_to_schedule(row)
        scanned += 1
        due_items = _merge_candidates(
            [
                candidate
                for rule in list(schedule.get("rule_sets") or [])
                for candidate in _iter_rule_candidates(rule, target_minute, target_minute)
            ]
        )
        if not due_items:
            continue
        due = due_items[0]
        planned_trigger_at = str(due["planned_trigger_at"])
        hits += 1
        now_text = _now_text()
        conn = connect_db(cfg.root)
        trigger_id = ""
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM schedule_trigger_instances WHERE schedule_id=? AND planned_trigger_at=? LIMIT 1",
                (schedule["schedule_id"], planned_trigger_at),
            ).fetchone()
            if existing is not None:
                deduped += 1
                trigger_id = str(existing["trigger_instance_id"] or "").strip()
                audit_id = _append_schedule_audit(
                    conn,
                    schedule_id=schedule["schedule_id"],
                    trigger_instance_id=trigger_id,
                    action="trigger_deduped",
                    operator=operator_text,
                    detail={"planned_trigger_at": planned_trigger_at, "trigger_rule_summary": due["trigger_rule_summary"]},
                    created_at=now_text,
                )
                conn.commit()
                _append_schedule_event(cfg.root, {"created_at": now_text, "action": "trigger_deduped", "schedule_id": schedule["schedule_id"], "trigger_instance_id": trigger_id, "audit_id": audit_id})
                items.append({"schedule_id": schedule["schedule_id"], "trigger_instance_id": trigger_id, "status": "deduped"})
                continue
            trigger_id = _schedule_trigger_id()
            conn.execute(
                """
                INSERT INTO schedule_trigger_instances(
                    trigger_instance_id,schedule_id,planned_trigger_at,trigger_rule_summary,trigger_rule_keys_json,merged_rule_count,
                    trigger_status,trigger_message,assignment_ticket_id,assignment_node_id,schedule_name_snapshot,assigned_agent_id_snapshot,
                    launch_summary_snapshot,execution_checklist_snapshot,done_definition_snapshot,expected_artifact_snapshot,
                    delivery_mode_snapshot,delivery_receiver_agent_id_snapshot,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    trigger_id,
                    schedule["schedule_id"],
                    planned_trigger_at,
                    due["trigger_rule_summary"],
                    _json_dumps(due["trigger_rule_keys"], "[]"),
                    int(due["merged_rule_count"] or 0),
                    "trigger_hit",
                    "",
                    "",
                    "",
                    schedule["schedule_name"],
                    schedule["assigned_agent_id"],
                    schedule["launch_summary"],
                    schedule["execution_checklist"],
                    schedule["done_definition"],
                    schedule["expected_artifact"],
                    schedule["delivery_mode"],
                    schedule["delivery_receiver_agent_id"],
                    now_text,
                    now_text,
                ),
            )
            audit_id = _append_schedule_audit(
                conn,
                schedule_id=schedule["schedule_id"],
                trigger_instance_id=trigger_id,
                action="trigger_hit",
                operator=operator_text,
                detail={"planned_trigger_at": planned_trigger_at, "trigger_rule_summary": due["trigger_rule_summary"]},
                created_at=now_text,
            )
            conn.commit()
            _append_schedule_event(cfg.root, {"created_at": now_text, "action": "trigger_hit", "schedule_id": schedule["schedule_id"], "trigger_instance_id": trigger_id, "audit_id": audit_id})
        finally:
            conn.close()
        try:
            created = _create_schedule_node(
                cfg,
                schedule,
                trigger_instance_id=trigger_id,
                planned_trigger_at=planned_trigger_at,
                trigger_rule_summary=str(due["trigger_rule_summary"]),
            )
            dispatch_status = "requested"
            dispatch_message = ""
            try:
                dispatch_result = _request_assignment_dispatch(cfg.root, str(created["ticket_id"]))
                dispatch_status = str(dispatch_result.get("dispatch_status") or "requested")
                dispatch_message = str(dispatch_result.get("dispatch_message") or "").strip()
            except Exception as dispatch_exc:
                dispatch_status = "dispatch_failed"
                dispatch_message = str(dispatch_exc)
            created_nodes += 1
            result_status = _assignment_runtime_status(cfg.root, ticket_id=str(created["ticket_id"]), node_id=str(created["node_id"]))
            next_items = _future_triggers(list(schedule.get("rule_sets") or []), start_dt=target_minute + timedelta(minutes=1), limit=1)
            conn = connect_db(cfg.root)
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    UPDATE schedule_trigger_instances
                    SET trigger_status=?,trigger_message=?,assignment_ticket_id=?,assignment_node_id=?,updated_at=?
                    WHERE trigger_instance_id=?
                    """,
                    (
                        dispatch_status if dispatch_status == "dispatch_failed" else str(result_status.get("result_status") or "queued"),
                        dispatch_message or str(result_status.get("assignment_status_text") or result_status.get("result_status_text") or "").strip(),
                        str(created["ticket_id"]),
                        str(created["node_id"]),
                        _now_text(),
                        trigger_id,
                    ),
                )
                conn.execute(
                    """
                    UPDATE schedule_plans
                    SET last_trigger_at=?,last_result_status=?,last_result_ticket_id=?,last_result_node_id=?,next_trigger_at=?
                    WHERE schedule_id=?
                    """,
                    (
                        planned_trigger_at,
                        str(result_status.get("result_status") or "queued"),
                        str(created["ticket_id"]),
                        str(created["node_id"]),
                        str(next_items[0]["planned_trigger_at"]) if next_items else "",
                        schedule["schedule_id"],
                    ),
                )
                audit_id = _append_schedule_audit(
                    conn,
                    schedule_id=schedule["schedule_id"],
                    trigger_instance_id=trigger_id,
                    action="dispatch_failed" if dispatch_status == "dispatch_failed" else "create_assignment_node",
                    operator=operator_text,
                    detail={
                        "assignment_ticket_id": created["ticket_id"],
                        "assignment_node_id": created["node_id"],
                        "dispatch_status": dispatch_status,
                        "dispatch_message": dispatch_message,
                    },
                    created_at=_now_text(),
                )
                conn.commit()
            finally:
                conn.close()
            _append_schedule_event(
                cfg.root,
                {
                    "created_at": _now_text(),
                    "action": "dispatch_failed" if dispatch_status == "dispatch_failed" else "create_assignment_node",
                    "schedule_id": schedule["schedule_id"],
                    "trigger_instance_id": trigger_id,
                    "assignment_ticket_id": created["ticket_id"],
                    "assignment_node_id": created["node_id"],
                    "dispatch_status": dispatch_status,
                    "dispatch_message": dispatch_message,
                    "audit_id": audit_id,
                },
            )
            items.append(
                {
                    "schedule_id": schedule["schedule_id"],
                    "trigger_instance_id": trigger_id,
                    "status": "dispatch_failed" if dispatch_status == "dispatch_failed" else "created",
                    "assignment_ticket_id": created["ticket_id"],
                    "assignment_node_id": created["node_id"],
                    "dispatch_message": dispatch_message,
                }
            )
        except Exception as exc:
            conn = connect_db(cfg.root)
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "UPDATE schedule_trigger_instances SET trigger_status='create_failed',trigger_message=?,updated_at=? WHERE trigger_instance_id=?",
                    (str(exc), _now_text(), trigger_id),
                )
                conn.execute(
                    "UPDATE schedule_plans SET last_trigger_at=?,last_result_status='failed' WHERE schedule_id=?",
                    (planned_trigger_at, schedule["schedule_id"]),
                )
                audit_id = _append_schedule_audit(
                    conn,
                    schedule_id=schedule["schedule_id"],
                    trigger_instance_id=trigger_id,
                    action="trigger_failed",
                    operator=operator_text,
                    detail={"stage": "create_assignment_node", "error": str(exc)},
                    created_at=_now_text(),
                )
                conn.commit()
            finally:
                conn.close()
            _append_schedule_event(cfg.root, {"created_at": _now_text(), "action": "trigger_failed", "schedule_id": schedule["schedule_id"], "trigger_instance_id": trigger_id, "stage": "create_assignment_node", "error": str(exc), "audit_id": audit_id})
            items.append({"schedule_id": schedule["schedule_id"], "trigger_instance_id": trigger_id, "status": "failed", "error": str(exc)})
    return {
        "scanned": scanned,
        "hit_count": hits,
        "deduped_count": deduped,
        "created_node_count": created_nodes,
        "scan_at": _iso_minute(target_minute),
        "items": items,
    }


def start_schedule_trigger_worker(cfg: Any, state: Any) -> threading.Thread:
    worker_key = f"{str(getattr(cfg, 'root', ''))}:{str(getattr(cfg, 'host', ''))}:{str(getattr(cfg, 'port', ''))}"
    with _SCHEDULE_WORKER_LOCK:
        existing = _SCHEDULE_WORKER_THREADS.get(worker_key)
        if existing and existing.is_alive():
            return existing

        def worker() -> None:
            last_minute = ""
            while not state.stop_event.is_set():
                try:
                    current_minute = _iso_minute(_now_bj())
                    if current_minute != last_minute:
                        run_schedule_scan(cfg, operator="schedule-worker", now_at=current_minute)
                        last_minute = current_minute
                except Exception as exc:
                    _append_schedule_event(cfg.root, {"created_at": _now_text(), "action": "worker_error", "error": str(exc)})
                if state.stop_event.wait(SCHEDULE_WORKER_INTERVAL_SECONDS):
                    break

        thread = threading.Thread(target=worker, name="schedule-trigger-worker", daemon=True)
        _SCHEDULE_WORKER_THREADS[worker_key] = thread
        thread.start()
        return thread
