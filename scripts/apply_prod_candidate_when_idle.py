#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request


DEFAULT_BASE_URL = "http://127.0.0.1:8090"
DEFAULT_OPERATOR = "prod-idle-upgrade-watcher"
DEFAULT_TIMEOUT_SECONDS = 1800.0
DEFAULT_POLL_SECONDS = 10.0
DEFAULT_REQUEST_TIMEOUT_SECONDS = 8.0
DEFAULT_APPLY_WAIT_SECONDS = 240.0


def _now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _default_log_path(repo_root: Path) -> Path:
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    return repo_root / "logs" / "runs" / f"prod-idle-upgrade-watcher-{stamp}.md"


def _request_json(
    *,
    base_url: str,
    path: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
) -> tuple[int, dict[str, Any]]:
    url = f"{str(base_url or '').rstrip('/')}{str(path or '').strip()}"
    headers = {"Accept": "application/json"}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib_request.Request(
        url,
        data=body,
        headers=headers,
        method=str(method or "GET").strip().upper() or "GET",
    )
    try:
        with urllib_request.urlopen(request, timeout=max(1.0, float(timeout_seconds or 0.0))) as response:
            status = int(getattr(response, "status", 0) or response.getcode() or 0)
            raw = response.read().decode("utf-8", "replace")
    except urllib_error.HTTPError as exc:
        status = int(exc.code or 0)
        raw = exc.read().decode("utf-8", "replace")
    except Exception as exc:
        return 0, {
            "ok": False,
            "error": str(exc),
            "code": "request_failed",
        }
    try:
        payload_data = json.loads(raw) if raw else {}
    except Exception:
        payload_data = {
            "ok": False,
            "error": "response_invalid_json",
            "raw_body": raw[:1000],
        }
    if not isinstance(payload_data, dict):
        payload_data = {
            "ok": False,
            "error": "response_payload_invalid",
        }
    return status, payload_data


def _append_log(log_path: Path, line: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(line.rstrip() + "\n")


def _log_message(log_path: Path, message: str) -> None:
    _append_log(log_path, f"- `{_now_text()}` {message}")


def _status_summary(payload: dict[str, Any]) -> str:
    return ", ".join(
        [
            f"current={str(payload.get('current_version') or '').strip() or '-'}",
            f"candidate={str(payload.get('candidate_version') or '').strip() or '-'}",
            f"candidate_is_newer={bool(payload.get('candidate_is_newer'))}",
            f"request_pending={bool(payload.get('request_pending'))}",
            f"running_task_count={int(payload.get('running_task_count') or 0)}",
            f"can_upgrade={bool(payload.get('can_upgrade'))}",
        ]
    )


def _wait_for_upgrade_completion(
    *,
    base_url: str,
    candidate_version: str,
    poll_seconds: float,
    request_timeout_seconds: float,
    wait_seconds: float,
    log_path: Path,
) -> bool:
    deadline = time.monotonic() + max(1.0, float(wait_seconds or 0.0))
    while time.monotonic() < deadline:
        status_code, status_payload = _request_json(
            base_url=base_url,
            path="/api/runtime-upgrade/status",
            timeout_seconds=request_timeout_seconds,
        )
        if status_code == 200 and bool(status_payload.get("ok")):
            _log_message(log_path, f"等待升级完成中：{_status_summary(status_payload)}")
            current_version = str(status_payload.get("current_version") or "").strip()
            request_pending = bool(status_payload.get("request_pending"))
            candidate_is_newer = bool(status_payload.get("candidate_is_newer"))
            if current_version == candidate_version and not request_pending:
                _log_message(log_path, "prod 已切到目标 candidate，watcher 结束。")
                return True
            if current_version == candidate_version and not candidate_is_newer:
                _log_message(log_path, "candidate 已不再比 current 更新，视为升级完成。")
                return True
        else:
            _log_message(
                log_path,
                f"等待升级完成时状态接口不可用：status_code={int(status_code or 0)} payload={json.dumps(status_payload, ensure_ascii=False)}",
            )
        time.sleep(max(0.1, float(poll_seconds or 0.0)))
    _log_message(log_path, f"超过等待窗口仍未确认切换到 {candidate_version}。")
    return False


def run_watcher(args: argparse.Namespace) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    log_path = Path(args.log_path).resolve() if str(args.log_path or "").strip() else _default_log_path(repo_root)

    _append_log(log_path, "# Prod Idle Upgrade Watcher")
    _append_log(log_path, "")
    _log_message(
        log_path,
        "watcher 启动："
        + ", ".join(
            [
                f"base_url={args.base_url}",
                f"timeout_seconds={float(args.timeout_seconds):.1f}",
                f"poll_seconds={float(args.poll_seconds):.1f}",
                f"operator={args.operator}",
            ]
        ),
    )

    deadline = time.monotonic() + max(1.0, float(args.timeout_seconds or 0.0))
    while time.monotonic() < deadline:
        status_code, status_payload = _request_json(
            base_url=args.base_url,
            path="/api/runtime-upgrade/status",
            timeout_seconds=args.request_timeout_seconds,
        )
        if status_code != 200 or not bool(status_payload.get("ok")):
            _log_message(
                log_path,
                f"状态接口不可用：status_code={int(status_code or 0)} payload={json.dumps(status_payload, ensure_ascii=False)}",
            )
            time.sleep(max(0.1, float(args.poll_seconds or 0.0)))
            continue

        _log_message(log_path, f"状态轮询：{_status_summary(status_payload)}")
        candidate_version = str(status_payload.get("candidate_version") or "").strip()
        candidate_is_newer = bool(status_payload.get("candidate_is_newer"))
        running_task_count = int(status_payload.get("running_task_count") or 0)
        can_upgrade = bool(status_payload.get("can_upgrade"))

        if not candidate_version:
            _log_message(log_path, "当前没有 prod candidate，继续等待。")
            time.sleep(max(0.1, float(args.poll_seconds or 0.0)))
            continue

        if args.require_candidate_newer and not candidate_is_newer:
            _log_message(log_path, "candidate 已不比 current 更新，watcher 直接结束。")
            return 0

        if can_upgrade and running_task_count <= 0:
            apply_status, apply_payload = _request_json(
                base_url=args.base_url,
                path="/api/runtime-upgrade/apply",
                method="POST",
                payload={"operator": args.operator},
                timeout_seconds=args.request_timeout_seconds,
            )
            _log_message(
                log_path,
                f"发起 apply：status_code={int(apply_status or 0)} payload={json.dumps(apply_payload, ensure_ascii=False)}",
            )
            apply_code = str(apply_payload.get("code") or "").strip()
            if int(apply_status or 0) in {200, 202} and bool(apply_payload.get("ok")):
                completed = _wait_for_upgrade_completion(
                    base_url=args.base_url,
                    candidate_version=candidate_version,
                    poll_seconds=args.poll_seconds,
                    request_timeout_seconds=args.request_timeout_seconds,
                    wait_seconds=args.apply_wait_seconds,
                    log_path=log_path,
                )
                return 0 if completed else 4
            if apply_code == "runtime_upgrade_already_requested" or bool(apply_payload.get("request_pending")):
                completed = _wait_for_upgrade_completion(
                    base_url=args.base_url,
                    candidate_version=candidate_version,
                    poll_seconds=args.poll_seconds,
                    request_timeout_seconds=args.request_timeout_seconds,
                    wait_seconds=args.apply_wait_seconds,
                    log_path=log_path,
                )
                return 0 if completed else 4
            _log_message(log_path, "apply 失败，继续等待下一次空闲窗口。")

        time.sleep(max(0.1, float(args.poll_seconds or 0.0)))

    _log_message(log_path, "watcher 超时退出，仍未等到可升级空窗。")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Wait for an idle prod window and apply the latest candidate.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--operator", default=DEFAULT_OPERATOR)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)
    parser.add_argument("--request-timeout-seconds", type=float, default=DEFAULT_REQUEST_TIMEOUT_SECONDS)
    parser.add_argument("--apply-wait-seconds", type=float, default=DEFAULT_APPLY_WAIT_SECONDS)
    parser.add_argument("--log-path", default="")
    parser.add_argument("--require-candidate-newer", action="store_true", default=True)
    parser.add_argument("--allow-equal-candidate", dest="require_candidate_newer", action="store_false")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return run_watcher(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
