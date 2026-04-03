#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass
class Viewport:
    name: str
    width: int
    height: int


VIEWPORTS: list[Viewport] = [
    Viewport("1366x768", 1366, 768),
    Viewport("1280x720", 1280, 720),
    Viewport("1080x700", 1080, 700),
    Viewport("900x700", 900, 700),
    Viewport("768x1024", 768, 1024),
    Viewport("390x844", 390, 844),
]
TABS = ("chat", "training", "settings")


def call(base_url: str, path: str) -> tuple[int, dict]:
    req = Request(url=base_url + path, method="GET")
    try:
        with urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, (json.loads(body) if body else {})
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            payload = json.loads(body) if body else {}
        except Exception:
            payload = {"raw": body}
        return exc.code, payload


def wait_health(base_url: str, timeout_s: int = 90) -> None:
    end_at = time.time() + max(10, timeout_s)
    while time.time() < end_at:
        status, payload = call(base_url, "/healthz")
        if status == 200 and bool(payload.get("ok")):
            return
        time.sleep(0.5)
    raise RuntimeError("healthz timeout")


def find_edge_executable() -> Path:
    candidates = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    for path in candidates:
        if path.exists() and path.is_file():
            return path
    raise RuntimeError("Microsoft Edge executable not found")


def run_edge_cmd(
    edge_path: Path,
    *,
    viewport: Viewport,
    url: str,
    screenshot_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        str(edge_path),
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        f"--window-size={viewport.width},{viewport.height}",
        "--virtual-time-budget=10000",
    ]
    if screenshot_path is not None:
        cmd.append(f"--screenshot={screenshot_path.as_posix()}")
    else:
        cmd.append("--dump-dom")
    cmd.append(url)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=150,
    )


def parse_probe(dom_text: str) -> dict:
    matched = re.search(
        r"<pre[^>]*id=['\"]layoutProbeOutput['\"][^>]*>(.*?)</pre>",
        str(dom_text or ""),
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not matched:
        return {"error": "layoutProbeOutput_not_found"}
    raw = html.unescape(matched.group(1) or "").strip()
    if not raw:
        return {"error": "layoutProbeOutput_empty"}
    try:
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else {"error": "layoutProbeOutput_not_dict"}
    except Exception as exc:
        return {"error": f"layoutProbeOutput_json_error:{exc}"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check frontend layout overflow with Edge headless.")
    parser.add_argument("--root", default=".", help="workspace root")
    parser.add_argument("--host", default="127.0.0.1", help="web host")
    parser.add_argument("--port", type=int, default=8110, help="web port")
    parser.add_argument(
        "--out-dir",
        default="",
        help="report output directory (default: .output/runs/layout-overflow-<ts>)",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out_dir = (
        Path(args.out_dir).resolve()
        if str(args.out_dir or "").strip()
        else (root / ".output" / "runs" / f"layout-overflow-{datetime.now().strftime('%Y%m%d-%H%M%S')}").resolve()
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir = out_dir / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    edge_path = find_edge_executable()
    base_url = f"http://{args.host}:{args.port}"
    web_script = (root / "scripts" / "workflow_web_server.py").resolve()
    proc = subprocess.Popen(
        [
            sys.executable,
            str(web_script),
            "--host",
            args.host,
            "--port",
            str(args.port),
        ],
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    rows: list[dict] = []
    errors: list[str] = []
    try:
        wait_health(base_url, timeout_s=90)
        for viewport in VIEWPORTS:
            for tab in TABS:
                params = {
                    "layout_probe": "1",
                    "layout_probe_tab": tab,
                    "layout_probe_expand": "1",
                    "layout_probe_stress": "1",
                }
                url = base_url + "/?" + urlencode(params)
                dom_run = run_edge_cmd(edge_path, viewport=viewport, url=url, screenshot_path=None)
                probe = parse_probe(dom_run.stdout)
                screenshot_path = screenshots_dir / f"{viewport.name}-{tab}.png"
                shot_run = run_edge_cmd(
                    edge_path,
                    viewport=viewport,
                    url=url,
                    screenshot_path=screenshot_path,
                )
                row = {
                    "viewport": viewport.name,
                    "tab": tab,
                    "innerWidth": int(probe.get("innerWidth") or 0),
                    "scrollWidth": int(probe.get("scrollWidth") or 0),
                    "bodyScrollWidth": int(probe.get("bodyScrollWidth") or 0),
                    "probe_error": str(probe.get("error") or ""),
                    "probe_pass": bool(probe.get("pass")),
                    "screenshot": screenshot_path.as_posix(),
                    "dom_returncode": int(dom_run.returncode),
                    "shot_returncode": int(shot_run.returncode),
                }
                row["pass"] = bool(
                    row["dom_returncode"] == 0
                    and row["shot_returncode"] == 0
                    and not row["probe_error"]
                    and row["scrollWidth"] <= row["innerWidth"]
                )
                if not row["pass"]:
                    errors.append(
                        f"{viewport.name}/{tab}: pass={row['pass']} error={row['probe_error']} "
                        f"inner={row['innerWidth']} scroll={row['scrollWidth']}"
                    )
                rows.append(row)
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=8)
        except Exception:
            proc.kill()

    report_json = out_dir / "report.json"
    report_json.write_text(
        json.dumps(
            {
                "base_url": base_url,
                "edge_path": edge_path.as_posix(),
                "rows": rows,
                "errors": errors,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    lines = [
        f"# Layout Overflow Probe - {datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "",
        f"- base_url: {base_url}",
        f"- edge: {edge_path.as_posix()}",
        f"- output_dir: {out_dir.as_posix()}",
        "",
    ]
    for row in rows:
        lines.extend(
            [
                f"## {row['viewport']} / {row['tab']}",
                f"- pass: {row['pass']}",
                f"- innerWidth: {row['innerWidth']}",
                f"- scrollWidth: {row['scrollWidth']}",
                f"- bodyScrollWidth: {row['bodyScrollWidth']}",
                f"- probe_error: {row['probe_error'] or 'none'}",
                f"- screenshot: {row['screenshot']}",
                "",
            ]
        )
    if errors:
        lines.extend(["## errors", "```text", *errors, "```", ""])
    report_md = out_dir / "report.md"
    report_md.write_text("\n".join(lines), encoding="utf-8")
    print(report_md.as_posix())

    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())

