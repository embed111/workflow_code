#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

CRUD_KEYS = ("create", "read", "update", "delete")
MODES = {"required", "optional", "disabled"}
DISABLED_REQUIRED_FIELDS = ("reason", "trigger", "error_code", "user_message")


def load_json(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("root must be object")
    return raw


def validate(data: dict) -> list[str]:
    errors: list[str] = []
    features = data.get("features")
    if not isinstance(features, list) or not features:
        return ["features must be a non-empty list"]
    for idx, feature in enumerate(features, start=1):
        prefix = f"features[{idx}]"
        if not isinstance(feature, dict):
            errors.append(f"{prefix} must be object")
            continue
        fid = str(feature.get("id") or "").strip()
        if not fid:
            errors.append(f"{prefix}.id is required")
        crud = feature.get("crud")
        if not isinstance(crud, dict):
            errors.append(f"{prefix}.crud is required")
            continue
        for key in CRUD_KEYS:
            node = crud.get(key)
            node_prefix = f"{prefix}.crud.{key}"
            if not isinstance(node, dict):
                errors.append(f"{node_prefix} is required")
                continue
            mode = str(node.get("mode") or "").strip().lower()
            if mode not in MODES:
                errors.append(f"{node_prefix}.mode invalid: {mode!r}")
                continue
            if mode == "disabled":
                for field in DISABLED_REQUIRED_FIELDS:
                    val = str(node.get(field) or "").strip()
                    if not val:
                        errors.append(f"{node_prefix}.{field} is required when mode=disabled")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate CRUD declaration gate.")
    parser.add_argument(
        "--file",
        default="docs/workflow/crud-审查-Phase0.json",
        help="CRUD declaration file path",
    )
    args = parser.parse_args()

    path = Path(args.file).resolve()
    if not path.exists():
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "crud_declaration_not_found",
                    "path": path.as_posix(),
                },
                ensure_ascii=False,
            )
        )
        return 1

    try:
        data = load_json(path)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "crud_declaration_parse_failed",
                    "path": path.as_posix(),
                    "detail": str(exc),
                },
                ensure_ascii=False,
            )
        )
        return 1

    errors = validate(data)
    print(
        json.dumps(
            {
                "ok": not errors,
                "path": path.as_posix(),
                "errors": errors,
                "feature_count": len(data.get("features") or []),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
