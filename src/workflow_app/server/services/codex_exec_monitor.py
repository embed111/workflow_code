from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(slots=True)
class MonitoredProcessResult:
    stdout_text: str
    stderr_text: str
    exit_code: int | None
    started_at_ms: int
    finished_at_ms: int
    forced_exit_after_result: bool
    monitor: dict[str, Any]

    @property
    def duration_ms(self) -> int:
        return max(0, int(self.finished_at_ms or 0) - int(self.started_at_ms or 0))


def _now_ms() -> int:
    return max(0, int(time.time() * 1000))


def resolve_codex_command(
    *,
    env_var_names: tuple[str, ...] = ("WORKFLOW_CODEX_BIN",),
) -> str:
    for env_name in env_var_names:
        raw = str(os.getenv(env_name) or "").strip()
        if not raw:
            continue
        candidate = Path(raw).expanduser()
        # Acceptance/dev may inject a stub binary via env. Formal test/prod must not set this override.
        return candidate.as_posix() if candidate.exists() else raw
    return str(shutil.which("codex.cmd") or shutil.which("codex") or "").strip()


def _terminate_process(proc: subprocess.Popen[str] | None) -> None:
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except Exception:
                pass
    except Exception:
        pass
    try:
        if proc.poll() is None:
            proc.kill()
    except Exception:
        return


def run_monitored_subprocess(
    *,
    command: list[str],
    cwd: Path | str,
    stdin_text: str = "",
    on_stdout_line: Callable[[str], None] | None = None,
    on_stderr_line: Callable[[str], None] | None = None,
    completion_checker: Callable[[], bool] | None = None,
    completion_grace_s: float = 8.0,
) -> MonitoredProcessResult:
    proc = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    if proc.stdin is not None:
        proc.stdin.write(str(stdin_text or ""))
        if stdin_text and not str(stdin_text).endswith("\n"):
            proc.stdin.write("\n")
        proc.stdin.close()

    started_at_ms = _now_ms()
    monitor: dict[str, Any] = {
        "pid": int(getattr(proc, "pid", 0) or 0),
        "started_at_ms": started_at_ms,
        "finished_at_ms": 0,
        "last_stdout_at_ms": 0,
        "last_stderr_at_ms": 0,
        "last_activity_at_ms": started_at_ms,
        "stdout_line_count": 0,
        "stderr_line_count": 0,
        "completion_observed_at_ms": 0,
        "forced_exit_after_result": False,
    }
    monitor_lock = threading.Lock()
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []

    def _note_activity(stream_key: str) -> None:
        now_ms = _now_ms()
        with monitor_lock:
            monitor[f"last_{stream_key}_at_ms"] = now_ms
            monitor["last_activity_at_ms"] = now_ms
            counter_key = f"{stream_key}_line_count"
            monitor[counter_key] = int(monitor.get(counter_key) or 0) + 1

    def _read_stream(
        pipe: Any,
        collector: list[str],
        stream_key: str,
        observer: Callable[[str], None] | None,
    ) -> None:
        if pipe is None:
            return
        try:
            for line in iter(pipe.readline, ""):
                if line == "":
                    break
                collector.append(line)
                _note_activity(stream_key)
                if observer is not None:
                    try:
                        observer(line)
                    except Exception:
                        pass
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    t_out = threading.Thread(
        target=_read_stream,
        args=(proc.stdout, stdout_chunks, "stdout", on_stdout_line),
        daemon=True,
    )
    t_err = threading.Thread(
        target=_read_stream,
        args=(proc.stderr, stderr_chunks, "stderr", on_stderr_line),
        daemon=True,
    )
    t_out.start()
    t_err.start()

    exit_code: int | None = None
    completion_marked_at = 0.0
    forced_exit_after_result = False
    try:
        while True:
            try:
                exit_code = int(proc.wait(timeout=1) or 0)
                break
            except subprocess.TimeoutExpired:
                if completion_checker is None:
                    continue
                try:
                    completed = bool(completion_checker())
                except Exception:
                    completed = False
                if not completed:
                    completion_marked_at = 0.0
                    continue
                if completion_marked_at <= 0:
                    completion_marked_at = time.monotonic()
                    with monitor_lock:
                        if not int(monitor.get("completion_observed_at_ms") or 0):
                            monitor["completion_observed_at_ms"] = _now_ms()
                    continue
                if (time.monotonic() - completion_marked_at) < max(1.0, float(completion_grace_s or 0.0)):
                    continue
                forced_exit_after_result = True
                _terminate_process(proc)
                try:
                    proc.wait(timeout=3)
                except Exception:
                    pass
                exit_code = 0
                break
    finally:
        t_out.join(timeout=2)
        t_err.join(timeout=2)
        finished_at_ms = _now_ms()
        with monitor_lock:
            monitor["finished_at_ms"] = finished_at_ms
            monitor["forced_exit_after_result"] = bool(forced_exit_after_result)

    return MonitoredProcessResult(
        stdout_text="".join(stdout_chunks),
        stderr_text="".join(stderr_chunks),
        exit_code=exit_code,
        started_at_ms=started_at_ms,
        finished_at_ms=max(started_at_ms, int(monitor.get("finished_at_ms") or started_at_ms)),
        forced_exit_after_result=bool(forced_exit_after_result),
        monitor=dict(monitor),
    )
