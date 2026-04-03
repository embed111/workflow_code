from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def exec_local_parts(module_globals: dict[str, Any], module_file: str) -> None:
    module_path = Path(module_file).resolve()
    parts_dir = module_path.with_name(module_path.stem + "_parts")
    manifest_path = parts_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"module parts manifest missing: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise RuntimeError(f"invalid module parts manifest: {manifest_path}")
    for raw in payload:
        name = str(raw or "").strip()
        if not name:
            continue
        part_path = parts_dir / name
        if not part_path.exists() or not part_path.is_file():
            raise FileNotFoundError(f"module part missing: {part_path}")
        code = compile(part_path.read_text(encoding="utf-8"), str(part_path), "exec")
        exec(code, module_globals)
