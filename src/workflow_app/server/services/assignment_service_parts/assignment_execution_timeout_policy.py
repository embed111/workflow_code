from __future__ import annotations


def _assignment_execution_activity_timeout_s() -> int:
    raw = str(os.getenv("WORKFLOW_ASSIGNMENT_EXECUTION_ACTIVITY_TIMEOUT_S") or "").strip()
    if raw:
        try:
            return max(30, int(raw))
        except Exception:
            pass
    return max(30, int(_assignment_execution_timeout_s()))


def _assignment_execution_activity_age_seconds(
    *,
    last_activity_monotonic: float,
    now_monotonic: float,
) -> float:
    try:
        last_value = float(last_activity_monotonic or 0.0)
        now_value = float(now_monotonic or 0.0)
    except Exception:
        return 0.0
    if last_value <= 0.0 or now_value <= last_value:
        return 0.0
    return now_value - last_value


def _assignment_execution_activity_timed_out(
    *,
    last_activity_monotonic: float,
    now_monotonic: float,
    timeout_s: int,
) -> bool:
    return _assignment_execution_activity_age_seconds(
        last_activity_monotonic=last_activity_monotonic,
        now_monotonic=now_monotonic,
    ) >= max(1, int(timeout_s or 0))


def _assignment_execution_timeout_message(timeout_s: int) -> str:
    return f"assignment execution timeout after {max(1, int(timeout_s or 0))}s without progress"
